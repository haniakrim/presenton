"""Bridges a Skywork-generated .pptx into Forge's Smart-mode editor.

Skywork returns a finished, pixel-positioned .pptx. Forge's Smart editor
requires per-slide HTML matching a strict contract: a `<section class="relative
h-[720px] w-[1280px] overflow-hidden">` root, no scrolling/clipping utilities,
and (via `inspect_smart_slide_layout`) no overlapping/off-canvas absolutely
positioned "meaningful" (text/media) elements.

`convert_pptx_to_html()` (export_task_service.py) renders each slide as a
single absolutely-positioned `<div>` tree with inline pixel styles — a
different but *compatible* layout model (the Smart validator's geometry
checks parse inline `style` positioning, not just Tailwind classes). The two
real gaps are: (1) the wrapper isn't a `<section>` with the required classes,
and (2) purely decorative shapes (background rectangles, accent bars) that
happen to sit behind text trip the overlap check, which has no auto-fix.

Strategy per slide:
1. Extract the single root `<div>` PowerPoint's renderer emits, rewrap it as
   a Smart-compliant `<section>`.
2. Tag content-free (svg/shape-only, no visible text) top-level children
   `aria-hidden="true"` so the layout inspector skips them — this resolves
   the overwhelming majority of real "background shape overlaps text"
   rejections, since inspect_smart_slide_layout only checks "meaningful"
   (text/media) nodes and explicitly skips aria-hidden ones.
3. Run the result through Forge's own `normalize_smart_slide_html` /
   `_slide_from_html` — the exact validator local Smart generation uses, so
   there is no drift between the two code paths.
4. If a slide still fails (dense text, genuine overlapping content, etc. —
   no auto-fix exists for these), fall back to rendering that single slide's
   original HTML to a flat image via the same export runtime and wrapping it
   in the minimal valid Smart-HTML shell. The deck never fails outright;
   individual slides degrade from editable to image-only.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from typing import Optional

from fastapi import HTTPException

from services.export_task_service import EXPORT_TASK_SERVICE, PptxToHtmlDocument
from utils.asset_directory_utils import (
    filesystem_image_path_to_app_data_url,
    get_images_directory,
)
from utils.llm_calls.generate_smart_presentation import _slide_from_html

logger = logging.getLogger(__name__)

_BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL | re.IGNORECASE)
_ROOT_DIV_OPEN_RE = re.compile(r'^\s*<div\s+style="([^"]*)"\s*>', re.IGNORECASE)
_BACKGROUND_RE = re.compile(r"background\s*:\s*([^;]+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>")
_OPEN_TAG_NAME_RE = re.compile(r"^<([a-zA-Z][a-zA-Z0-9]*)")
_VOID_TAGS = {
    "br", "hr", "img", "input", "meta", "link", "area", "base",
    "col", "embed", "param", "source", "track", "wbr",
}
_ASSET_REF_RE = re.compile(
    r'src="([^"]+)"|url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)', re.IGNORECASE
)


def _split_top_level_children(fragment: str) -> list[str]:
    """Split an HTML fragment into its top-level sibling elements (tag-agnostic depth count)."""
    children: list[str] = []
    depth = 0
    start: Optional[int] = None
    for match in _TAG_RE.finditer(fragment):
        closing, tag, self_close = match.group(1), match.group(2).lower(), match.group(3)
        is_void = bool(self_close) or tag in _VOID_TAGS
        if not closing:
            if depth == 0:
                start = match.start()
            if not is_void:
                depth += 1
            elif depth == 0 and start is not None:
                children.append(fragment[start : match.end()])
                start = None
        else:
            depth -= 1
            if depth == 0 and start is not None:
                children.append(fragment[start : match.end()])
                start = None
    return children


def _has_visible_text(chunk: str) -> bool:
    text = re.sub(r"<[^>]+>", " ", chunk)
    return bool(text.split())


def _mark_decorative(chunk: str) -> str:
    name_match = _OPEN_TAG_NAME_RE.match(chunk)
    if not name_match:
        return chunk
    tag = name_match.group(1)
    return re.sub(rf"^<{tag}\b", f'<{tag} aria-hidden="true"', chunk, count=1)


_OPEN_TAG_FULL_RE = re.compile(r"^<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")


def _tag_decorative(chunk: str) -> str:
    """Recursively hide (aria-hidden) any branch with no visible text anywhere inside it.

    A shape/icon can sit several levels deep (e.g. a "row" wrapper containing an
    icon div and a label div as siblings) — real PowerPoint output routinely
    nests this way, so tagging must walk the whole subtree, not just the
    slide's direct children, or a decorative icon next to a text label still
    trips Smart mode's sibling-overlap check.
    """
    if not _has_visible_text(chunk):
        return _mark_decorative(chunk)

    open_match = _OPEN_TAG_FULL_RE.match(chunk)
    if not open_match:
        return chunk
    tag = open_match.group(1).lower()
    if tag in _VOID_TAGS:
        return chunk

    stripped = chunk.rstrip()
    close_tag = f"</{tag}>"
    if not stripped.lower().endswith(close_tag):
        return chunk

    inner = stripped[open_match.end() : -len(close_tag)]
    children = _split_top_level_children(inner)
    if not children:
        # this node's own text lives directly inside it; nothing to recurse into
        return chunk

    retagged_inner = "".join(_tag_decorative(child) for child in children)
    return stripped[: open_match.end()] + retagged_inner + close_tag


def _extract_root(raw_slide_html: str) -> Optional[tuple[str, str]]:
    """Returns (background_css_value, inner_html) from a convert_pptx_to_html slide, or None."""
    body_match = _BODY_RE.search(raw_slide_html)
    body = body_match.group(1) if body_match else raw_slide_html
    open_match = _ROOT_DIV_OPEN_RE.match(body.strip())
    if not open_match:
        return None
    root_style = open_match.group(1)
    remainder = body.strip()[open_match.end() :].rstrip()
    if not remainder.endswith("</div>"):
        return None
    inner = remainder[: -len("</div>")]
    background_match = _BACKGROUND_RE.search(root_style)
    background = background_match.group(1).strip() if background_match else "#FFFFFF"
    return background, inner


def _rehost_asset(src_path: str) -> str:
    """Copy a file into app_data/images and return its servable URL."""
    dest_dir = get_images_directory()
    ext = os.path.splitext(src_path)[1] or ".png"
    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(dest_dir, dest_name)
    shutil.copyfile(src_path, dest_path)
    return filesystem_image_path_to_app_data_url(dest_path)


def _rehost_referenced_assets(html: str, images_dir: str) -> str:
    """Rewrite relative image/url() references to rehosted app_data/images URLs."""

    def replace(match: re.Match) -> str:
        ref = match.group(1) or match.group(2)
        if not ref or ref.startswith(("http://", "https://", "data:", "blob:", "/app_data/")):
            return match.group(0)
        source_path = os.path.normpath(os.path.join(images_dir, ref))
        if not os.path.isfile(source_path):
            return match.group(0)
        try:
            new_url = _rehost_asset(source_path)
        except OSError:
            logger.warning("[skywork_smart_bridge] failed to rehost asset %s", source_path)
            return match.group(0)
        return match.group(0).replace(ref, new_url)

    return _ASSET_REF_RE.sub(replace, html)


def _transpile_slide(raw_slide_html: str, images_dir: str) -> Optional[str]:
    extracted = _extract_root(raw_slide_html)
    if extracted is None:
        return None
    background, inner = extracted
    children = _split_top_level_children(inner)
    tagged = "".join(_tag_decorative(child) for child in children)
    section = (
        '<section class="relative h-[720px] w-[1280px] overflow-hidden" '
        f'style="background:{background}">{tagged}</section>'
    )
    return _rehost_referenced_assets(section, images_dir)


async def _image_fallback_slide(raw_slide_html: str, index: int) -> dict[str, str]:
    result = await EXPORT_TASK_SERVICE.render_html_to_image(raw_slide_html, 1280, 720)
    image_url = _rehost_asset(result.path)
    section = (
        '<section class="relative h-[720px] w-[1280px] overflow-hidden" '
        f'data-slide-title="Slide {index + 1}">'
        f'<img src="{image_url}" alt="" class="absolute inset-0 h-full w-full object-cover" />'
        "</section>"
    )
    return _slide_from_html(section, index)


async def build_smart_slides(pptx_path: str) -> list[dict[str, str]]:
    """Convert a .pptx into Smart-mode-compliant slides, one per source slide.

    Each slide is attempted as fully editable HTML first; any slide that
    fails Smart mode's own validator falls back to a flattened image so the
    whole deck never fails outright.
    """
    document: PptxToHtmlDocument = await EXPORT_TASK_SERVICE.convert_pptx_to_html(pptx_path)

    slides: list[dict[str, str]] = []
    for index, raw_slide_html in enumerate(document.slides):
        try:
            transpiled = _transpile_slide(raw_slide_html, document.images_dir)
            if transpiled is None:
                raise ValueError("could not locate the slide's root element")
            slides.append(_slide_from_html(transpiled, index))
            continue
        except (HTTPException, ValueError) as exc:
            logger.info(
                "[skywork_smart_bridge] slide %d failed Smart validation (%s); "
                "falling back to a flattened image",
                index,
                exc,
            )

        try:
            slides.append(await _image_fallback_slide(raw_slide_html, index))
        except Exception:
            logger.exception(
                "[skywork_smart_bridge] slide %d image fallback also failed; skipping",
                index,
            )

    return slides
