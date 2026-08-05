"""OpenAI provider.

Uses non-strict function calling. Strict structured outputs would require every
property to be required and all defaults removed, which would mean maintaining
a second, degraded copy of the IR schema; Pydantic validation on the way back
already catches anything malformed.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from . import ProviderError

DEFAULT_MODEL = "gpt-4.1"
TOOL_NAME = "emit_application_model"


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not set")

        self.model = model or os.getenv("FIORI_GENIE_MODEL") or DEFAULT_MODEL
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        payload = [{"role": "system", "content": system}] + messages
        tool = {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": (
                    "Emit the structured CAP application model derived from the "
                    "functional specification."
                ),
                "parameters": schema,
            },
        }

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=payload,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        choice = response.choices[0]
        calls = choice.message.tool_calls or []
        if not calls:
            raise ProviderError(
                f"OpenAI returned no tool call (finish_reason={choice.finish_reason})"
            )

        try:
            return json.loads(calls[0].function.arguments)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"OpenAI returned unparseable tool arguments: {exc}") from exc
