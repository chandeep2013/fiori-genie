"""Google AI Studio (Gemini) provider.

Uses the free-tier-friendly Gemini API via the google-genai SDK. Gemini rejects
JSON Schema keywords like `additionalProperties`, so we sanitize Pydantic's
schema before asking for structured JSON.
"""

from __future__ import annotations

import copy
import concurrent.futures
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from . import ProviderError

# Prefer the floating alias so new AI Studio keys keep working as Google
# retires numbered flash models for new accounts.
DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TIMEOUT_S = 120

# Keys Gemini rejects when used as JSON Schema *metadata*.
# Do not strip these when they appear as property names under "properties".
_UNSUPPORTED_META_KEYS = {
    "additionalProperties",
    "additional_properties",
    "$schema",
    "default",
    "title",
    "examples",
    "const",
}

_COMPACT_RETRY = (
    "Your previous JSON response was truncated or invalid. "
    "Emit a COMPLETE application model as a single JSON object. "
    "Keep it small: at most 2 sampleData rows per entity, short labels, "
    "no long doc strings. Do not wrap in markdown."
)


def _sanitize_schema(node: Any, *, in_properties: bool = False) -> Any:
    """Strip unsupported JSON Schema metadata for Gemini.

    Property names under `properties` (e.g. a field literally called `title`)
    must be preserved; only schema annotation keys are removed.
    """
    if isinstance(node, dict):
        cleaned = {}
        for key, value in node.items():
            if in_properties:
                cleaned[key] = _sanitize_schema(value, in_properties=False)
                continue
            if key in _UNSUPPORTED_META_KEYS:
                continue
            cleaned[key] = _sanitize_schema(
                value, in_properties=(key == "properties")
            )
        return cleaned
    if isinstance(node, list):
        return [_sanitize_schema(item, in_properties=False) for item in node]
    return node


def _request_timeout_s() -> float:
    raw = os.getenv("FIORI_GENIE_LLM_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))
    try:
        return max(30.0, float(raw))
    except ValueError:
        return float(DEFAULT_TIMEOUT_S)


def _max_output_tokens() -> int:
    raw = os.getenv("FIORI_GENIE_MAX_OUTPUT_TOKENS", "65536")
    try:
        return max(2048, int(raw))
    except ValueError:
        return 65536


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return text.strip()


def _finish_reason(response: Any) -> str:
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""
        reason = getattr(candidates[0], "finish_reason", None)
        return str(reason or "")
    except Exception:
        return ""


def _extract_payload(response: Any) -> Tuple[Optional[Dict], str, str]:
    """Return (parsed_dict_or_None, raw_text, finish_reason)."""
    finish = _finish_reason(response)

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed, "", finish

    text = _strip_fences(getattr(response, "text", None) or "")
    if not text:
        return None, "", finish

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, text, finish

    if isinstance(data, dict):
        return data, text, finish
    return None, text, finish


def _looks_truncated(text: str, finish: str) -> bool:
    finish_l = finish.lower()
    if "max_token" in finish_l or finish_l.endswith("length") or "length" == finish_l:
        return True
    if not text:
        return False
    # Truncation almost always leaves an open string / structure.
    if text.rstrip()[-1:] not in ("}", "]"):
        return True
    return False


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: Optional[str] = None):
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'google-genai' package is not installed. Run:\n"
                "  pip install google-genai"
            ) from exc

        api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_AI_API_KEY")
        )
        if not api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Create one at "
                "https://aistudio.google.com/apikey and put it in .env"
            )

        self.model = model or os.getenv("FIORI_GENIE_MODEL") or DEFAULT_MODEL
        self._client = genai.Client(api_key=api_key)
        self.max_output_tokens = _max_output_tokens()
        self.timeout_s = _request_timeout_s()

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        from google.genai import types

        contents = self._to_contents(messages, types)
        clean_schema = _sanitize_schema(copy.deepcopy(schema))

        response = self._call(types, system, contents, clean_schema, with_schema=True)
        data, text, finish = _extract_payload(response)
        if data is not None:
            return data

        # One compact retry — free-tier / VPN responses often truncate mid-JSON.
        if text or _looks_truncated(text, finish) or not text:
            retry_messages = list(messages) + [
                {
                    "role": "assistant",
                    "content": text[:4000] if text else "(empty or truncated JSON)",
                },
                {"role": "user", "content": _COMPACT_RETRY},
            ]
            retry_contents = self._to_contents(retry_messages, types)
            response = self._call(
                types, system, retry_contents, clean_schema, with_schema=True
            )
            data, text, finish = _extract_payload(response)
            if data is not None:
                return data

        if not text:
            raise ProviderError(
                "Gemini returned an empty response"
                + (f" (finish_reason={finish})" if finish else "")
                + ". The free tier may be rate-limited — wait a minute and retry, "
                "or set FIORI_GENIE_MODEL=gemini-2.0-flash."
            )

        hint = ""
        if _looks_truncated(text, finish):
            hint = (
                " Response looks truncated"
                + (f" (finish_reason={finish})" if finish else "")
                + ". Try again, raise FIORI_GENIE_MAX_OUTPUT_TOKENS, or use a "
                "shorter spec. VPN inspection can also cut long JSON responses."
            )
        raise ProviderError(
            f"Gemini returned unparseable JSON: {self._json_error(text)}.{hint}"
        )

    def _json_error(self, text: str) -> str:
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return str(exc)
        return "unknown parse error"

    def _to_contents(self, messages: List[Dict], types: Any) -> List[Any]:
        contents = []
        for message in messages:
            role = "user" if message.get("role") == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=str(message.get("content") or ""))],
                )
            )
        return contents

    def _call(
        self,
        types: Any,
        system: str,
        contents: List[Any],
        clean_schema: Dict,
        *,
        with_schema: bool,
    ) -> Any:
        def _invoke() -> Any:
            try:
                config_kwargs: Dict[str, Any] = {
                    "system_instruction": system,
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                    "max_output_tokens": self.max_output_tokens,
                }
                if with_schema:
                    config_kwargs["response_json_schema"] = clean_schema
                return self._client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            except Exception as exc:
                message = str(exc)
                if with_schema and (
                    "INVALID_ARGUMENT" in message or "additionalProperties" in message
                ):
                    try:
                        return self._client.models.generate_content(
                            model=self.model,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                system_instruction=(
                                    system
                                    + "\n\nRespond with ONLY a JSON object that matches "
                                    "the application model schema. No markdown fences."
                                ),
                                response_mime_type="application/json",
                                temperature=0.2,
                                max_output_tokens=self.max_output_tokens,
                            ),
                        )
                    except Exception as retry_exc:
                        raise ProviderError(
                            f"Gemini request failed: {retry_exc}"
                        ) from retry_exc
                raise ProviderError(f"Gemini request failed: {exc}") from exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_invoke)
            try:
                return future.result(timeout=self.timeout_s)
            except concurrent.futures.TimeoutError as exc:
                raise ProviderError(
                    f"Gemini timed out after {int(self.timeout_s)}s. "
                    "Check VPN/network, or raise FIORI_GENIE_LLM_TIMEOUT_S."
                ) from exc
