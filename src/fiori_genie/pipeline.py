"""Spec -> IR -> project, with a repair loop driven by the CDS compiler.

The loop is the point of the tool. A single generation pass produces plausible
CDS most of the time; what makes the output trustworthy is that nothing is
returned to the caller until the compiler has accepted it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pydantic import ValidationError

from .compile import check_annotations, compile_project
from .ir import AppModel
from .normalize import normalize_model
from .prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt
from .providers import Provider, ProviderError
from .validate import validate_model

Progress = Callable[[str], None]


@dataclass
class Attempt:
    number: int
    stage: str  # "parse" | "validate" | "compile" | "ok"
    errors: List[str] = field(default_factory=list)
    raw_model: Optional[Dict] = None


@dataclass
class Result:
    succeeded: bool
    model: Optional[AppModel]
    files: List[Path]
    attempts: List[Attempt]
    output_dir: Optional[Path]
    warnings: List[str] = field(default_factory=list)

    @property
    def error_summary(self) -> List[str]:
        return self.attempts[-1].errors if self.attempts else []


def _format_validation_errors(exc: ValidationError) -> List[str]:
    """Render Pydantic errors as instructions rather than tracebacks."""
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        messages.append(f"{location}: {error['msg']}")
    return messages[:30]


def _noop(_: str) -> None:
    pass


def generate_project(
    spec_text: str,
    out_dir: Path,
    provider: Provider,
    project_name: Optional[str] = None,
    max_attempts: int = 3,
    on_progress: Optional[Progress] = None,
    skip_compile: bool = False,
) -> Result:
    """Generate a CAP project from a functional spec.

    Output is written to `out_dir` only after the compiler accepts it, so a
    failed run never leaves a half-broken project behind.
    """
    from .render import render_project  # imported late; pulls in Jinja

    progress = on_progress or _noop
    schema = AppModel.model_json_schema(by_alias=True)

    messages: List[Dict] = [
        {"role": "user", "content": build_user_prompt(spec_text, project_name)}
    ]
    attempts: List[Attempt] = []

    for number in range(1, max_attempts + 1):
        progress(f"Attempt {number}/{max_attempts}: asking the model for a design")

        try:
            raw = provider.generate(SYSTEM_PROMPT, messages, schema)
        except ProviderError as exc:
            attempts.append(Attempt(number, "parse", [str(exc)]))
            return Result(False, None, [], attempts, None)

        # 1. Structural validation.
        try:
            model = normalize_model(AppModel.model_validate(raw))
        except ValidationError as exc:
            errors = _format_validation_errors(exc)
            progress(f"  rejected by schema validation ({len(errors)} problems)")
            attempts.append(Attempt(number, "parse", errors, raw))
            messages += _repair_turn(raw, errors, "validate")
            continue

        # 2. Cross-model semantic validation.
        errors = validate_model(model)
        if errors:
            progress(f"  rejected by model validation ({len(errors)} problems)")
            attempts.append(Attempt(number, "validate", errors, raw))
            messages += _repair_turn(raw, errors, "validate")
            continue

        progress(f"  model is valid: {len(model.entities)} entities, "
                 f"{len(model.services)} service(s), {len(model.apps)} app(s)")

        # 3. Render and let the compiler have the final say.
        staging = Path(tempfile.mkdtemp(prefix="fiori-genie-"))
        try:
            files = render_project(model, staging)

            if skip_compile:
                _publish(staging, out_dir)
                attempts.append(Attempt(number, "ok", [], raw))
                return Result(True, model, files, attempts, out_dir)

            progress("  compiling with cds")
            ok, diagnostics = compile_project(staging)
            if not ok:
                progress(f"  compiler rejected it ({len(diagnostics)} diagnostics)")
                attempts.append(Attempt(number, "compile", diagnostics, raw))
                messages += _repair_turn(raw, diagnostics, "compile")
                continue

            edmx_ok, warnings = check_annotations(staging)
            if not edmx_ok:
                progress(f"  annotations rejected ({len(warnings)} diagnostics)")
                attempts.append(Attempt(number, "compile", warnings, raw))
                messages += _repair_turn(raw, warnings, "compile")
                continue

            progress("  compiled cleanly")
            _publish(staging, out_dir)
            attempts.append(Attempt(number, "ok", [], raw))
            return Result(True, model, files, attempts, out_dir, warnings)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    return Result(False, None, [], attempts, None)


def _repair_turn(raw: Dict, errors: List[str], stage: str) -> List[Dict]:
    return [
        {"role": "assistant", "content": json.dumps(raw, indent=2)},
        {"role": "user", "content": build_repair_prompt(errors, stage)},
    ]


def _publish(staging: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in staging.iterdir():
        target = out_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
