# fiori-genie

Turns a functional specification into a runnable SAP CAP project: CDS schema,
OData service, Fiori elements annotations, a working UI5 app, sample data and
tests.

A proof of concept, built to answer one question: can an LLM produce SAP
application code that is trustworthy enough to start from?

## The idea

The model never writes CDS.

It emits a structured **application model** — entities, typed fields,
associations and compositions, service exposure, UI annotations — which is
validated and then rendered into CDS by deterministic templates. Three
consequences follow:

1. **Syntax errors are impossible.** The templates own the grammar.
2. **Semantics are checked before anything is written.** Do association targets
   exist? Does every to-many have a valid backlink? Does the list report
   reference fields that are actually on the entity?
3. **The CDS compiler is the final gate.** Nothing reaches the output directory
   until `cds compile` accepts it. When it doesn't, the diagnostics are fed back
   and the model tries again.

That last point is what separates this from a prompt that emits CDS. There is a
ground-truth oracle in the loop, so the output is verified rather than
plausible.

```
spec ──▶ LLM ──▶ application model ──▶ validation ──▶ render ──▶ cds compile ──▶ output
                       ▲                    │                         │
                       └──────── diagnostics ◀────────────────────────┘
```

## Setup

Requires Node 20+ and Python 3.9+.

```bash
npm install                       # installs @sap/cds-dk locally
python3 -m venv .venv
./.venv/bin/pip install -e .

cp .env.example .env              # then add one API key
./.venv/bin/fiori-genie doctor    # checks the toolchain
```

## Use

```bash
# Generate from a spec
fiori-genie build specs/purchase-requisition.md -o ./generated

# Run the result
cd generated && npm install && npm run watch
# then open http://localhost:4004/launchpad.html
```

The web UI does the same thing with a spec editor, a view of the model that was
inferred, a file browser and a zip download:

```bash
fiori-genie serve      # http://127.0.0.1:8000
```

### Other commands

| Command | Purpose |
| --- | --- |
| `build` | Spec to project, with the repair loop |
| `render` | Render from a saved model, no LLM involved |
| `validate` | Check a model without rendering |
| `schema` | Print the JSON schema the LLM is constrained to |
| `doctor` | Verify the local toolchain |

`render` is the fast path when iterating on templates: save a model once with
`build --save-model model.json`, then re-render from it for free.

## What it generates

```
db/schema.cds                     entities, aspects, associations, compositions
db/data/*.csv                     sample data, foreign keys resolved
srv/service.cds                   service with draft and readonly exposure
app/launchpad.html                Fiori launchpad sandbox
app/appconfig/                    launchpad tile and target resolution
app/<id>/annotations.cds          UI annotations for list report and object page
app/<id>/webapp/                  UI5 app: manifest, component, i18n
app/<id>/webapp/test/integration  OPA5 journeys with Fiori elements page objects
test/service.test.js              cds.test suite, runs headless in CI
test/e2e/<id>.test.js             wdi5 browser test
wdio.conf.js                      wdi5 configuration
```

## Choosing a provider

Set one credential in `.env`; the provider is inferred (or set
`FIORI_GENIE_PROVIDER` explicitly).

- **Google AI Studio / Gemini** — best unpaid path. Create a key at
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then
  `pip install google-genai` and set `GEMINI_API_KEY` + `FIORI_GENIE_PROVIDER=gemini`.
  Default model: `gemini-2.5-flash`.
- **demo** — offline; matches sample specs to built-in fixtures (no LLM).
- **Anthropic or OpenAI** — paid / credit-based; forced tool calls for structured IR.
- **SAP Generative AI Hub** — BTP-native; implemented but not verified on a live tenant.

## Things worth knowing

**The launchpad is not optional.** Fiori elements uses ushell services for inner
app state and cross-app navigation. Opening an app's `index.html` directly
renders the list report but will not navigate to the object page. Generated apps
are meant to be run from `launchpad.html`.

**Service paths must not start with a slash.** In CDS, `@(path: '/procurement')`
is absolute and drops the `/odata/v4` prefix, silently breaking every generated
URL. There is a test pinning this.

**Composition children are not draft-enabled.** CAP draft-enables them through
the root; annotating the child too is a compile error. The validator rejects it
with a message that tells the model how to fix it.

**Development auth is dummy auth.** A service declaring `requires` would make
the local server answer 401 and the browser pop a basic-auth dialog. The
generated `package.json` scopes dummy auth to the development profile only.

## Testing

```bash
./.venv/bin/python -m pytest tests/ -q
```

Covers the deterministic path end to end, including that the compile oracle
actually rejects broken CDS — a check that would otherwise pass vacuously.

## Limitations

- Generation is a single request; the UI shows progress only once it finishes.
- The wdi5 tests are a starting point. The `cds.test` suite is the layer that
  earns its keep.
- Only managed associations are produced. No unmanaged `on` conditions, no
  code-list entities, no actions or functions.
- There is no evaluation set. Before trusting this on real specs, assemble
  30–50 with expected models; otherwise there is no way to tell whether a prompt
  change helped.
