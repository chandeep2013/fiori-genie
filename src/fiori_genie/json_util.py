"""Best-effort repair for truncated LLM JSON payloads."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def loads_maybe_repaired(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON, repairing a truncated object/array when needed."""
    if not text or not text.strip():
        return None
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    repaired = _close_truncated(text)
    if repaired is None:
        return None
    try:
        data = json.loads(repaired)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _close_truncated(text: str) -> Optional[str]:
    """Close an open string and any unclosed { / [ so json.loads can succeed."""
    in_string = False
    escape = False
    stack = []
    for ch in text:
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()

    if not stack and not in_string:
        return None

    out = text.rstrip()
    # Drop a trailing comma / colon that usually sits before truncation.
    while out and out[-1] in ",:":
        out = out[:-1].rstrip()

    if in_string:
        out += '"'

    # After closing a string we may still have a dangling comma.
    while out and out[-1] in ",:":
        out = out[:-1].rstrip()

    while stack:
        out += stack.pop()
    return out
