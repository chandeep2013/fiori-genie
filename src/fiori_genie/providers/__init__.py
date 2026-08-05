"""LLM provider abstraction.

The pipeline only needs one operation: given a conversation, return a dict that
should parse as an `AppModel`. Keeping the interface this narrow is what makes
the SAP Generative AI Hub swap a configuration change rather than a rewrite.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Protocol


class Message(Dict):
    """A chat turn: {"role": "user"|"assistant", "content": str}."""


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    model: str

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        """Return a dict conforming to `schema`, or raise ProviderError."""
        ...


def get_provider(
    name: Optional[str] = None, model: Optional[str] = None
) -> Provider:
    """Resolve a provider from an explicit name or the environment."""
    name = (name or os.getenv("FIORI_GENIE_PROVIDER") or "").lower().strip()

    if not name:
        # Infer from whichever credential is present. Fall back to the offline
        # demo provider so Generate works without a paid API key.
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            name = "gemini"
        elif os.getenv("ANTHROPIC_API_KEY"):
            name = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            name = "openai"
        elif os.getenv("AICORE_CLIENT_ID"):
            name = "genai-hub"
        else:
            name = "demo"

    if name == "demo":
        from .demo_provider import DemoProvider

        return DemoProvider(model=model)
    if name in ("gemini", "google", "google-ai", "ai-studio"):
        from .gemini_provider import GeminiProvider

        return GeminiProvider(model=model)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(model=model)
    if name in ("genai-hub", "genaihub", "aicore"):
        from .genai_hub import GenAIHubProvider

        return GenAIHubProvider(model=model)

    raise ProviderError(
        f"Unknown provider '{name}'. Supported: demo, gemini, anthropic, openai, genai-hub."
    )


__all__ = ["Provider", "ProviderError", "get_provider"]
