import asyncio

import pytest

from services.skywork_client import (
    SkyworkError,
    phase_message,
    run_stream,
    unwrap_sse_payload,
)


async def _alist(items):
    for item in items:
        yield item


def _sse(*lines: str) -> list[str]:
    """Join event/data pairs into a flat SSE line list with blank-line delimiters."""
    out: list[str] = []
    for line in lines:
        out.append(line)
    return out


def test_unwrap_sse_payload_plain_envelope():
    raw = '{"code":0,"message":"success","data":{"phase":"outline"}}'
    assert unwrap_sse_payload(raw) == {"phase": "outline"}


def test_unwrap_sse_payload_string_encoded_data():
    raw = '{"code":0,"message":"success","data":"{\\"phase\\":\\"slides\\"}"}'
    assert unwrap_sse_payload(raw) == {"phase": "slides"}


def test_unwrap_sse_payload_malformed_json_yields_empty_dict():
    assert unwrap_sse_payload("not json") == {}


def test_unwrap_sse_payload_empty_object():
    assert unwrap_sse_payload("{}") == {}


@pytest.mark.parametrize(
    "phase,data,expected_substring",
    [
        ("outline", {}, "Generating outline"),
        ("outline_done", {}, "Outline generated successfully"),
        ("slides", {}, "Generating slides"),
        ("slides_page_start", {"page_num": 3}, "Start generating page 3"),
        ("slides_page", {"page_num": 3}, "Finish generating Page 3"),
        ("slides_done", {}, "exporting PPTX"),
        ("export", {"status": "done"}, "Export complete."),
        ("export", {}, "Exporting PPTX"),
        ("done", {}, "Generation complete"),
        ("ping", {"progress": 42, "stage": "Preparing content"}, "42% was done"),
    ],
)
def test_phase_message_table(phase, data, expected_substring):
    assert expected_substring in phase_message(phase, data)


def test_phase_message_unknown_phase_is_bracketed():
    assert phase_message("mystery", {}) == "[mystery]"


def test_run_stream_returns_download_url_on_completion():
    lines = _sse(
        "event: phase",
        'data: {"code":0,"message":"success","data":{"phase":"outline"}}',
        "",
        "event: completionEvent",
        'data: {"code":0,"message":"success","data":{"phase":"done","download_url":"https://cdn.example.com/x.pptx"}}',
        "",
    )

    async def run():
        events = []

        async def on_progress(event_type, data):
            events.append((event_type, data))

        url = await run_stream(_alist(lines), on_progress)
        assert url == "https://cdn.example.com/x.pptx"
        assert events[0][0] == "phase"
        assert events[-1][0] == "completionEvent"

    asyncio.run(run())


def test_run_stream_raises_on_bare_empty_error():
    lines = _sse(
        "event: phase",
        'data: {"code":0,"message":"success","data":{"phase":"slides"}}',
        "",
        "event: error",
        "data: {}",
        "",
    )

    async def run():
        with pytest.raises(SkyworkError, match="empty error"):
            await run_stream(_alist(lines))

    asyncio.run(run())


def test_run_stream_raises_on_error_with_message():
    lines = _sse("event: error", 'data: {"message":"invalid api key"}', "")

    async def run():
        with pytest.raises(SkyworkError, match="invalid api key"):
            await run_stream(_alist(lines))

    asyncio.run(run())


def test_run_stream_raises_when_stream_ends_without_completion():
    lines = _sse(
        "event: phase",
        'data: {"code":0,"message":"success","data":{"phase":"outline"}}',
        "",
    )

    async def run():
        with pytest.raises(SkyworkError, match="without a completion event"):
            await run_stream(_alist(lines))

    asyncio.run(run())
