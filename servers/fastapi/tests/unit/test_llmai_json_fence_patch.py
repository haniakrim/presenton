from llmai.openai.client import OpenAIClient
from llmai.shared import JSONObjectResponse

from utils import llmai_json_fence_patch


def _client() -> OpenAIClient:
    # No network/credentials needed: _final_content is a pure method on the
    # accumulated string content, doesn't touch self beyond the one helper
    # method it already calls (_assistant_content_to_openai_content).
    return OpenAIClient.__new__(OpenAIClient)


def test_apply_is_idempotent():
    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    patched_once = OpenAIClient._final_content
    llmai_json_fence_patch.apply()
    assert OpenAIClient._final_content is patched_once


def test_strips_json_fence_before_parsing():
    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    client = _client()

    fenced = '```json\n{"hello": "world"}\n```'
    result = client._final_content(fenced, JSONObjectResponse())
    assert result == {"hello": "world"}


def test_parses_plain_json_unchanged():
    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    client = _client()

    result = client._final_content('{"hello": "world"}', JSONObjectResponse())
    assert result == {"hello": "world"}


def test_non_json_response_format_returns_content_untouched():
    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    client = _client()

    fenced = '```json\n{"hello": "world"}\n```'
    result = client._final_content(fenced, None)
    assert result == fenced


def test_strips_fence_with_leading_prose():
    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    client = _client()

    prefixed = 'Here is the JSON:\n```json\n{"hello": "world"}\n```'
    result = client._final_content(prefixed, JSONObjectResponse())
    assert result == {"hello": "world"}


def test_extracts_json_embedded_in_prose_with_no_fence():
    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    client = _client()

    prose = 'Sure thing, here you go: {"hello": "world"} -- hope that helps!'
    result = client._final_content(prose, JSONObjectResponse())
    assert result == {"hello": "world"}


def test_genuinely_invalid_content_still_raises_with_context():
    import json

    import pytest

    llmai_json_fence_patch._applied = False
    llmai_json_fence_patch.apply()
    client = _client()

    with pytest.raises(json.JSONDecodeError):
        client._final_content("not json at all, no brackets either", JSONObjectResponse())
