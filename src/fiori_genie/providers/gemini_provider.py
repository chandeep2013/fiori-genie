"""Google AI Studio (Gemini) provider.

Uses the free-tier-friendly Gemini API via the google-genai SDK. Gemini rejects
JSON Schema keywords like `additionalProperties`, so we sanitize Pydantic's
schema before asking for structured JSON.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional

from . import ProviderError

# Prefer the floating alias so new AI Studio keys keep working as Google
# retires numbered flash models for new accounts.
DEFAULT_MODEL = "gemini-flash-latest"

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

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        from google.genai import types

        contents = []
        for message in messages:
            role = "user" if message.get("role") == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=str(message.get("content") or ""))],
                )
            )

        clean_schema = _sanitize_schema(copy.deepcopy(schema))

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=clean_schema,
                    temperature=0.2,
                    max_output_tokens=16384,
                ),
            )
        except Exception as exc:
            # Fallback: JSON mode without schema on any 400-class schema problem.
            message = str(exc)
            if "INVALID_ARGUMENT" in message or "additionalProperties" in message:
                try:
                    response = self._client.models.generate_content(
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
                            max_output_tokens=16384,
                        ),
                    )
                except Exception as retry_exc:
                    raise ProviderError(f"Gemini request failed: {retry_exc}") from retry_exc
            else:
                raise ProviderError(f"Gemini request failed: {exc}") from exc

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise ProviderError(
                "Gemini returned an empty response. The free tier may be rate-"
                "limited — wait a minute and retry, or set "
                "FIORI_GENIE_MODEL=gemini-2.0-flash."
            )

        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini returned unparseable JSON: {exc}") from exc
