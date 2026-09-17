"""Workaround for a real llmai SDK gap when talking to non-strict OpenAI-compatible
backends (confirmed live against Ollama Cloud, multiple models).

Real OpenAI/Anthropic/Google enforce `response_format=json_schema`/`json_object`
server-side and never wrap the response in a markdown code fence, so llmai's
OpenAIClient._final_content() has no reason to defend against one -- it calls
json.loads() directly on the accumulated content. Ollama Cloud does not reliably
enforce structured output: the model sometimes free-generates and wraps its JSON
in a ```json fence regardless of the requested response_format, which crashes
every retry with "Expecting value: line 1 column 1 (char 0)" before Presenton's
own code (extract_structured_content's dirtyjson fallback) ever sees the content.

This patches _final_content to strip a leading/trailing markdown fence before
parsing -- the same defensive pattern already used for Smart-mode HTML
(_FENCE_PATTERN in utils/llm_calls/generate_smart_presentation.py) -- rather
than editing the vendored package directly, which wouldn't survive a reinstall.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# A fenced block anywhere in the text (not just anchored at start/end) --
# covers "Here is the JSON:\n```json\n{...}\n```" style prefixed responses,
# not just a response that is *only* a fence.
_FENCED_BLOCK = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_ANCHORED_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

_applied = False


def _extract_bracketed_json(text: str) -> str | None:
    """Find the first balanced {...} or [...] span in free-form text.

    Covers responses that embed JSON in prose with no code fence at all.
    """
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == open_ch:
                depth += 1
            elif char == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
    return None


def _parse_lenient_json(text_content: str) -> object:
    """Try progressively looser extraction strategies before giving up."""
    attempts = [text_content]

    fenced_match = _FENCED_BLOCK.search(text_content)
    if fenced_match:
        attempts.append(fenced_match.group(1).strip())

    attempts.append(_ANCHORED_FENCE.sub("", text_content).strip())

    bracketed = _extract_bracketed_json(text_content)
    if bracketed:
        attempts.append(bracketed)

    last_error: json.JSONDecodeError | None = None
    for attempt in attempts:
        if not attempt:
            continue
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

    logger.warning(
        "[llmai_json_fence_patch] all lenient JSON parse strategies failed; "
        "raw content (first 1000 chars): %r",
        text_content[:1000],
    )
    raise last_error or json.JSONDecodeError("Expecting value", text_content, 0)


def apply() -> None:
    global _applied
    if _applied:
        return

    try:
        from llmai.openai.client import OpenAIClient
        from llmai.shared import JSONObjectResponse, JSONSchemaResponse
    except ImportError:
        logger.warning(
            "[llmai_json_fence_patch] llmai.openai.client not importable; skipping"
        )
        return

    def patched_final_content(self, content, response_format):
        text_content = self._assistant_content_to_openai_content(content)
        if text_content and isinstance(
            response_format, (JSONSchemaResponse, JSONObjectResponse)
        ):
            return _parse_lenient_json(text_content)
        return content

    OpenAIClient._final_content = patched_final_content
    _applied = True
    logger.info(
        "[llmai_json_fence_patch] applied lenient JSON extraction to "
        "OpenAIClient._final_content"
    )
