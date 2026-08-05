"""Anthropic provider.

Uses a forced tool call rather than free-text JSON: the tool's input_schema is
the IR's JSON schema, so the response arrives already shaped and there is no
fenced-code or prose stripping to do.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from . import ProviderError

DEFAULT_MODEL = "claude-sonnet-4-5"
TOOL_NAME = "emit_application_model"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: Optional[str] = None, max_tokens: int = 16000):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")

        self.model = model or os.getenv("FIORI_GENIE_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        tool = {
            "name": TOOL_NAME,
            "description": (
                "Emit the structured CAP application model derived from the "
                "functional specification."
            ),
            "input_schema": schema,
        }

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except Exception as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
                return dict(block.input)

        raise ProviderError(
            f"Anthropic returned no '{TOOL_NAME}' tool call "
            f"(stop_reason={response.stop_reason}). The model may have hit the "
            "token limit; try a shorter specification."
        )
