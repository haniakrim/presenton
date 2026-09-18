import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.export_task_service import HtmlToImageTaskResult, PptxToHtmlDocument
from services.skywork_smart_bridge import (
    _extract_root,
    _has_visible_text,
    _rehost_referenced_assets,
    _sanitized_smart_slide,
    _split_top_level_children,
    _tag_decorative,
    _transpile_slide,
    build_smart_slides,
)

REAL_SAMPLE_SLIDE_HTML = (
    '<!doctype html><html><head><meta charset="utf-8"><style>'
    "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#FFFFFF}"
    "</style></head><body>"
    '<div style="position:relative;width:1280px;height:720.02px;overflow:hidden;background:#FFFFFF">'
    '<div style="box-sizing:border-box;position:absolute;left:48px;top:28.83px;width:864.02px;'
    'height:120px;color:#111827;">'
    '<span style="display:block;width:100%;font-size:0">'
    '<span style="color:#111827;">Root Cause Deep Dive</span></span></div>'
    '<div style="box-sizing:border-box;position:absolute;left:768.02px;top:480.01px;width:288.01px;'
    'height:144.01px;overflow:visible">'
    '<svg width="100%" height="100%" viewBox="0 0 288.01 144.01"><polygon points="0,0 288.01,0 '
    '288.01,144.01 0,144.01" fill="#4F81BD"/></svg></div>'
    '<div style="box-sizing:border-box;position:absolute;left:768.02px;top:480.01px;width:288.01px;'
    'height:144px;color:#111827;">'
    '<span style="display:block;width:100%;font-size:0">'
    '<span style="color:#111827;">Shape</span></span></div>'
    "</div></body></html>"
)


def test_split_top_level_children_ignores_nested_tags():
    fragment = "<div><span>a</span></div><svg><polygon/></svg>"
    children = _split_top_level_children(fragment)
    assert children == ["<div><span>a</span></div>", "<svg><polygon/></svg>"]


def test_has_visible_text():
    assert _has_visible_text('<div style="x">hello</div>') is True
    assert _has_visible_text("<div><svg><polygon/></svg></div>") is False


def test_tag_decorative_marks_only_text_free_children():
    text_chunk = '<div style="x">hello</div>'
    shape_chunk = "<div><svg><polygon/></svg></div>"
    assert _tag_decorative(text_chunk) == text_chunk
    assert 'aria-hidden="true"' in _tag_decorative(shape_chunk)


def test_extract_root_returns_background_and_inner():
    result = _extract_root(REAL_SAMPLE_SLIDE_HTML)
    assert result is not None
    background, inner = result
    assert background == "#FFFFFF"
    assert "Root Cause Deep Dive" in inner
    assert inner.strip().endswith("</div>")


def test_extract_root_returns_none_for_unrecognized_shape():
    assert _extract_root("<html><body><p>no root div</p></body></html>") is None


def test_transpile_slide_produces_a_well_formed_section():
    transpiled = _transpile_slide(REAL_SAMPLE_SLIDE_HTML, "/nonexistent")
    assert transpiled is not None
    assert transpiled.startswith(
        '<section class="relative h-[720px] w-[1280px] overflow-hidden"'
    )
    assert transpiled.rstrip().endswith("</section>")
    # the background shape (svg-only, no text) is tagged decorative for
    # accessibility - it does not affect visual rendering, and overlapping
    # "meaningful" content (the "Shape" text label on top of it) is no
    # longer rejected: Skywork's own design is trusted, not re-validated as
    # if it were fresh LLM output.
    assert '<div aria-hidden="true" style=' in transpiled

    # security sanitization still applies; content-quality validation does not
    slide = _sanitized_smart_slide(transpiled, 0)
    assert slide["html"] == transpiled
    assert slide["title"] == "Slide 1"


def test_transpile_slide_returns_none_when_root_cannot_be_found():
    assert _transpile_slide("<html><body><p>x</p></body></html>", "/nonexistent") is None


def test_sanitized_smart_slide_strips_unsafe_content():
    html = (
        '<section class="relative h-[720px] w-[1280px] overflow-hidden">'
        '<script>alert(1)</script>'
        '<div onclick="alert(2)">hi</div>'
        '<a href="javascript:alert(3)">click</a>'
        "</section>"
    )
    slide = _sanitized_smart_slide(html, 2)
    assert "<script>" not in slide["html"]
    assert "onclick" not in slide["html"]
    assert "javascript:" not in slide["html"]
    assert slide["title"] == "Slide 3"
    assert slide["slide_type"] == "content"


def test_rehost_referenced_assets_resolves_manifest_relative_paths(tmp_path):
    # convert_pptx_to_html's manifest points images_dir at the "images/"
    # folder itself, but slide HTML references assets relative to the
    # manifest's own directory (the folder *containing* images/), e.g.
    # src="images/slide.png" - asset_root must be that containing folder,
    # not images_dir, or every reference silently fails to rehost.
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "SK-1-img-1-abc123.png").write_bytes(b"fake-png")

    html = '<img src="images/SK-1-img-1-abc123.png">'
    with patch(
        "services.skywork_smart_bridge._rehost_asset",
        return_value="/app_data/images/rehosted.png",
    ) as mock_rehost:
        result = _rehost_referenced_assets(html, str(tmp_path))

    mock_rehost.assert_called_once_with(str(images_dir / "SK-1-img-1-abc123.png"))
    assert result == '<img src="/app_data/images/rehosted.png">'


def test_build_smart_slides_uses_transpile_and_falls_back_on_failure():
    good_slide = REAL_SAMPLE_SLIDE_HTML
    bad_slide = "<html><body><p>unrecognized shape, forces the fallback path</p></body></html>"

    document = PptxToHtmlDocument(
        slides=[good_slide, bad_slide],
        width=1280.0,
        height=720.0,
        images_dir="/nonexistent",
        fonts_dir="/nonexistent",
    )

    async def run():
        with patch(
            "services.skywork_smart_bridge.EXPORT_TASK_SERVICE"
        ) as mock_service:
            mock_service.convert_pptx_to_html = AsyncMock(return_value=document)
            mock_service.render_html_to_image = AsyncMock(
                return_value=HtmlToImageTaskResult(path="/nonexistent/fallback.png")
            )
            with patch(
                "services.skywork_smart_bridge._rehost_asset",
                return_value="/app_data/images/fallback.png",
            ):
                slides = await build_smart_slides("/nonexistent/sample.pptx")

        assert len(slides) == 2
        # slide 0: transpiled, fully editable
        assert "Root Cause Deep Dive" in slides[0]["html"]
        assert 'aria-hidden="true"' in slides[0]["html"]
        # slide 1: fell back to a flattened image after transpile returned None
        assert "<img" in slides[1]["html"]
        assert "/app_data/images/fallback.png" in slides[1]["html"]
        mock_service.render_html_to_image.assert_awaited_once_with(bad_slide, 1280, 720)

    asyncio.run(run())
