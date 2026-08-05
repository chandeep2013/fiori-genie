"""Demo provider — no API key required.

Picks a canned application model by matching the pasted specification to a
known sample. Title lines are preferred over body keywords so shared phrases
(e.g. "plant maintenance" inside a purchase-requisition purpose) do not steal
the match. For arbitrary new specs, use a real LLM provider.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import ProviderError

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"

# (fixture name, title substring, body keyword regex)
_CATALOG: List[Tuple[str, str, str]] = [
    ("travel-expense", "travel expense", r"expense claim|\bex-000"),
    ("leave-request", "leave request", r"\blr-000|annual leave|sick leave"),
    (
        "maintenance-notification",
        "maintenance notification",
        r"\bmn-000|notification item",
    ),
    ("sales-quotation", "sales quotation", r"\bsq-000|quotation item"),
    ("supplier-invoice", "supplier invoice", r"\bsi-000|invoice intake"),
    (
        "purchase-requisition",
        "purchase requisition",
        r"\bpr-000|requisition item",
    ),
]

_DEFAULT = "purchase-requisition"


def _extract_spec_text(messages: List[Dict]) -> str:
    chunks = []
    for message in messages:
        if message.get("role") == "user":
            chunks.append(str(message.get("content") or ""))
    return "\n".join(chunks)


def resolve_fixture_name(spec_text: str) -> str:
    text = spec_text.lower()

    # Prefer the H1 / title line when present.
    title_match = re.search(
        r"functional specification:\s*([^\n]+)", text, re.IGNORECASE
    )
    if title_match:
        title = title_match.group(1).strip()
        for name, title_key, _ in _CATALOG:
            if title_key in title:
                return name

    for name, _, body_pattern in _CATALOG:
        if re.search(body_pattern, text, re.IGNORECASE):
            return name

    return _DEFAULT


class DemoProvider:
    name = "demo"

    def __init__(self, model: Optional[str] = None):
        self.model = model or "fixture/auto"
        if not _FIXTURE_DIR.is_dir():
            raise ProviderError(
                f"Demo fixture directory not found at {_FIXTURE_DIR}. "
                "Re-clone the repo or set ANTHROPIC_API_KEY / OPENAI_API_KEY."
            )

    def generate(self, system: str, messages: List[Dict], schema: Dict) -> Dict:
        fixture_name = resolve_fixture_name(_extract_spec_text(messages))
        path = _FIXTURE_DIR / f"{fixture_name}.json"
        if not path.is_file():
            raise ProviderError(f"Demo fixture missing: {path.name}")

        self.model = f"fixture/{fixture_name}"
        return json.loads(path.read_text(encoding="utf-8"))
