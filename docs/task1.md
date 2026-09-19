# Task 1 — Semantic Business Data Translation Layer

## What the brief asks for, and where each requirement lives

| Requirement | Implementation |
|---|---|
| Automatically figure out how the client structured and uses their data | `task1/discovery.py` (statistics) + `task1/semantic_map.py` (LLM interpretation with evidence, cached per schema fingerprint) |
| Understand intent in everyday language | `task1/intent.py` — question → concept-level IR; concepts, never field names |
| Pull the correct answer for *this* client | `task1/planner.py` binds concepts to fields/values/rules; `task1/executor.py` runs deterministic Python |
| Explain its reasoning | `task1/explain.py` — steps are derived from bindings + counts; the LLM only phrases the answer and its number is verified |
| Explain *why* it found nothing | `explain.zero_diagnosis` (which filter kills the result, what the data holds instead) and `unanswerable` (concept not tracked, with the closest field) |
| Not hard-coded to one tool | `task1/adapters/base.py` contract; Pipedrive, HubSpot, Jira, CSV/JSON/XLSX adapters; two demo sources with opposite habits |
| Quick, dynamic setup; no field maps that break on rename | connect = fetch schema + records → profile → map; a renamed field changes the fingerprint and the map is rebuilt |

## The pipeline

### 1. Discovery (no LLM)
For every field of every collection: fill rate, distinct values before/after case-normalisation, top values, inferred type, and signals:

* `CONSTANT` — one value everywhere → carries no information (the shared login problem)
* `inconsistent_spelling` — hand-typed data
* `name_like`, `repeating_values`, `low_cardinality`, `free_text`, `identifier`, `mostly_empty`, `multi_valued`
* `NEVER USED` declared options — `Lost` exists in the tool but no record has it

Rendered compactly (≈2k tokens for a CRM with three collections) so the mapping call is cheap and no raw records leave the server.

### 2. Semantic map (one LLM call per connection, cached)
Output per collection: description, record nouns, and `concept → {field, kind, confidence, evidence, value_map}`. Category values can be **rules across fields**:

```json
"status": {
  "field": "status", "kind": "category", "confidence": 0.9,
  "evidence": "built-in status has Open/Won only; Lost never used, lost encoded in stage 'Dead Leads'",
  "value_map": {
    "open": {"all": [{"field": "status", "in": ["Open"]}, {"field": "stage", "not_in": ["Dead Leads"]}]},
    "won":  ["Won"],
    "lost": {"field": "stage", "in": ["Dead Leads"]}
  }
}
```

`missing_concepts` records what the data genuinely does not track (with a reason), so questions about it are answered honestly instead of with 0.

People fields get an alias table: a deterministic union-find over spellings (same first name with Damerau-tolerant typos, abbreviations, initials like "G. Sharma"/"IK") refined by a small LLM call. On the demo CRM, 22 raw spellings become 4 people.

### 3. Intent
The model sees the capabilities derived from the map (collections, record nouns, concepts, allowed category keys, known people) and returns:

```json
{"collection": "deals", "operation": "count",
 "filters": [{"concept": "owner", "op": "eq", "value": "Garima"}, {"concept": "status", "op": "eq", "value": "open"}],
 "group_by": null, "interpretation": "Count open deals owned by Garima", "confidence": 0.9}
```

Operations: count, list, sum, avg, min, max, group_count, group_sum. Filter ops: eq, neq, in, contains, gt/gte/lt/lte, between, is_empty, not_empty. Relative dates are converted using today's date.

### 4. Planner
Binds each filter: person → alias cluster (fuzzy, with ambiguity detection and "did you mean"), category → rule from the value map (synonyms: active/live/in play → open, dead/abandoned → lost, urgent/hot/P1 → high…), number/date → direct, text → contains. Every binding carries a human note and the map's evidence. Unbound concepts make the plan non-executable with a reason.

### 5. Executor
Filters records with the rule language (`task1/rules.py`), aggregates, computes per-filter counts (used for diagnosis), and canonicalises group keys (so "deals per owner" shows "Garima Sharma", not seven spellings).

### 6. Explanation
* `answer` — phrased sentence + steps + wider context (e.g. all 21 of Garima's deals broken down by stage)
* `empty_with_reason` — "2 records match the other filters but none is won; here is how they break down"
* `unanswerable` — "This data does not track 'region' anywhere. Closest field: …"

## Walk-through: "How many open deals does Garima own?"

Demo CRM output (abridged):

> **Garima has 14 active deals.**
> 1. Understood the question as: count open deals owned by Garima Sharma
> 2. owner = Garima Sharma, matched via spellings "Garima", "garima", "Garima S.", "G. Sharma", "Garima Sharma", "garima sharma", "Garmia" in 'Assigned To' — why this field: custom text field, 90% fill, 21 distinct names, inconsistent spelling; official owner field is a single shared login
> 3. 'open' ⇒ status = open ⇒ status ∈ {Open} AND stage ∉ {Dead Leads} — why: Lost/Deleted never used, lost encoded in stage "Dead Leads"
> 4. Applied the filters to 71 records → 14 deals matched; per-filter counts: owner 21, status 45

Same code on the Jira demo: "How many completed tickets does Garima have?" → `Status ∈ {Done} AND Resolution ∈ {Done}` (11), and "abandoned" → `Resolution ∈ {Won't Do}` (3).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/task1/sources` | available sources and their config fields |
| `POST /api/task1/connect {source, config, force_remap}` | fetch, profile, map; returns connection id, semantic map, profiles |
| `POST /api/task1/ask {connection_id, question}` | answer + steps + plan + intent + usage |
| `GET /api/task1/connections/{id}` | map, profiles, history |
| `POST /api/task1/connections/{id}/override {collection, concept, spec}` | human correction of a mapping (persisted) |

## Adding a connector

Implement `load() -> list[Collection]` returning flat records and `FieldMeta(name, label, type, is_custom, options)`. Resolve ids to labels (stage ids → names, enum ids → labels, user objects → names) — that is all the tool-specific knowledge needed. Register it in `task1/adapters/registry.py`. An MCP-served tool fits the same shape: `list_resources` → collections, `read_resource` → records.

## Limitations and next steps
* Records are loaded (≤2,000 per collection) and filtered in memory. The next step for big tenants is translating bound rules into the tool's own query API; the plan already contains exactly the information needed.
* Multi-collection joins ("deals of contacts in Mumbai") are not supported yet; the IR is single-collection.
* Corrections via `override` are persisted but there is no UI; a "was this right?" loop would feed future mappings.
