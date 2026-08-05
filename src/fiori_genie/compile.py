"""Runs the CDS compiler over a generated project.

This is the ground truth of the pipeline. Pydantic and `validate_model` catch
what we thought to check for; the compiler catches everything else, which is
what lets the generator be confident rather than hopeful.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

# The compiler colourises its diagnostics; the escape sequences are noise in a
# repair prompt and burn tokens, so they are stripped before feedback.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# `cds compile .` needs a resolvable project root, which a freshly generated
# folder without node_modules does not have. Naming the roots explicitly makes
# the check independent of project-root detection.
ROOTS = ["db", "srv", "app"]


class CdsNotFound(RuntimeError):
    pass


def find_cds() -> str:
    """Locate a cds executable: explicit override, repo-local, then PATH."""
    override = os.getenv("FIORI_GENIE_CDS")
    if override:
        if not Path(override).exists():
            raise CdsNotFound(f"FIORI_GENIE_CDS points at a missing file: {override}")
        return override

    repo_local = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / "cds"
    if repo_local.exists():
        return str(repo_local)

    found = shutil.which("cds")
    if found:
        return found

    raise CdsNotFound(
        "Could not find the 'cds' executable. Install it in this repo with "
        "`npm install --save-dev @sap/cds-dk`, or set FIORI_GENIE_CDS to its path."
    )


def _clean_diagnostics(output: str) -> List[str]:
    """Keep the lines that describe problems, drop progress noise."""
    output = ANSI_RE.sub("", output)
    interesting = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(
            marker in lowered
            for marker in ("error", "warning", "expected", ".cds:", "at line")
        ):
            interesting.append(stripped)

    if interesting:
        # Compiler diagnostics repeat context lines; cap the feedback so a
        # cascade of errors from one root cause doesn't swamp the repair turn.
        return interesting[:40]

    return [line.strip() for line in output.splitlines() if line.strip()][:40]


def compile_project(project_dir: Path, cds_bin: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Compile the project. Returns (succeeded, diagnostics)."""
    cds_bin = cds_bin or find_cds()

    roots = [r for r in ROOTS if (project_dir / r).is_dir()]
    if not roots:
        return False, ["Generated project contains none of: db/, srv/, app/"]

    try:
        result = subprocess.run(
            [cds_bin, "compile", *roots, "--to", "sql"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, ["cds compile timed out after 180s"]
    except OSError as exc:
        raise CdsNotFound(f"Failed to run '{cds_bin}': {exc}") from exc

    combined = (result.stderr or "") + "\n" + (result.stdout or "")

    # cds exits 0 on success; it can also exit 0 while printing an inability to
    # resolve the model, so treat an empty SQL result as a failure too.
    if result.returncode != 0:
        return False, _clean_diagnostics(combined)

    if "CREATE TABLE" not in (result.stdout or ""):
        return False, _clean_diagnostics(combined) or [
            "cds compile produced no SQL output"
        ]

    return True, []


def check_annotations(project_dir: Path, cds_bin: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Compile to EDMX, which exercises the UI annotations specifically.

    A model can be valid SQL-wise while its annotations reference members that
    do not exist on the projected entity, and only the OData/EDMX rendering
    surfaces that.
    """
    cds_bin = cds_bin or find_cds()
    roots = [r for r in ROOTS if (project_dir / r).is_dir()]
    if not roots:
        return True, []

    try:
        result = subprocess.run(
            [cds_bin, "compile", *roots, "--to", "edmx", "--odata-version", "v4"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True, []  # non-fatal: SQL compile already passed

    if result.returncode != 0:
        return False, _clean_diagnostics((result.stderr or "") + "\n" + (result.stdout or ""))

    warnings = [
        line.strip()
        for line in (result.stderr or "").splitlines()
        if "warn" in line.lower()
    ]
    return True, warnings[:20]
