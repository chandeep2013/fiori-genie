"""Demo provider — no API key required.

Returns the built-in purchase-requisition fixture so the full Generate →
compile → download loop can be exercised without a paid LLM. Useful for local
demos and CI. Swap to anthropic/openai once you have a real key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from . import ProviderError

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "purchase-requisition.json"
)


class DemoProvider:
    name = "demo"
    model = "fixture/purchase-requisition"

    def __init__(self, model: Optional[str] = None):
        if model:
            self.model = model
        if not _FIXTURE.is_file():
            raise ProviderError(
                f"Demo fixture not found at {_FIXTURE}. "
                "Re-clone the repo or set ANTHROPIC_API_KEY / OPENAI_API_KEY."
            )
        self._payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        # Ignore the prompt and schema — this is a canned response for demos.
        return dict(self._payload)
