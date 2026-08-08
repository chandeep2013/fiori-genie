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
import time
from typing import Any, Dict, List, Optional, Tuple

from ..json_util import loads_maybe_repaired
from . import ProviderError

# Prefer the lite floating alias: free-tier accounts often exhaust the main
# Flash quota while flash-lite still has capacity.
DEFAULT_MODEL = "gemini-flash-lite-latest"
DEFAULT_TIMEOUT_S = 180

# Tried in order when the primary model returns 503 high-demand.
_FALLBACK_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
)

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

# sampleData balloons the response and is the #1 truncation cause — drop it
# from the constrained schema; CSV rows are optional for a runnable app.
_SCHEMA_DROP_PROPERTIES = {"sampleData"}

_COMPACT_RETRY = (
    "Your previous JSON response was truncated or invalid. "
    "Emit a COMPLETE smaller application model as one JSON object. "
    "Omit sampleData entirely. Use short labels, at most 3 entities, "
    "one service, one app. Do not wrap in markdown."
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
                if key in _SCHEMA_DROP_PROPERTIES:
                    continue
                cleaned[key] = _sanitize_schema(value, in_properties=False)
                continue
            if key in _UNSUPPORTED_META_KEYS:
                continue
            if key == "required" and isinstance(value, list):
                cleaned[key] = [item for item in value if item not in _SCHEMA_DROP_PROPERTIES]
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
    # Thinking-capable models share this budget with "thinking" tokens.
    # Keep it high, and set thinking_budget=0 so JSON is not starved.
    raw = os.getenv("FIORI_GENIE_MAX_OUTPUT_TOKENS", "8192")
    try:
        return max(2048, int(raw))
    except ValueError:
        return 8192


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

    data = loads_maybe_repaired(text)
    if data is not None:
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
        system = (
            system
            + "\n\nOmit sampleData from the JSON. Keep the model compact so the "
            "response cannot be truncated."
        )

        response = self._call(types, system, contents, clean_schema, with_schema=True)
        data, text, finish = _extract_payload(response)
        if data is not None:
            return data

        # Compact retry with schema, then one last attempt without schema.
        for with_schema in (True, False):
            retry_messages = list(messages) + [
                {
                    "role": "assistant",
                    "content": (text[:2000] if text else "(empty or truncated JSON)"),
                },
                {"role": "user", "content": _COMPACT_RETRY},
            ]
            retry_contents = self._to_contents(retry_messages, types)
            response = self._call(
                types, system, retry_contents, clean_schema, with_schema=with_schema
            )
            data, text, finish = _extract_payload(response)
            if data is not None:
                return data

        if not text:
            raise ProviderError(
                "Gemini returned an empty response"
                + (f" (finish_reason={finish})" if finish else "")
                + ". The free tier may be rate-limited — wait a minute and retry, "
                "set FIORI_GENIE_MODEL=gemini-flash-lite-latest, or use "
                "FIORI_GENIE_PROVIDER=demo."
            )

        hint = ""
        if _looks_truncated(text, finish):
            hint = (
                " Response looks truncated"
                + (f" (finish_reason={finish})" if finish else "")
                + ". Retry, shorten the spec, or use FIORI_GENIE_PROVIDER=demo."
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

    def _model_candidates(self) -> List[str]:
        ordered: List[str] = []
        for name in (self.model, *_FALLBACK_MODELS):
            if name and name not in ordered:
                ordered.append(name)
        return ordered

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
            last_exc: Optional[Exception] = None
            models = self._model_candidates()
            for index, model in enumerate(models):
                try:
                    return self._generate_once(
                        types,
                        system,
                        contents,
                        clean_schema,
                        model=model,
                        with_schema=with_schema,
                    )
                except ProviderError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    message = str(exc)
                    if _is_overload_error(exc) and index < len(models) - 1:
                        time.sleep(min(2**index, 8))
                        continue
                    if with_schema and (
                        "INVALID_ARGUMENT" in message
                        or "additionalProperties" in message
                    ):
                        try:
                            return self._generate_once(
                                types,
                                system
                                + "\n\nRespond with ONLY a JSON object that matches "
                                "the application model schema. No markdown fences. "
                                "Omit sampleData.",
                                contents,
                                clean_schema,
                                model=model,
                                with_schema=False,
                            )
                        except Exception as retry_exc:
                            raise ProviderError(
                                _friendly_gemini_error(retry_exc)
                            ) from retry_exc
                    if _is_overload_error(exc):
                        # Try next model even if schema path did not apply.
                        if index < len(models) - 1:
                            time.sleep(min(2**index, 8))
                            continue
                    raise ProviderError(_friendly_gemini_error(exc)) from exc
            raise ProviderError(
                _friendly_gemini_error(last_exc or RuntimeError("Gemini unavailable"))
            )

        # Allow model fallbacks + short sleeps inside one outer timeout.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_invoke)
            try:
                return future.result(timeout=self.timeout_s)
            except concurrent.futures.TimeoutError as exc:
                raise ProviderError(
                    f"Gemini timed out after {int(self.timeout_s)}s. "
                    "Check VPN/network, or raise FIORI_GENIE_LLM_TIMEOUT_S."
                ) from exc

    def _generate_once(
        self,
        types: Any,
        system: str,
        contents: List[Any],
        clean_schema: Dict,
        *,
        model: str,
        with_schema: bool,
    ) -> Any:
        config_kwargs: Dict[str, Any] = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "max_output_tokens": self.max_output_tokens,
        }
        if with_schema:
            config_kwargs["response_json_schema"] = clean_schema
        # Prevent thinking tokens from eating the whole output budget.
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass

        try:
            return self._client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            # Older / non-thinking models reject thinking_config.
            if "thinking" in str(exc).lower() and "thinking_config" in config_kwargs:
                config_kwargs.pop("thinking_config", None)
                return self._client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            raise


def _is_overload_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return any(
        marker in lowered
        for marker in (
            "503",
            "unavailable",
            "high demand",
            "overloaded",
            "try again later",
            "temporarily",
        )
    )


def _friendly_gemini_error(exc: Exception) -> str:
    """Map Google quota/auth failures to actionable guidance."""
    message = str(exc)
    lowered = message.lower()
    if _is_overload_error(exc):
        return (
            "Gemini is temporarily overloaded (503 high demand). "
            "This is on Google's side, not your API key. Wait a minute and retry, "
            "or set FIORI_GENIE_PROVIDER=demo to generate from the sample specs "
            "without calling Gemini. Original error: "
            f"{message}"
        )
    if any(
        marker in lowered
        for marker in (
            "resource_exhausted",
            "quota",
            "rate limit",
            "429",
            "exceeded your current quota",
        )
    ):
        return (
            "Gemini quota exceeded (this is per Google project / day, not per API key). "
            "A new key in the same AI Studio project usually does not reset the limit. "
            "Options: wait for the daily reset; create a key in a brand-new Google Cloud "
            "project at https://aistudio.google.com/apikey; try "
            "FIORI_GENIE_MODEL=gemini-flash-lite-latest; or set FIORI_GENIE_PROVIDER=demo for "
            "offline sample-spec generation. Original error: "
            f"{message}"
        )
    if "not available in your country" in lowered or "failed_precondition" in lowered:
        return (
            "Gemini free tier is not available for this project/region. "
            "Enable billing in Google AI Studio, or use FIORI_GENIE_PROVIDER=demo. "
            f"Original error: {message}"
        )
    return f"Gemini request failed: {message}"
