# Run fiori-genie on SAP Business Application Studio

Step-by-step guide to clone, generate, and preview CAP + Fiori apps in BAS.

## Prerequisites

- A BAS Dev Space (Full Stack Cloud Application or SAP Fiori is fine)
- Node.js 20+ (usually preinstalled)
- Python 3.9+ (`python3 --version`)
- Git access to this repo
- Optional: a [Google AI Studio](https://aistudio.google.com/apikey) key for Gemini (free tier)

---

## 1. Clone and open the project

In the BAS terminal:

```bash
cd ~
git clone https://github.com/chandeep2013/fiori-genie.git
cd fiori-genie
git checkout cursor/cap-spec-to-fiori-generator
git pull origin cursor/cap-spec-to-fiori-generator
```

Open the folder in BAS (`File → Open Workspace` → select `fiori-genie`).

---

## 2. Install toolchain

```bash
cd ~/fiori-genie   # or wherever you cloned it

npm install

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install google-genai          # only needed for Gemini
```

Check the toolchain:

```bash
fiori-genie doctor
```

---

## 3. Configure the LLM provider

Create `.env` in the project root:

```bash
cp .env.example .env
```

Edit `.env` (use Gemini for unpaid generation):

```bash
GEMINI_API_KEY=your-key-here
FIORI_GENIE_PROVIDER=gemini
FIORI_GENIE_MODEL=gemini-flash-lite-latest
```

For offline demo only (no API key; matches sample specs to fixtures):

```bash
FIORI_GENIE_PROVIDER=demo
```

Do not commit `.env`.

---

## 4. Start the fiori-genie web UI

```bash
source .venv/bin/activate
cd ~/fiori-genie
fiori-genie serve --host 0.0.0.0 --port 8000
```

In BAS:

1. Open the **Ports** view (or wait for the “port 8000 is available” popup).
2. Set port **8000** to **Public** / **Expose**.
3. Open the provided URL in a new browser tab.

You should see the fiori-genie UI5 app: paste a spec, generate, review the model, browse files, download a zip.

---

## 5. Generate apps

### From the UI

1. Paste a functional spec (or open one from `specs/`).
2. Click generate.
3. Note the **output path** shown after success (each run gets its own folder).

Examples of sample specs already in the repo:

| Spec | Typical output folder |
| --- | --- |
| `specs/purchase-requisition.md` | `generated/purchase-requisition` |
| `specs/travel-expense.md` | `generated/travel-expense` |

If a folder already exists, a timestamped sibling is created (nothing is overwritten).

### From the terminal (alternative)

```bash
source .venv/bin/activate
cd ~/fiori-genie

fiori-genie build specs/purchase-requisition.md
# → generated/purchase-requisition

fiori-genie build specs/travel-expense.md
# → generated/travel-expense
```

---

## 6. Run a generated CAP + Fiori app

Use a **second** BAS terminal (keep the UI on 8000 if you still need it).

```bash
cd ~/fiori-genie/generated/travel-expense   # or purchase-requisition, etc.
npm install
npx cds serve --port 4004
```

Important: CAP’s CLI uses `--port`, not `--host`. Binding is handled by BAS once the port is exposed.

In BAS:

1. Expose port **4004** (Public).
2. Open: `https://<your-bas-url-for-4004>/launchpad.html`

Do **not** open the app’s `index.html` alone if you need list → object navigation. Fiori elements needs the launchpad sandbox (`launchpad.html`).

---

## 7. Typical two-app workflow

Generate purchase requisition, then travel expense — each stays in its own folder:

```bash
# Terminal A — generator UI
fiori-genie serve --host 0.0.0.0 --port 8000
# expose 8000

# Terminal B — after each generate, serve the app you want
cd generated/purchase-requisition && npm install && npx cds serve --port 4004
# expose 4004 → /launchpad.html

# later, stop that server and switch:
cd ../travel-expense && npm install && npx cds serve --port 4004
```

Only one process can bind to 4004 at a time. Stop the previous `cds serve` before starting another.

---

## Ports cheat sheet

| Port | Process | What to open |
| --- | --- | --- |
| **8000** | `fiori-genie serve` | Generator UI (paste spec → generate) |
| **4004** | `npx cds serve --port 4004` | Generated app → `/launchpad.html` |

Both ports must be **exposed** in BAS or the browser cannot reach them.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Browser cannot open 8000 / 4004 | Expose the port in BAS Ports view; use the BAS-provided URL, not `localhost` from your laptop |
| `cds serve: unknown option --host` | Use `npx cds serve --port 4004` only |
| Basic-auth popup on the CAP app | Expected if profile/auth is wrong; generated apps use dummy auth under development — restart with `npx cds serve --port 4004` from the generated folder |
| List opens but object page does not | Open `/launchpad.html`, not `.../webapp/index.html` |
| Second generate overwrote the first | Pull latest branch; each run writes `generated/<project-name>` or a timestamped sibling |
| Gemini / API errors | Quota is per Google project, not per key. Try `FIORI_GENIE_MODEL=gemini-flash-lite-latest`, or `FIORI_GENIE_PROVIDER=demo` with sample specs |
| `fiori-genie: command not found` | `source .venv/bin/activate` then `pip install -e .` |

---

## Quick copy-paste (after clone)

```bash
cd ~/fiori-genie
git checkout cursor/cap-spec-to-fiori-generator && git pull

npm install
python3 -m venv .venv && source .venv/bin/activate
pip install -e . && pip install google-genai

cp .env.example .env
# edit .env → set GEMINI_API_KEY and FIORI_GENIE_PROVIDER=gemini

fiori-genie serve --host 0.0.0.0 --port 8000
# expose 8000 → open UI → generate

# new terminal:
cd generated/<project-name>
npm install && npx cds serve --port 4004
# expose 4004 → open /launchpad.html
```
