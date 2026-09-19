# Treelife AI — Technical Assessment

Two working systems in one FastAPI app, built for the Treelife AI technical assessment:

| | What it does | Open |
|---|---|---|
| **Task 1 — Semantic Business Data Translation Layer** | Connects to a CRM / project tool, *discovers how the client actually uses it* (hand-typed owner fields, "Dead Leads" folders, priority hidden in tags), then answers plain-English questions with reasoning — or explains honestly why the data can't answer. | `/task1` |
| **Task 2 — Enterprise Document Workspace** | Upload 50 files once; ask cross-file questions, run SQL over spreadsheets, cross-audit one document against the rest, edit Word/Excel files in place without corrupting them, generate new documents. Every turn costs a fraction of re-sending the files. | `/task2` |

Both tasks share one small LLM layer (any OpenAI-compatible API; Groq by default), local embeddings (no embedding API cost), and a strict per-call context budget.

* Architecture, diagrams, tech-stack justification and execution workflows: **[ARCHITECTURE.md](ARCHITECTURE.md)**
* Deep-dives: **[docs/task1.md](docs/task1.md)** · **[docs/task2.md](docs/task2.md)**

---

## Run it in 2 minutes

Requirements: Python 3.10+ (or Docker) and an LLM API key. The default is a free [Groq](https://console.groq.com) key; any OpenAI-compatible endpoint works.

```bash
git clone <this repo> && cd treelife-ai-assessment
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # put your LLM_API_KEY in .env
python samples/make_samples.py                       # builds the demo document corpus (samples/demo_corpus.zip)
uvicorn app:app --port 8000
```

Open <http://localhost:8000>.

Docker instead:

```bash
cp .env.example .env   # add LLM_API_KEY
docker compose up --build
```

The first document upload downloads a ~70 MB embedding model once (cached under `data/models`). Set `EMBEDDING_MODEL=none` to run lexical-only search with zero downloads.

### Try Task 1 (30 seconds)
1. Open `/task1`, keep **Demo CRM (messy, Pipedrive-shaped)** selected, click **Connect & discover**.
2. Read what it learned: owner lives in the custom `Assigned To` field (the official owner is a shared login), `lost` = the "Dead Leads" stage, priority = labels, and 22 spellings collapse into 4 people.
3. Ask *"How many open deals does Garima own?"* → **"Garima has 14 active deals"** with the reasoning. Then try *"How many deals in the London region?"* (unanswerable, explained), *"deals owned by Garmia"* (typo resolved), *"total value of open deals per owner"*.
4. Switch the source to **Demo project tool (Jira-shaped)** — same code, different habits: "completed" = Done *and* resolution Done, "abandoned" = Done + Won't Do.

### Try Task 2 (2 minutes)
1. Open `/task2`, click **New** to create a workspace, drop `samples/demo_corpus.zip` on the upload box (16 files: contracts, an invoice register with a hidden sheet and formulas, a policy PDF, board minutes).
2. Drop the same ZIP again — every file is detected as a duplicate; nothing is re-processed.
3. Use the example chips: cross-audit the Nimbus contract, ask a numeric question over the register (it writes SQL), edit the contract in place (a validated v2 appears, original kept), generate a memo or a spreadsheet.
4. Watch the cost meter on each reply: tokens actually used vs. what sending every file would cost.

---

## Point it at your own data

**Task 1** — choose the source in the UI or call the API:

| Source | Config | Notes |
|---|---|---|
| Pipedrive | `api_token` | Settings → Personal preferences → API |
| HubSpot | `access_token` (private app) | needs `crm.objects.{deals,contacts,companies}.read` |
| Jira Cloud | `base_url`, `email`, `api_token`, optional `jql` | uses `/rest/api/3/search/jql` |
| CSV / JSON / XLSX export | `path` on the server | any tool: export → point here |

```bash
curl -X POST localhost:8000/api/task1/connect -H 'content-type: application/json' \
  -d '{"source":"pipedrive","config":{"api_token":"..."}}'
curl -X POST localhost:8000/api/task1/ask -H 'content-type: application/json' \
  -d '{"connection_id":"<id from connect>","question":"How many open deals does Garima own?"}'
```

Nothing is hard-coded to a tool: a connector is ~80 lines that returns *collections of flat records + field metadata* ([task1/adapters/base.py](task1/adapters/base.py)); everything downstream is tool-agnostic. The built-in demo sources are served by this same app over HTTP (`/mock/crm`, `/mock/jira`) and consumed through the **same** Pipedrive/Jira adapters used for real accounts.

**Task 2** — upload anything: PDF, DOCX, XLSX/XLSM, CSV, TXT, MD, or a ZIP of them.

---

## Repository layout

```
app.py                  FastAPI entry point (mounts both tasks + the mock SaaS endpoints)
shared/                 llm.py (metered, budgeted, retrying client) · embeddings.py (fastembed) · config.py
task1/
  adapters/             base.py (contract) · pipedrive.py · hubspot.py · jira.py · files.py · registry.py
  mock_server/          deterministic messy CRM + Jira data, served Pipedrive/Jira-shaped
  discovery.py          statistical profiling (fill rates, CONSTANT fields, unused options, name-likeness…)
  semantic_map.py       LLM concept→field map with evidence + people alias clustering
  intent.py             question → concept-level query IR
  planner.py            IR → bindings on this client's fields/values (rules, fuzzy people, synonyms)
  rules.py              tiny boolean rule language (open = status∈{Open} AND stage∉{Dead Leads})
  executor.py           deterministic filtering/aggregation
  explain.py            reasoning steps, zero-result diagnosis, unanswerable handling
  engine.py / router.py / static/index.html
task2/
  workspace.py          upload-once store: SHA-256 dedupe, versions, manifest, compact chat memory
  parsers/              pdf.py (PyMuPDF) · docx.py (python-docx) · xlsx.py (openpyxl, hidden sheets, formulas) · text.py
  index.py              hybrid BM25 + embeddings, RRF fusion, scoped search, incremental
  ingest.py             parse once → index once → batched one-line summaries
  planner.py            strategy + file selection from the manifest only
  answer.py / tables.py / audit.py    focused QA · DuckDB SQL over sheets · cross-audit
  editor/               docx_edit.py · xlsx_edit.py · generate.py · validate.py (integrity + invariants)
  engine.py / router.py / static/index.html
samples/make_samples.py demo corpus with planted discrepancies
tests/                  pytest suite (no LLM or model download needed)
Dockerfile · docker-compose.yml · render.yaml
```

## Tests

```bash
pytest -q
```

The suite covers the deterministic core: discovery signals, alias clustering (typos, initials, nicknames), binding + execution (`open deals for Garima == 14`, `lost == Dead Leads`), zero-result diagnosis, unanswerable handling, parsers (hidden sheets, formulas, PDF pages), scoped hybrid search, DOCX/XLSX edits that preserve structure, refusal to overwrite formulas, chart pre-flight, corruption detection, dedupe and versioning. LLM prompts are exercised by the live demo.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_API_KEY` | — | required; Groq / OpenAI / any OpenAI-compatible key |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | change for OpenAI, Together, Ollama… |
| `LLM_MODEL_STRONG` / `LLM_MODEL_FAST` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` | reasoning vs cheap steps |
| `LLM_CONTEXT_BUDGET` | `4200` | hard cap on tokens of context per call (Groq free tier = 8k TPM) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | local; `none` = BM25 only |
| `DATA_DIR` | `./data` | workspaces, caches, model files |
| `PIPEDRIVE_API_TOKEN`, `HUBSPOT_ACCESS_TOKEN`, `JIRA_*` | — | optional defaults for real connectors |

## Deploy

* **Render**: click *New → Blueprint*, point at the repo; `render.yaml` provisions the service. Set `LLM_API_KEY` when prompted.
* **Anything that runs a Dockerfile** (Railway, Fly.io, Cloud Run): build the image, set `LLM_API_KEY`, expose `$PORT`.
* Persistence: workspaces live under `DATA_DIR`; mount a volume in production.

## Honest limitations

* **Excel workbooks with charts, pivots or embedded objects are not edited in place** — openpyxl cannot round-trip those parts, so the pre-flight check refuses and offers to generate a new workbook instead. That is a deliberate safety choice over silent corruption.
* After an in-place Excel edit, formula cells are recalculated by Excel on open (`fullCalcOnLoad`); the app's own parsed view shows them as formulas, not cached values.
* Task 1 currently loads up to 2,000 records per collection into memory and filters in Python. For very large CRMs the next step is pushing the bound filters down to the tool's query API — the plan format already makes that possible.
* The semantic map is cached per schema fingerprint; renaming a field invalidates the cache and the map is rebuilt automatically. Corrections can be applied through `POST /api/task1/connections/{id}/override` (human-in-the-loop) but there is no UI for it yet.
* Free-tier Groq limits are 8k tokens/minute per model; the app retries on 429 and keeps every call under budget, but a burst of long questions will queue.

Built by Aditya Chaudhary.
