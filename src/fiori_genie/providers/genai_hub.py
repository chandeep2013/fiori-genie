"""SAP Generative AI Hub provider (AI Core).

NOT YET VERIFIED against a live BTP subaccount — it was written from the SDK's
documented OpenAI-compatible surface but has not been run end to end. Treat it
as the migration path off a direct vendor key, and expect to adjust the client
construction once you have AI Core credentials to test with.

Requires `pip install generative-ai-hub-sdk` and the standard AICORE_* variables
(AICORE_CLIENT_ID, AICORE_CLIENT_SECRET, AICORE_AUTH_URL, AICORE_BASE_URL,
AICORE_RESOURCE_GROUP), which the SDK reads itself.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from . import ProviderError

DEFAULT_MODEL = "anthropic--claude-4-sonnet"
TOOL_NAME = "emit_application_model"


class GenAIHubProvider:
    name = "genai-hub"

    def __init__(self, model: Optional[str] = None):
        try:
            from gen_ai_hub.proxy.native.openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise ProviderError(
                "The 'generative-ai-hub-sdk' package is not installed. Run:\n"
                "  pip install generative-ai-hub-sdk\n"
                "and configure the AICORE_* environment variables."
            ) from exc

        self.model = model or os.getenv("FIORI_GENIE_MODEL") or DEFAULT_MODEL
        self._client = OpenAI()

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        payload = [{"role": "system", "content": system}] + messages
        tool = {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": "Emit the structured CAP application model.",
                "parameters": schema,
            },
        }

        try:
            response = self._client.chat.completions.create(
                model_name=self.model,
                messages=payload,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            )
        except Exception as exc:
            raise ProviderError(f"Generative AI Hub request failed: {exc}") from exc

        calls = response.choices[0].message.tool_calls or []
        if not calls:
            raise ProviderError("Generative AI Hub returned no tool call")

        try:
            return json.loads(calls[0].function.arguments)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Unparseable tool arguments: {exc}") from exc
