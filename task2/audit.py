"""Cross-audit one document against the rest without reading the rest.

  1. take the TARGET's chunks (bounded — big targets are narrowed by search)
  2. extract ≤ 12 checkable claims (amounts, dates, terms, parties) with a search query each
  3. for every claim retrieve the top-3 passages from the SUPPORT set only
  4. compare claims vs evidence in small batches, output structured findings
Token cost ≈ target text + (3 passages × claims), independent of how many support files exist."""
from __future__ import annotations

from typing import Any

from shared import llm
from shared.config import settings
from shared.llm import approx_tokens

from .answer import pack_sources
from .index import Index, tokenize
from .workspace import FileRecord, Workspace

_EXTRACT = """From the document passages below, list the CHECKABLE claims worth verifying against other documents:
figures, dates, deadlines, percentages, party names, obligations, defined terms. Max 10, most important first.
Each claim must be ATOMIC — exactly one fact (one number, date, period or obligation). Never combine two facts in one claim.
ALWAYS include, when the document states them: the fee/price, payment terms (days), service level / uptime, termination notice period,
contract term/renewal, effective date and the parties. Then add other notable clauses.
For each claim write a short keyword search query that would find the same topic in OTHER documents about the SAME party/deal:
always include the specific party, product or reference names from the document (e.g. "Nimbus Software payment terms days invoice").
Output ONLY JSON: {"claims": [{"claim": "...", "kind": "amount|date|term|party|obligation|other", "query": "keywords"}]}"""

_COMPARE = """You are auditing a document against supporting evidence from other documents.
For each claim decide: "consistent" (evidence agrees), "discrepancy" (evidence conflicts — state both values), or "not_found" (no evidence about it).
Quote the conflicting values and cite the source tags [S#]. Be precise; do not invent evidence.
IMPORTANT: evidence about a DIFFERENT party, vendor or contract than the target (e.g. another vendor's agreement built from the same template) is NOT evidence about the target's claim — never cite it, never use it to mark a claim consistent or a discrepancy. If only such evidence exists, the status is "not_found".
A company policy, a register/ledger, board minutes, or an invoice that concerns the target party or applies to all vendors IS valid evidence (e.g. "policy requires 99.9% uptime" vs a 99.5% clause = discrepancy).
Evidence from registers, minutes, policies or invoices that mention the target party IS relevant, even when it uses different wording (e.g. a "Net 45" terms column vs "payable within 30 days").
Output ONLY JSON: {"findings": [{"claim": "...", "status": "consistent|discrepancy|not_found", "evidence": "what the sources say, with [S#] tags", "severity": "high|medium|low"}]}"""


def _focus(text: str, query: str, max_chars: int) -> str:
    """Keep the window of a long passage that best matches the query (instead of its head)."""
    if len(text) <= max_chars:
        return text
    terms = set(tokenize(query))
    lines = text.splitlines()
    if not lines:
        return text[:max_chars]
    scores = [len(terms & set(tokenize(ln))) for ln in lines]
    best = max(range(len(lines)), key=lambda i: (scores[i], -i))
    lo = hi = best
    out = lines[best]
    while len(out) < max_chars and (lo > 0 or hi < len(lines) - 1):
        if lo > 0:
            lo -= 1
            out = lines[lo] + "\n" + out
        if hi < len(lines) - 1 and len(out) < max_chars:
            hi += 1
            out = out + "\n" + lines[hi]
    head = lines[0] if lines[0].startswith("[") and lo > 0 else ""
    return (head + "\n" if head else "") + out[:max_chars] + " …"


