"""Command line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .compile import compile_project, find_cds
from .ir import AppModel
from .pipeline import generate_project
from .providers import ProviderError, get_provider
from .render import render_project
from .validate import validate_model

app = typer.Typer(
    add_completion=False,
    help="Generate a runnable CAP + Fiori elements project from a functional spec.",
)
console = Console()


def _load_model(path: Path) -> AppModel:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]{path} is not valid JSON:[/red] {exc}")
        raise typer.Exit(1)

    try:
        return AppModel.model_validate(raw)
    except Exception as exc:
        console.print(f"[red]Model does not match the schema:[/red]\n{exc}")
        raise typer.Exit(1)


def _report_files(files, out_dir: Path) -> None:
    table = Table(title=f"{len(files)} files written to {out_dir}", show_header=False)
    for path in files:
        table.add_row(str(path))
    console.print(table)


@app.command()
def build(
    spec: Path = typer.Argument(..., help="Functional spec (markdown or plain text)"),
    out: Path = typer.Option(Path("./generated"), "--out", "-o", help="Output directory"),
    provider: Optional[str] = typer.Option(None, help="anthropic | openai | genai-hub"),
    model: Optional[str] = typer.Option(None, help="Override the model name"),
    name: Optional[str] = typer.Option(None, help="Project name for the generated app"),
    attempts: int = typer.Option(3, help="Maximum generate/repair attempts"),
    save_model: Optional[Path] = typer.Option(
        None, "--save-model", help="Also write the intermediate model as JSON"
    ),
):
    """Generate a CAP project from a functional specification."""
    load_dotenv()

    if not spec.exists():
        console.print(f"[red]Spec not found:[/red] {spec}")
        raise typer.Exit(1)

    try:
        llm = get_provider(provider, model)
    except ProviderError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"spec:     {spec}\n"
            f"provider: {llm.name} ({llm.model})\n"
            f"output:   {out}",
            title="fiori-genie",
            expand=False,
        )
    )

    result = generate_project(
        spec_text=spec.read_text(encoding="utf-8"),
        out_dir=out,
        provider=llm,
        project_name=name,
        max_attempts=attempts,
        on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
    )

    if not result.succeeded:
        console.print("\n[red]Generation failed.[/red] Last diagnostics:")
        for error in result.error_summary:
            console.print(f"  [red]-[/red] {error}")
        console.print(
            f"\n[dim]Tried {len(result.attempts)} time(s). "
            "Raising --attempts or tightening the spec often helps.[/dim]"
        )
        raise typer.Exit(1)

    console.print(f"\n[green]Success[/green] after {len(result.attempts)} attempt(s).")
    _report_files(result.files, out)

    if result.warnings:
        console.print("\n[yellow]Compiler warnings:[/yellow]")
        for warning in result.warnings:
            console.print(f"  [yellow]-[/yellow] {warning}")

    if save_model and result.model:
        save_model.parent.mkdir(parents=True, exist_ok=True)
        save_model.write_text(
            json.dumps(result.model.model_dump(by_alias=True, mode="json"), indent=2),
            encoding="utf-8",
        )
        console.print(f"\nIntermediate model saved to {save_model}")

    console.print(
        f"\nNext:\n  cd {out}\n  npm install\n  npm run watch"
    )


@app.command()
def render(
    model_file: Path = typer.Argument(..., help="An intermediate model JSON file"),
    out: Path = typer.Option(Path("./generated"), "--out", "-o"),
    compile_check: bool = typer.Option(True, "--compile/--no-compile"),
):
    """Render a project from an existing model, without calling an LLM."""
    model = _load_model(model_file)

    errors = validate_model(model)
    if errors:
        console.print("[red]Model failed validation:[/red]")
        for error in errors:
            console.print(f"  [red]-[/red] {error}")
        raise typer.Exit(1)

    files = render_project(model, out)
    _report_files(files, out)

    if compile_check:
        ok, diagnostics = compile_project(out)
        if ok:
            console.print("[green]cds compile passed.[/green]")
        else:
            console.print("[red]cds compile failed:[/red]")
            for line in diagnostics:
                console.print(f"  [red]-[/red] {line}")
            raise typer.Exit(1)


@app.command()
def validate(model_file: Path = typer.Argument(...)):
    """Validate a model JSON file without rendering anything."""
    model = _load_model(model_file)
    errors = validate_model(model)

    if errors:
        console.print(f"[red]{len(errors)} problem(s):[/red]")
        for error in errors:
            console.print(f"  [red]-[/red] {error}")
        raise typer.Exit(1)

    console.print(
        f"[green]Valid.[/green] {len(model.entities)} entities, "
        f"{len(model.services)} service(s), {len(model.apps)} app(s)."
    )


@app.command()
def schema(
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write to a file")
):
    """Print the JSON schema the LLM is constrained to."""
    text = json.dumps(AppModel.model_json_schema(by_alias=True), indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"Schema written to {out}")
    else:
        console.print(Syntax(text, "json", theme="ansi_dark"))


@app.command()
def doctor():
    """Check that the local toolchain is usable."""
    load_dotenv()
    ok = True

    try:
        cds = find_cds()
        console.print(f"[green]ok[/green]   cds executable: {cds}")
    except Exception as exc:
        console.print(f"[red]fail[/red] {exc}")
        ok = False

    try:
        llm = get_provider()
        console.print(f"[green]ok[/green]   provider: {llm.name} ({llm.model})")
    except ProviderError as exc:
        console.print(f"[yellow]warn[/yellow] {exc}")
        console.print("[dim]     `render` and `validate` still work without a provider.[/dim]")

    console.print(f"[green]ok[/green]   python: {sys.version.split()[0]}")

    if not ok:
        raise typer.Exit(1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False, "--reload"),
):
    """Run the web UI and API."""
    load_dotenv()
    import uvicorn

    console.print(f"fiori-genie UI on http://{host}:{port}")
    uvicorn.run("fiori_genie.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
