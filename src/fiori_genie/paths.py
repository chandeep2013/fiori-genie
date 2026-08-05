"""Output path helpers — never silently overwrite a previous generation."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

GENERATED_ROOT = Path("generated")


def slugify_project_name(name: Optional[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "app").lower()).strip("-")
    return slug or "app"


def allocate_output_dir(
    project_name: Optional[str] = None,
    root: Path = GENERATED_ROOT,
    *,
    prefer_exact: Optional[Path] = None,
) -> Path:
    """Return a directory that does not already exist.

    Preference order:
    1. `prefer_exact` when given and free
    2. `root/<project-slug>` when free
    3. `root/<project-slug>-YYYYMMDD-HHMMSS` (and -2, -3… if needed)
    """
    if prefer_exact is not None and not prefer_exact.exists():
        return prefer_exact

    slug = slugify_project_name(project_name)
    root = Path(root)
    primary = root / slug
    if not primary.exists():
        return primary

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = root / f"{slug}-{stamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{slug}-{stamp}-{suffix}"
    return candidate
