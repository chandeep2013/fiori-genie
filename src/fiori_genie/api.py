"""FastAPI backend for the fiori-genie web UI."""

from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .ir import AppModel
from .paths import GENERATED_ROOT, allocate_output_dir
from .pipeline import generate_project
from .providers import ProviderError, get_provider
from .render import render_project
from .validate import validate_model

load_dotenv()

WEB_DIR = Path(__file__).parent / "web"
WORKSPACE = Path("./workspace").resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)


def _resolve_run_dir(run_id: str) -> Path:
    """Locate a finished generation by run id (pointer file or workspace dir)."""
    pointer = WORKSPACE / f"{run_id}.path"
    if pointer.is_file():
        candidate = Path(pointer.read_text(encoding="utf-8").strip())
        if candidate.is_dir():
            return candidate
    legacy = WORKSPACE / run_id
    if legacy.is_dir():
        return legacy
    raise HTTPException(status_code=404, detail="Unknown run id")

# Binary-ish or bulky files are listed but not shipped to the browser.
PREVIEWABLE_SUFFIXES = {
    ".cds", ".json", ".js", ".ts", ".xml", ".html", ".yaml", ".yml",
    ".csv", ".properties", ".md", ".gitignore",
}

app = FastAPI(title="fiori-genie", version="0.1.0")


class GenerateRequest(BaseModel):
    spec: str
    project_name: Optional[str] = Field(default=None, alias="projectName")
    provider: Optional[str] = None
    model: Optional[str] = None
    attempts: int = 3

    model_config = {"populate_by_name": True, "protected_namespaces": ()}


class RenderRequest(BaseModel):
    model: Dict

    model_config = {"protected_namespaces": ()}


def _file_payload(root: Path) -> List[Dict]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "node_modules" in path.parts:
            continue
        relative = path.relative_to(root)
        suffix = path.suffix or path.name
        content = None
        if suffix in PREVIEWABLE_SUFFIXES and path.stat().st_size < 400_000:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = None
        files.append(
            {
                "path": str(relative),
                "size": path.stat().st_size,
                "content": content,
            }
        )
    return files


@app.get("/api/status")
def status() -> Dict:
    try:
        provider = get_provider()
        detail = None
        if provider.name == "demo":
            detail = (
                "Using offline demo provider: it matches your spec to a built-in "
                "sample (leave, travel, sales, maintenance, invoice, purchase). "
                "It does not call an LLM. Add ANTHROPIC_API_KEY or OPENAI_API_KEY "
                "for real generation from arbitrary specs."
            )
        return {
            "providerReady": True,
            "provider": provider.name,
            "model": provider.model,
            "detail": detail,
        }
    except ProviderError as exc:
        return {"providerReady": False, "provider": None, "model": None, "detail": str(exc)}


@app.get("/api/schema")
def schema() -> Dict:
    return AppModel.model_json_schema(by_alias=True)


@app.get("/api/sample-spec")
def sample_spec() -> Dict:
    candidate = Path("specs/purchase-requisition.md")
    if candidate.exists():
        return {"spec": candidate.read_text(encoding="utf-8")}
    return {"spec": ""}


@app.post("/api/generate")
def generate(request: GenerateRequest) -> Dict:
    if not request.spec.strip():
        raise HTTPException(status_code=400, detail="Specification is empty")

    try:
        provider = get_provider(request.provider, request.model)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    run_id = uuid.uuid4().hex[:12]
    staging = WORKSPACE / run_id
    log: List[str] = []

    result = generate_project(
        spec_text=request.spec,
        out_dir=staging,
        provider=provider,
        project_name=request.project_name,
        max_attempts=request.attempts,
        on_progress=log.append,
    )

    attempts = [
        {"number": a.number, "stage": a.stage, "errors": a.errors}
        for a in result.attempts
    ]

    if not result.succeeded:
        shutil.rmtree(staging, ignore_errors=True)
        return {
            "ok": False,
            "runId": None,
            "outputPath": None,
            "log": log,
            "attempts": attempts,
            "errors": result.error_summary,
        }

    # Promote into generated/<project-name> without overwriting prior apps.
    project = (
        (result.model.project_name if result.model else None)
        or request.project_name
        or "app"
    )
    final = allocate_output_dir(project)
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(final))
    (WORKSPACE / f"{run_id}.path").write_text(str(final.resolve()), encoding="utf-8")
    log.append(f"Wrote project to {final} (previous apps were left untouched)")

    return {
        "ok": True,
        "runId": run_id,
        "outputPath": str(final),
        "log": log,
        "attempts": attempts,
        "warnings": result.warnings,
        "model": result.model.model_dump(by_alias=True, mode="json") if result.model else None,
        "files": _file_payload(final),
    }


@app.post("/api/render")
def render(request: RenderRequest) -> Dict:
    """Re-render from an edited model. Lets the UI act as a review-and-fix step."""
    try:
        model = AppModel.model_validate(request.model)
    except ValidationError as exc:
        return {
            "ok": False,
            "errors": [
                f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
                for e in exc.errors()
            ],
        }

    errors = validate_model(model)
    if errors:
        return {"ok": False, "errors": errors}

    run_id = uuid.uuid4().hex[:12]
    final = allocate_output_dir(model.project_name)
    render_project(model, final)
    (WORKSPACE / f"{run_id}.path").write_text(str(final.resolve()), encoding="utf-8")

    return {
        "ok": True,
        "runId": run_id,
        "outputPath": str(final),
        "files": _file_payload(final),
    }


@app.get("/api/download/{run_id}")
def download(run_id: str):
    if not run_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid run id")

    out_dir = _resolve_run_dir(run_id)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out_dir.rglob("*")):
            if path.is_file() and "node_modules" not in path.parts:
                archive.write(path, path.relative_to(out_dir))
    buffer.seek(0)

    zip_name = out_dir.name or run_id
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