def _collapse_templates(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop passages that are near-duplicates of an earlier one (same clause from a shared template)."""
    out: list[dict[str, Any]] = []
    seen: list[set[str]] = []
    for h in hits:
        body = h["text"].split("\n", 1)[1] if h["text"].startswith("[") and "\n" in h["text"] else h["text"]
        toks = set(tokenize(body))
        if any(len(toks & s) / max(len(toks | s), 1) >= 0.85 for s in seen):
            continue
        seen.append(toks)
        out.append(h)
    return out


def _select_evidence(hits: list[dict[str, Any]], entity: str, claim_text: str, n: int = 5) -> list[dict[str, Any]]:
    """Tiered, claim-relevant pick: passages naming the entity, then non-template documents (registers,
    policies, minutes), then the rest — each tier ranked by lexical overlap with the claim, ≤2 per file."""
    ent_l = entity.lower()
    q = set(tokenize(claim_text)) - {"the", "of", "a", "and", "in", "to"}

    def overlap(h: dict[str, Any]) -> float:
        toks = set(tokenize(h["text"]))
        return len(q & toks) / max(len(q), 1)

    tiers = [
        [h for h in hits if ent_l in h["text"].lower()],
        [h for h in hits if ent_l not in h["text"].lower() and "contract" not in h["file_name"].lower()],
        [h for h in hits if ent_l not in h["text"].lower() and "contract" in h["file_name"].lower()],
    ]
    quota = [2, 2, 1]
    picked: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    for tier, k in zip(tiers, quota):
        for h in sorted(tier, key=lambda h: (-overlap(h), -h["score"])):
            if k <= 0 or per_file.get(h["file_id"], 0) >= 2:
                continue
            picked.append(h)
            per_file[h["file_id"]] = per_file.get(h["file_id"], 0) + 1
            k -= 1
    # fill remaining slots with the most claim-relevant leftovers
    if len(picked) < n:
        rest = [h for h in hits if h not in picked]
        for h in sorted(rest, key=lambda h: (-overlap(h), -h["score"])):
            if len(picked) >= n:
                break
            if per_file.get(h["file_id"], 0) >= 2:
                continue
            picked.append(h)
            per_file[h["file_id"]] = per_file.get(h["file_id"], 0) + 1
    return picked[:n]


def _target_chunks(index: Index, target: FileRecord, question: str, budget: int) -> list[dict[str, Any]]:
    chunks = index.file_chunks(target.id)
    total = sum(c["n_tokens"] for c in chunks)
    if total <= budget:
        return chunks
    ranked = index.search(question + " amounts dates terms obligations parties", file_ids=[target.id], k=40)
    out, used = [], 0
    for c in ranked:
        if used + c["n_tokens"] > budget:
            break
        out.append(c)
        used += c["n_tokens"]
    return sorted(out, key=lambda c: c["id"])


def _entity(target: FileRecord) -> str:
    """Best-effort party/subject name from the file name, e.g. 'Vendor Contract - Nimbus Software.docx' -> 'Nimbus Software'."""
    stem = target.name.rsplit(".", 1)[0]
    for sep in (" - ", " – ", " — ", ": "):
        if sep in stem:
            return stem.split(sep)[-1].strip()
    return stem


def cross_audit(ws: Workspace, index: Index, target: FileRecord, support_ids: list[str], question: str) -> dict[str, Any]:
    budget = settings.context_budget
    entity = _entity(target)
    tchunks = _target_chunks(index, target, question, budget - 1200)
    target_text, _ = pack_sources(tchunks, budget - 1200)
    ext = llm.chat_json([{"role": "system", "content": _EXTRACT}, {"role": "user", "content": f"DOCUMENT: {target.name}\nFOCUS: {question}\n\n{target_text}"}],
                        model=settings.model_fast, reasoning="low", max_tokens=1200, step="audit:extract")
    claims = [c for c in (ext.get("claims") or []) if isinstance(c, dict) and c.get("claim")][:10]
    if not claims:
        return {"findings": [], "claims": [], "report": "No checkable claims were found in the target document.", "target_tokens": sum(c["n_tokens"] for c in tchunks)}

    # gather evidence per claim (support files only), dedupe chunks across claims
    evidence: dict[int, dict[str, Any]] = {}
    per_claim: list[list[int]] = []
    for c in claims:
        hits: list[dict[str, Any]] = []
        if support_ids:
            # two probes: the model's query, and an entity-anchored one so registers/minutes/policies about THIS party surface
            seen_ids: set[int] = set()
            for q in (str(c.get("query") or c["claim"]), f"{entity} {c['claim']}", f"policy {c.get('kind', '')} {c['claim'][:80]}"):
                for h in index.search(q, file_ids=support_ids, k=20):
                    if h["id"] not in seen_ids:
                        seen_ids.add(h["id"])
                        hits.append(h)
            # templated documents (12 contracts with the same clause) would otherwise flood the candidates:
            # collapse near-identical passages to one representative, then prefer passages that mention the
            # entity or come from non-template documents (registers, minutes, policies)
            hits = _select_evidence(_collapse_templates(hits), entity, f"{c.get('query', '')} {c['claim']}")
        picked = hits
        ids = []
        for h in picked:
            h = dict(h)
            if h["n_tokens"] > 380:  # trim long passages to the window that matters; evidence needs to be dense
                h["text"] = _focus(h["text"], f"{c.get('query', '')} {c['claim']}", 380 * 3)
                h["n_tokens"] = 380
            evidence.setdefault(h["id"], h)
            ids.append(h["id"])
        per_claim.append(ids)

    # compare in batches that respect the budget
    findings: list[dict[str, Any]] = []
    sources_used: list[dict[str, Any]] = []
    i = 0
    while i < len(claims):
        batch_claims, batch_ev, tokens = [], {}, 0
        while i < len(claims):
            ev_ids = per_claim[i]
            add = sum(evidence[e]["n_tokens"] for e in ev_ids if e not in batch_ev) + approx_tokens(claims[i]["claim"]) + 40
            if batch_claims and (tokens + add > budget - 900 or len(batch_claims) >= 5):
                break
            batch_claims.append(claims[i])
            for e in ev_ids:
                batch_ev[e] = evidence[e]
            tokens += add
            i += 1
        src_text, used = pack_sources(list(batch_ev.values()), budget - 900)
        tagmap = {u["chunk_id"]: u["tag"] for u in used}
        claim_lines = "\n".join(f"{n + 1}. [{c.get('kind', 'other')}] {c['claim']}  (evidence: {', '.join(tagmap.get(e, '?') for e in per_claim[claims.index(c)])})" for n, c in enumerate(batch_claims))
        cmp = llm.chat_json([{"role": "system", "content": _COMPARE}, {"role": "user", "content": f"TARGET DOCUMENT: {target.name}\n\nCLAIMS:\n{claim_lines}\n\nEVIDENCE FROM OTHER DOCUMENTS:\n{src_text or '(none found)'}"}],
                            model=settings.model_strong, reasoning="low", max_tokens=2500, step="audit:compare")
        for f in cmp.get("findings") or []:
            if isinstance(f, dict) and f.get("claim"):
                f.setdefault("status", "not_found")
                f.setdefault("severity", "low")
                findings.append(f)
        sources_used.extend(used)

    disc = [f for f in findings if f["status"] == "discrepancy"]
    ok = [f for f in findings if f["status"] == "consistent"]
    nf = [f for f in findings if f["status"] == "not_found"]
    lines = [f"**Cross-audit of {target.name}** against {len(support_ids)} document(s): {len(disc)} discrepancies, {len(ok)} consistent, {len(nf)} not verifiable.", ""]
    if disc:
        lines.append("**Discrepancies**")
        lines.extend(f"- ⚠ ({f.get('severity')}) {f['claim']} — {f.get('evidence', '')}" for f in disc)
        lines.append("")
    if ok:
        lines.append("**Consistent**")
        lines.extend(f"- ✓ {f['claim']} — {f.get('evidence', '')}" for f in ok)
        lines.append("")
    if nf:
        lines.append("**Not verifiable from the other documents**")
        lines.extend(f"- ? {f['claim']}" for f in nf)
    # dedupe sources for the UI
    seen, srcs = set(), []
    for s in sources_used:
        key = (s["file_id"], str(s["loc"]))
        if key not in seen:
            seen.add(key)
            srcs.append(s)
    claim_evidence = [{"claim": c["claim"], "query": c.get("query"), "evidence": [{"file_name": evidence[e]["file_name"], "loc": evidence[e]["loc"]} for e in ids]}
                      for c, ids in zip(claims, per_claim)]
    return {"findings": findings, "claims": claims, "claim_evidence": claim_evidence, "report": "\n".join(lines), "sources": srcs,
            "target_tokens": sum(c["n_tokens"] for c in tchunks), "evidence_tokens": sum(e["n_tokens"] for e in evidence.values())}
