# Task 2 — Enterprise Document Workspace

## Roadblocks → mechanisms

| Roadblock | Mechanism (and where) |
|---|---|
| Repeated upload cost | `Workspace.add_bytes` hashes content (SHA-256); duplicates return the existing record instantly. ZIPs are expanded. Parsed units, DataFrames, vectors and summaries persist under `DATA_DIR`, so nothing is ever processed twice. |
| Information overload | The model never receives whole files. The **planner** sees a manifest (1–2 lines per file). Each strategy assembles a bounded context (`LLM_CONTEXT_BUDGET`, default 4.2k tokens with a conservative 3-chars/token estimate). Spreadsheets are queried with **SQL** rather than read. Hidden sheets are parsed and flagged; row blocks are indexed so clauses inside spreadsheets are searchable. |
| Re-read tax | `Workspace.remember` stores ≤12 compact turn summaries (question, strategy, files, 300 chars). Follow-ups resolve references ("that document", "the same file") from memory and hit the index, not the files. |
| File corruption | The model emits **operations**; `editor/docx_edit.py` and `editor/xlsx_edit.py` apply them with python-docx/openpyxl on a copy; `editor/validate.py` re-opens the result and compares invariants with the original; failures are discarded; successes become a new version. New documents come from a content spec built by code (`editor/generate.py`) and go through the same validation. |

## Strategies

| Strategy | When | What enters the prompt |
|---|---|---|
| `qa` | factual question over one or a few docs | top passages from hybrid search, scoped to the chosen files, packed to budget, cited `[S#]` |
| `table_query` | numeric / filter / aggregation on spreadsheets | sheet schemas + 3 sample rows → SQL → DuckDB result (≤60 rows, capped) + 3 passages for context |
| `cross_audit` | "check A against the rest" | A's units (bounded) → ≤12 claims → per-claim evidence from support files only (entity-anchored queries, ≤2 passages per file, ≤5 per claim) → batched comparison |
| `edit` | change an existing DOCX/XLSX | target's units (`id | text`) or sheet schema + relevant row blocks, plus ≤4 supporting passages if other documents are referenced |
| `generate` | produce a new DOCX/XLSX | relevant passages + prior findings from memory → content spec |
| `summarize` | summarise documents | the target's chunks (bounded) |

## Measured on the demo corpus (16 files, ≈28k tokens if sent whole)

| Turn | Tokens used | vs. naive | Notes |
|---|---|---|---|
| "What are the payment terms in the Nimbus contract?" | ≈2.7k | 58–90% saved | 2 calls; cites paragraph and section |
| "Total invoiced per vendor; which invoices are open?" | ≈4k | ≈85% saved | SQL over 150+ rows; the model saw a schema and 3 sample rows |
| "Cross-audit the Nimbus contract against all documents" | ≈15k | ≈65% saved | 5 calls; finds all three planted issues: Net 45 vs net-30 (register), 99.5% vs the policy's 99.9% minimum, 60- vs 90-day notice (minutes + policy) |
| "Change payment terms to 45 days and notice to 90 days" | ≈3.3k | ≈88% saved | 2 ops, validated, v2 created, original kept |
| "Mark Nimbus invoices Net 30 and add an Audit Notes sheet" | ≈7.7k | ≈75% saved | 3 rows updated, sheet added, 189 formulas intact, hidden sheet still hidden |
| "Create an Excel sheet of all contracts with fee/SLA/notice" | ≈5.3k | ≈85% saved | generated workbook validated and indexed |

Wall-clock on the free Groq tier is 5–40 s per turn because calls wait for the 8k-tokens/minute window; on a paid tier the same turns take a few seconds.

The naive baseline grows linearly with the workspace; the per-turn cost does not — a 500-file workspace costs the same per question as a 16-file one because only the manifest (and the chosen passages) enter the prompt.

## Accuracy safeguards
* Citations are mandatory and the UI shows which sources were actually cited.
* The answer prompt requires "say what is missing" instead of guessing; cross-audit marks claims `not_found` when only other parties' documents match.
* Numbers over spreadsheets come from DuckDB, not from the model reading rows.
* Cross-audit evidence is diversified per file and anchored on the target's party name so near-identical templates cannot crowd out the register/minutes/policy.
* Hidden sheets are indexed and labelled `(HIDDEN)` in the schema the model sees.

## File safety, concretely
* **Never overwritten**: edits produce `<name> v2.docx` linked to the parent; the original stays downloadable.
* **Validation before download**: zip integrity (`testzip`), reopen with the real library, and invariants — DOCX: `document.xml`/`styles.xml` present, tables/images/headers/footers not lost, paragraph delta as expected; XLSX: sheet names, formula count, VBA part (`.xlsm`), merged ranges.
* **Formulas are protected**: value ops refuse to touch a formula cell; `set_formula` is explicit; `fullCalcOnLoad` makes Excel recompute.
* **Pre-flight refusal**: workbooks with charts/drawings/pivots/embedded objects are not edited in place (openpyxl would drop them); the assistant offers to generate a new workbook instead.

## Optional REST API (`uvicorn api:app`)

| Endpoint | Purpose |
|---|---|
| `POST /api/task2/workspaces {name}` / `GET /api/task2/workspaces` | create / list |
| `GET /api/task2/workspaces/{id}` | files (with summaries, versions, token estimates), index stats, chat memory |
| `POST /api/task2/workspaces/{id}/upload` (multipart `files[]`) | upload files or ZIPs; returns added / duplicates / errors |
| `POST /api/task2/workspaces/{id}/chat {message}` | run one turn; returns strategy, answer, sources, SQL, findings, ops, validation, artifacts, usage, naive cost |
| `GET /api/task2/workspaces/{id}/files/{fid}/download` | download any version |
| `GET /api/task2/workspaces/{id}/files/{fid}` | parsed outline, tables, units |

## Tech stack justification
See [ARCHITECTURE.md](../ARCHITECTURE.md#tech-stack--why). In short: PyMuPDF + python-docx + openpyxl for faithful parsing and editing; rank-bm25 + fastembed (local) for hybrid retrieval without an embedding bill; pandas + DuckDB so the database, not the model, does table maths; FastAPI for a single deployable process.

## Limitations
* openpyxl cannot round-trip charts/pivots/images — hence the pre-flight refusal rather than a corrupted file.
* Cached formula values are not available after an openpyxl save until Excel recalculates; the parsed view of a v2 workbook shows formulas as formulas.
* Cross-audit extracts at most 12 claims per run; very long targets are narrowed by search before extraction.
* Conversation memory is per workspace, not per user.
