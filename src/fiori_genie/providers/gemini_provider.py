"""Google AI Studio (Gemini) provider.

Uses the free-tier-friendly Gemini API via the google-genai SDK. Structured
output is enforced by passing our Pydantic AppModel as response_schema so the
repair loop still receives a dict shaped like the IR.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from . import ProviderError

# Flash models are the usual free-tier choice in AI Studio.
DEFAULT_MODEL = "gemini-2.5-flash"


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

        from ..ir import AppModel

        contents = []
        for message in messages:
            role = "user" if message.get("role") == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=str(message.get("content") or ""))],
                )
            )

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=AppModel,
                    temperature=0.2,
                    max_output_tokens=16384,
                ),
            )
        except Exception as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        if getattr(response, "parsed", None) is not None:
            parsed = response.parsed
            if hasattr(parsed, "model_dump"):
                return parsed.model_dump(by_alias=True, mode="json")
            if isinstance(parsed, dict):
                return parsed

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise ProviderError(
                "Gemini returned an empty response. The free tier may be rate-"
                "limited — wait a minute and retry, or try model gemini-2.0-flash."
            )

        # Models sometimes wrap JSON in fences despite response_mime_type.
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].lstrip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini returned unparseable JSON: {exc}") from exc
