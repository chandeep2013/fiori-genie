"""Tests for truncated JSON repair."""

from fiori_genie.json_util import loads_maybe_repaired
from fiori_genie.pipeline import _is_fatal_provider_error
from fiori_genie.providers import ProviderError


def test_repairs_truncated_object_mid_string():
    text = '{"namespace":"com.acme","projectName":"leave","entities":[{"name":"Leave'
    data = loads_maybe_repaired(text)
    assert data is not None
    assert data["projectName"] == "leave"
    assert data["entities"][0]["name"] == "Leave"


def test_repairs_truncated_after_property():
    text = '{"a":1,"b":{"c":true,'
    data = loads_maybe_repaired(text)
    assert data == {"a": 1, "b": {"c": True}}


def test_line_401_is_not_fatal():
    err = ProviderError(
        "Gemini returned unparseable JSON: Unterminated string starting at: "
        "line 401 column 19 (char 8507)"
    )
    assert not _is_fatal_provider_error(err)


def test_missing_api_key_is_fatal():
    assert _is_fatal_provider_error(ProviderError("GEMINI_API_KEY is not set"))
