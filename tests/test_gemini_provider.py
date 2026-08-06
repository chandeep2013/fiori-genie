"""Unit tests for Gemini response handling helpers (no live API calls)."""

from __future__ import annotations

from types import SimpleNamespace

from fiori_genie.pipeline import _is_fatal_provider_error
from fiori_genie.providers import ProviderError
from fiori_genie.providers.gemini_provider import (
    _extract_payload,
    _looks_truncated,
    _strip_fences,
)


def test_strip_fences():
    assert _strip_fences('```json\n{"a":1}\n```') == '{"a":1}'


def test_extract_payload_prefers_parsed_dict():
    response = SimpleNamespace(
        parsed={"namespace": "com.acme"},
        text="ignored",
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )
    data, text, finish = _extract_payload(response)
    assert data == {"namespace": "com.acme"}
    assert text == ""
    assert "STOP" in finish


def test_extract_payload_parses_text_json():
    response = SimpleNamespace(
        parsed=None,
        text='{"ok": true}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )
    data, text, finish = _extract_payload(response)
    assert data == {"ok": True}
    assert text.startswith("{")


def test_looks_truncated_open_brace():
    assert _looks_truncated('{"namespace": "com.acme", "entities": [{"name": "', "STOP")
    assert not _looks_truncated('{"a":1}', "STOP")
    assert _looks_truncated('{"a":1', "MAX_TOKENS")


def test_fatal_provider_errors():
    assert _is_fatal_provider_error(ProviderError("GEMINI_API_KEY is not set"))
    assert not _is_fatal_provider_error(
        ProviderError("Gemini returned unparseable JSON: Unterminated string")
    )
