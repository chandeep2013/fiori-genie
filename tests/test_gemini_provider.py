"""Unit tests for Gemini response handling helpers (no live API calls)."""

from __future__ import annotations

from types import SimpleNamespace

from fiori_genie.pipeline import _is_fatal_provider_error
from fiori_genie.providers import ProviderError
from fiori_genie.providers.gemini_provider import (
    _extract_payload,
    _friendly_gemini_error,
    _looks_truncated,
    _sanitize_schema,
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


def test_friendly_quota_error():
    msg = _friendly_gemini_error(
        RuntimeError("429 RESOURCE_EXHAUSTED Quota exceeded for metric")
    )
    assert "per Google project" in msg
    assert "demo" in msg


def test_sanitize_schema_drops_sample_data():
    schema = {
        "type": "object",
        "properties": {
            "projectName": {"type": "string"},
            "sampleData": {"type": "object"},
            "title": {"type": "string"},  # property name must survive
        },
        "required": ["projectName", "sampleData"],
    }
    cleaned = _sanitize_schema(schema)
    assert "sampleData" not in cleaned["properties"]
    assert "sampleData" not in cleaned["required"]
    assert "title" in cleaned["properties"]
