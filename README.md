# Treelife AI — Technical Assessment

Two working systems in one Streamlit app, built for the Treelife AI technical assessment:

| | What it does |
|---|---|
| **Task 1 — Semantic Business Data Translation Layer** | Connects to a CRM / project tool, *discovers how the client actually uses it* (hand-typed owner fields, "Dead Leads" folders, priority hidden in tags), then answers plain-English questions with reasoning — or explains honestly why the data can't answer. |
| **Task 2 — Enterprise Document Workspace** | Upload 50 files once; ask cross-file questions, run SQL over spreadsheets, cross-audit one document against the rest, edit Word/Excel files in place without corrupting them, generate new documents. Every turn costs a fraction of re-sending the files. |

Both tasks share one small LLM layer (any OpenAI-compatible API; Groq by default), local embeddings (no embedding API cost), and a strict per-call context budget.

* Architecture, diagrams, tech-stack justification and execution workflows: **[ARCHITECTURE.md](ARCHITECTURE.md)**
* Deep-dives: **[docs/task1.md](docs/task1.md)** · **[docs/task2.md](docs/task2.md)**

---

## Run it in 2 minutes

Requirements: Python 3.10–3.12 and an LLM API key (a free [Groq](https://console.groq.com) key works; any OpenAI-compatible endpoint does).

```bash
git clone https://github.com/Aditya-Chaudhary10/treelife-test.git && cd treelife-test
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # put your LLM_API_KEY in .env
streamlit run streamlit_app.py
```

Docker instead: `cp .env.example .env` (add the key) then `docker compose up --build` → <http://localhost:8501>.

The first document upload downloads a ~70 MB embedding model once (cached under `data/models`). Set `EMBEDDING_MODEL=none` to run lexical-only search with zero downloads.

### Deploy on Streamlit Community Cloud (free)
1. Push the repo, open <https://share.streamlit.io>, **New app** → repo, branch `main`, main file `streamlit_app.py`.
2. *Advanced settings* → Python 3.11 or 3.12 → **Secrets**: `LLM_API_KEY = "your-key"` (optionally `EMBEDDING_MODEL = "none"` for the smallest footprint).
3. Deploy. The demo corpus ships in the repo (`samples/demo_corpus.zip`) and loads with one click in Task 2.

Render / any Docker host also work (`render.yaml` and the `Dockerfile` run Streamlit on `$PORT`).

### Try Task 1 (30 seconds)
1. Open **Task 1**, keep **Demo CRM (messy, Pipedrive-shaped)** selected, click **Connect & discover**.
2. Read what it learned: owner lives in the custom `Assigned To` field (the official owner is a shared login), `lost` = the "Dead Leads" stage, priority = labels, and 22 spellings collapse into 4 people.
3. Ask *"How many open deals does Garima own?"* → **"Garima owns 14 open deals"** with the reasoning. Then try *"How many deals in the London region?"* (unanswerable, explained), *"deals owned by Garmia"* (typo resolved), *"total value of open deals per owner"*.
4. Switch the source to **Demo project tool (Jira-shaped)** — same code, different habits: "completed" = Done *and* resolution Done, "abandoned" = Done + Won't Do.

### Try Task 2 (2 minutes)
1. Open **Task 2**, create a workspace, click **Load demo corpus** (16 files: contracts, an invoice register with a hidden sheet and formulas, a policy PDF, board minutes) — or drop your own files / a ZIP.
2. Load it again — every file is detected as a duplicate; nothing is re-processed.
3. Use the example prompts: cross-audit the Nimbus contract, ask a numeric question over the register (it writes SQL), edit the contract in place (a validated v2 appears, original kept), generate a memo or a spreadsheet.
4. Watch the cost meter on each reply: tokens actually used vs. what sending every file would cost.

---

## Point it at your own data

**Task 1** — choose the source in the sidebar:

| Source | Config | Notes |
|---|---|---|
| Pipedrive | `api_token` | Settings → Personal preferences → API |
| HubSpot | `access_token` (private app) | needs `crm.objects.{deals,contacts,companies}.read` |
| Jira Cloud | `base_url`, `email`, `api_token`, optional `jql` | uses `/rest/api/3/search/jql` |
| CSV / JSON / XLSX export | `path` on the server | any tool: export → point here |

Nothing is hard-coded to a tool: a connector is ~80 lines that returns *collections of flat records + field metadata* ([task1/adapters/base.py](task1/adapters/base.py)); everything downstream is tool-agnostic. The demo sources are the **same** Pipedrive/Jira adapters talking HTTP to an in-process transport that serves Pipedrive/Jira-shaped JSON.

**Task 2** — upload anything: PDF, DOCX, XLSX/XLSM, CSV, TXT, MD, or a ZIP of them.

**REST access (optional)** — the same engines are exposed as an API for scripting: `uvicorn api:app --port 8000` → `/docs`.

---

## Repository layout

```
streamlit_app.py        entry point (st.navigation) · views/home.py · views/task1.py · views/task2.py
api.py                  optional REST API (FastAPI) over the same engines, plus the demo endpoints over HTTP
shared/                 llm.py (metered, budgeted, retrying client) · embeddings.py (fastembed) · config.py
task1/
  adapters/             base.py (contract) · pipedrive.py · hubspot.py · jira.py · files.py · registry.py
  mock_server/          deterministic messy CRM + Jira data; service.py · transport.py (in-process) · routes.py (HTTP)
  discovery.py          statistical profiling (fill rates, CONSTANT fields, unused options, name-likeness…)
  semantic_map.py       LLM concept→field map with evidence + people alias clustering
  intent.py             question → concept-level query IR
  planner.py            IR → bindings on this client's fields/values (rules, fuzzy people, synonyms)
  rules.py              tiny boolean rule language (open = status∈{Open} AND stage∉{Dead Leads})
  executor.py           deterministic filtering/aggregation
  explain.py            reasoning steps, zero-result diagnosis, unanswerable handling
  engine.py / router.py
task2/
  workspace.py          upload-once store: SHA-256 dedupe, versions, manifest, compact chat memory
  parsers/              pdf.py (PyMuPDF) · docx.py (python-docx) · xlsx.py (openpyxl, hidden sheets, formulas) · text.py
  index.py              hybrid BM25 + embeddings, RRF fusion, scoped search, incremental
  ingest.py             parse once → index once → batched one-line summaries
  planner.py            strategy + file selection from the manifest only
  answer.py / tables.py / audit.py    focused QA · DuckDB SQL over sheets · cross-audit
  editor/               docx_edit.py · xlsx_edit.py · generate.py · validate.py (integrity + invariants)
  engine.py / router.py
samples/make_samples.py demo corpus with planted discrepancies (samples/demo_corpus.zip)
tests/                  pytest suite (no LLM or model download needed)
Dockerfile · docker-compose.yml · render.yaml · .streamlit/config.toml
```

## Tests

```bash
pytest -q
```

The suite covers the deterministic core: discovery signals, alias clustering (typos, initials, nicknames), binding + execution (`open deals for Garima == 14`, `lost == Dead Leads`), zero-result diagnosis, unanswerable handling, the in-process demo transport, parsers (hidden sheets, formulas, PDF pages), scoped hybrid search, DOCX/XLSX edits that preserve structure, refusal to overwrite formulas, chart pre-flight, corruption detection, dedupe and versioning. LLM prompts are exercised by the live demo.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_API_KEY` | — | required; Groq / OpenAI / any OpenAI-compatible key (Streamlit Cloud: put it in Secrets) |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | change for OpenAI, Together, Ollama… |
| `LLM_MODEL_STRONG` / `LLM_MODEL_FAST` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` | reasoning vs cheap steps |
| `LLM_CONTEXT_BUDGET` | `4200` | hard cap on tokens of context per call (Groq free tier = 8k TPM) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | local; `none` = BM25 only |
| `DATA_DIR` | `./data` | workspaces, caches, model files |
| `PIPEDRIVE_API_TOKEN`, `HUBSPOT_ACCESS_TOKEN`, `JIRA_*` | — | optional defaults for real connectors |

## Honest limitations

* **Excel workbooks with charts, pivots or embedded objects are not edited in place** — openpyxl cannot round-trip those parts, so the pre-flight check refuses and offers to generate a new workbook instead. That is a deliberate safety choice over silent corruption.
* After an in-place Excel edit, formula cells are recalculated by Excel on open (`fullCalcOnLoad`); the app's own parsed view shows them as formulas, not cached values.
* Task 1 currently loads up to 2,000 records per collection into memory and filters in Python. For very large CRMs the next step is pushing the bound filters down to the tool's query API — the plan format already makes that possible.
* The semantic map is cached per schema fingerprint; renaming a field invalidates the cache and the map is rebuilt automatically. Corrections can be applied through the API (`POST /api/task1/connections/{id}/override`) but there is no UI for it yet.
* Free-tier Groq limits are 8k tokens/minute per model; the app retries on 429/413 and keeps every call under budget, but long turns can take 10–40 s while waiting for the window.
* Streamlit Community Cloud storage is ephemeral: workspaces disappear when the app restarts (fine for a demo; mount a volume with Docker for persistence).

Built by Aditya Chaudhary.
