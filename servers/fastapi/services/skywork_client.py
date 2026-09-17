"""Thin async client for Skywork's hosted PPT-generation API.

Ports the SSE handling from the bundled Claude Code skill
(`.claude/skills/skywork-ppt/scripts/run_ppt_write.py`) to async httpx, kept
free of FastAPI/DB imports so it can be unit-tested standalone.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

SKYWORK_GATEWAY_URL = "https://api-tools.skywork.ai/theme-gateway"

_PHASE_MESSAGES: dict[str, Callable[[dict[str, Any]], str]] = {
    "outline": lambda data: "Generating outline...",
    "outline_page": lambda data: (
        f"  Page {data.get('page_num') or 0}: "
        f"{' '.join(str(data.get('content') or '').split())[:300]}"
    ),
    "outline_done": lambda data: "Outline generated successfully!",
    "slides": lambda data: "Generating slides...",
    "slides_page_start": lambda data: (
        f"Start generating page {data.get('page_num') or 0}"
    ),
    "slides_page": lambda data: f"Finish generating Page {data.get('page_num') or 0}",
    "slides_done": lambda data: "Slides generated, exporting PPTX...",
    "export": lambda data: (
        "Export complete."
        if data.get("status") == "done"
        else "Exporting PPTX... this step takes 2-5 minutes."
    ),
    "done": lambda data: "Generation complete, saving file...",
    "ping": lambda data: (
        f"Now {data.get('progress', '')}% was done, and is working on {data.get('stage')}"
        if data.get("stage")
        else f"{data.get('progress', '')}%"
    ),
}


def phase_message(phase: str, data: dict[str, Any]) -> str:
    builder = _PHASE_MESSAGES.get(phase)
    if builder is None:
        return f"[{phase}]" if phase else "..."
    return builder(data)


class SkyworkError(Exception):
    """Raised when Skywork's stream ends without a usable download_url."""


def unwrap_sse_payload(raw: str) -> dict[str, Any]:
    """Unwrap the backend's `{"code":0,"message":"success","data": payload}` envelope.

    `data` may itself be a JSON-encoded string. Any parse failure yields `{}`
    rather than raising, matching the skill script's own tolerant behavior.
    """
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}

    data = parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


async def iter_sse(
    lines: AsyncIterator[str],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Parse an SSE stream (`event:`/`data:` lines, blank-line delimited) into events."""
    cur_event: Optional[str] = None
    cur_data: Optional[str] = None

    async for line in lines:
        line = line.rstrip("\r\n")
        if line == "":
            if cur_event is not None and cur_data is not None:
                yield cur_event, unwrap_sse_payload(cur_data)
            cur_event = None
            cur_data = None
            continue
        if line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:"):
            cur_data = line[5:].strip()

    if cur_event is not None and cur_data is not None:
        yield cur_event, unwrap_sse_payload(cur_data)


async def run_stream(
    lines: AsyncIterator[str],
    on_progress: Optional[Callable[[str, dict[str, Any]], Awaitable[None]]] = None,
) -> str:
    """Drive an already-open SSE line stream to completion. Returns the download_url.

    Pure event-handling logic, no httpx dependency, so it's directly unit-testable
    against a fake async line iterator.
    """
    async for event_type, data in iter_sse(lines):
        if on_progress is not None:
            await on_progress(event_type, data)

        if event_type == "error":
            message = data.get("message") or (
                "Skywork ended the stream with an empty error. Please try again."
            )
            raise SkyworkError(message)

        if event_type == "completionEvent" and data.get("phase") == "done":
            download_url = data.get("download_url")
            if not download_url:
                raise SkyworkError(
                    "Skywork reported completion without a download_url."
                )
            return download_url

    raise SkyworkError("Skywork's stream ended without a completion event.")


async def generate_pptx(
    api_key: str,
    query: str,
    language: str,
    reference: str,
    on_progress: Optional[Callable[[str, dict[str, Any]], Awaitable[None]]] = None,
) -> str:
    """Run a Skywork ppt_write_stream job to completion. Returns the download_url."""
    session_id = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "query": query,
        "language": language,
        "source_platform": "",
    }
    if reference:
        payload["reference"] = reference

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Session-Id": session_id,
        "Language": language,
        "Authorization": f"Bearer {api_key}",
    }

    timeout = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{SKYWORK_GATEWAY_URL}/ppt_write_stream",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                return await run_stream(response.aiter_lines(), on_progress)
    except httpx.HTTPError as exc:
        raise SkyworkError(f"Skywork request failed: {exc}") from exc


async def download_pptx(url: str, dest_path: str) -> None:
    timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(dest_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
    except httpx.HTTPError as exc:
        raise SkyworkError(f"Failed to download the generated file: {exc}") from exc
