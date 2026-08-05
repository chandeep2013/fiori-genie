"""Turns a validated `AppModel` into a complete, runnable CAP project on disk."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..ir import AppModel, Cardinality, Entity
from . import cds as cds_helpers
from . import tests as test_gen
from . import ui5
from .annotations import render_annotations

TEMPLATE_DIR = Path(__file__).parent / "templates"

# Pinned to the versions this generator was verified against.
CDS_VERSION = "^10"
SQLITE_VERSION = "^3"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    cds_helpers.register(env)
    return env


def _csv_columns(entity: Entity, rows: List[Dict]) -> List[str]:
    """Canonical column order, restricted to columns actually present."""
    candidates: List[str] = []
    if entity.use_cuid:
        candidates.append("ID")
    candidates += [f.name for f in entity.fields]
    candidates += [
        r.name + "_ID" for r in entity.relations if r.cardinality is Cardinality.TO_ONE
    ]
    if entity.use_managed:
        candidates += ["createdAt", "createdBy", "modifiedAt", "modifiedBy"]

    present = {key for row in rows for key in row}
    ordered = [c for c in candidates if c in present]
    # Anything the validator allowed but this list missed, appended stably.
    ordered += sorted(present - set(ordered))
    return ordered


def _render_csv(entity: Entity, rows: List[Dict]) -> str:
    columns = _csv_columns(entity, rows)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=columns, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buffer.getvalue()


def _package_json(model: AppModel) -> str:
    package = {
        "name": model.project_name,
        "version": "1.0.0",
        "description": model.description or f"Generated CAP service: {model.project_name}",
        "private": True,
        "engines": {"node": ">=20"},
        "dependencies": {
            "@sap/cds": CDS_VERSION,
            "express": "^4",
        },
        "devDependencies": {
            "@cap-js/sqlite": SQLITE_VERSION,
            "@sap/cds-dk": CDS_VERSION,
            # cds.test moved out of @sap/cds in v10 and pulls chai 6 as a peer.
            "@cap-js/cds-test": "^1",
            "chai": "^6",
            "chai-as-promised": "^8",
            "mocha": "^10",
            "@wdio/cli": "^8",
            "@wdio/local-runner": "^8",
            "@wdio/mocha-framework": "^8",
            "@wdio/spec-reporter": "^8",
            "wdio-ui5-service": "^2",
        },
        "scripts": {
            "start": "cds-serve",
            "watch": "cds watch",
            "build": "cds build --production",
            "test": "mocha test/*.test.js --timeout 60000",
            "test:e2e": "wdio run wdio.conf.js",
        },
        "cds": {
            "requires": {
                "db": {"kind": "sqlite", "credentials": {"url": ":memory:"}},
                # Services declaring `requires` would otherwise make the local
                # server answer 401 and the browser pop a basic-auth dialog.
                # Dummy auth applies only to the development profile; the
                # production profile keeps real authentication.
                "[development]": {"auth": {"kind": "dummy"}},
            }
        },
    }
    return json.dumps(package, indent=2) + "\n"


def _readme(model: AppModel) -> str:
    apps = "\n".join(
        f"- **{app.title}** — standalone at "
        f"<http://localhost:4004/{app.id}/webapp/index.html>"
        for app in model.apps
    )
    services = "\n".join(
        f"- `{s.name}` at `/odata/v4/{cds_helpers.service_path(s)}/`"
        for s in model.services
    )
    entities = "\n".join(
        f"- `{e.name}`" + (f" — {e.doc}" if e.doc else "") for e in model.entities
    )

    return f"""# {model.project_name}

{model.description or "Generated from a functional spec by fiori-genie."}

> Generated code. Review before committing to a real project — the model
> definitions and annotations are a starting point, not a finished design.

## Run it

```bash
npm install
npm run watch
```

Then open the launchpad at <http://localhost:4004/launchpad.html>.

### Apps

Run the apps from the launchpad. Fiori elements relies on launchpad (ushell)
services for navigation from a list report to an object page, so opening an
app's `index.html` directly will render the list but will not navigate into a
record.

{apps or "_No Fiori apps were generated._"}

### Services

{services}

### Entities

{entities}

## Tests

```bash
npm test          # cds.test service tests, no browser needed
npm run test:e2e  # wdi5 browser tests, requires `npm run watch` in another shell
```

OPA5 journeys live under each app at `webapp/test/integration/` and run in the
browser via `webapp/test/testsuite.qunit.html`.
"""


def _gitignore() -> str:
    return """node_modules/
gen/
*.db
*.sqlite
.env
dist/
test/e2e/__screenshots__/
"""


def render_project(model: AppModel, out_dir: Path) -> List[Path]:
    """Write the full project. Returns every path written, relative to out_dir."""
    env = _env()
    files: Dict[str, str] = {}

    files["package.json"] = _package_json(model)
    files[".gitignore"] = _gitignore()
    files["README.md"] = _readme(model)

    files["db/schema.cds"] = env.get_template("schema.cds.j2").render(model=model)
    files["srv/service.cds"] = env.get_template("service.cds.j2").render(model=model)

    for entity_name, rows in model.sample_data.items():
        entity = model.entity(entity_name)
        if entity is None or not rows:
            continue
        filename = f"{model.namespace}-{entity_name}.csv"
        files[f"db/data/{filename}"] = _render_csv(entity, rows)

    for app in model.apps:
        base = f"app/{app.id}"
        files[f"{base}/annotations.cds"] = render_annotations(model, app)
        files[f"{base}/ui5.yaml"] = ui5.ui5_yaml(app)
        files[f"{base}/webapp/manifest.json"] = ui5.manifest_json(model, app)
        files[f"{base}/webapp/Component.js"] = ui5.component_js(app)
        files[f"{base}/webapp/index.html"] = ui5.index_html(app)
        files[f"{base}/webapp/i18n/i18n.properties"] = ui5.i18n_properties(app)

        for rel_path, content in test_gen.opa_files(app).items():
            files[f"{base}/webapp/{rel_path}"] = content

        files[f"test/e2e/{app.id}.test.js"] = test_gen.wdi5_test(model, app)

    if model.apps:
        files["app/launchpad.html"] = ui5.launchpad_html(model)
        files["app/appconfig/fioriSandboxConfig.json"] = ui5.sandbox_config(model)

    files["test/service.test.js"] = test_gen.service_test(model)
    if model.apps:
        files["wdio.conf.js"] = test_gen.wdio_conf(model)

    written: List[Path] = []
    for rel_path, content in files.items():
        target = out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(Path(rel_path))

    return sorted(written)
