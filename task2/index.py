"""Per-workspace search index: hybrid BM25 (lexical) + local embeddings (semantic), fused with RRF.

Chunks are built from parsed units (~450 tokens, heading context prepended) and stored in SQLite;
vectors live in a NumPy file. Adding a file is incremental — indexing file 51 does not touch 1..50.
Search can be scoped to a set of file ids, which is how "focus on Document A" is enforced.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from shared import embeddings
from shared.llm import approx_tokens

from .parsers import ParsedDoc

CHUNK_TOKENS = 450
_TOK = re.compile(r"[a-z0-9]+(?:[.\-'][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOK.findall(text.lower())


def build_chunks(file_id: str, file_name: str, parsed: ParsedDoc) -> list[dict[str, Any]]:
    """Group units into chunks. Row-blocks and pages are already sized; paragraphs are packed."""
    chunks: list[dict[str, Any]] = []
    buf: list[Any] = []
    buf_tokens = 0
    section = ""

    def flush():
        nonlocal buf, buf_tokens
        if not buf:
            return
        text = "\n".join(u.text for u in buf)
        prefix = f"[{file_name}" + (f" › {section}" if section else "") + "]\n"
        chunks.append({"file_id": file_id, "unit_ids": [u.id for u in buf], "loc": buf[0].loc, "text": prefix + text, "n_tokens": approx_tokens(prefix + text)})
        buf, buf_tokens = [], 0

    for u in parsed.units:
        if u.kind in ("page", "rows", "sheet", "table"):
            flush()
            if u.kind == "sheet":
                section = u.loc.get("sheet", "")
            buf = [u]
            flush()
            continue
        if u.kind == "heading":
            flush()
            section = u.text
        t = approx_tokens(u.text)
        if buf_tokens + t > CHUNK_TOKENS and buf:
            flush()
        buf.append(u)
        buf_tokens += t
    flush()
    return chunks


def _locked(fn):
    def wrapper(self, *a, **kw):
        with self._lock:
            return fn(self, *a, **kw)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Index:
    def __init__(self, ws_dir: Path):
        self.db_path = ws_dir / "index.db"
        self.vec_path = ws_dir / "vectors.npy"
        self.ids_path = ws_dir / "vector_ids.json"
        # FastAPI serves sync endpoints from a thread pool; one connection shared under a lock is plenty here
        self.con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self.con.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, file_id TEXT, file_name TEXT, unit_ids TEXT, loc TEXT, text TEXT, n_tokens INTEGER)")
        self.con.execute("CREATE INDEX IF NOT EXISTS ix_file ON chunks(file_id)")
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[int] = []
        self._vecs: np.ndarray | None = None
        self._vec_ids: list[int] = []
        self._load_vectors()

    # ------------------------------------------------------------------ write
    @_locked
    def add_file(self, file_id: str, file_name: str, parsed: ParsedDoc) -> int:
        self.remove_file(file_id)
        chunks = build_chunks(file_id, file_name, parsed)
        cur = self.con.cursor()
        ids = []
        for c in chunks:
            cur.execute("INSERT INTO chunks (file_id, file_name, unit_ids, loc, text, n_tokens) VALUES (?,?,?,?,?,?)",
                        (file_id, file_name, json.dumps(c["unit_ids"]), json.dumps(c["loc"]), c["text"], c["n_tokens"]))
            ids.append(cur.lastrowid)
        self.con.commit()
        if embeddings.available() and chunks:
            vecs = embeddings.embed([c["text"] for c in chunks])
            self._vecs = vecs if self._vecs is None or self._vecs.size == 0 else np.vstack([self._vecs, vecs])
            self._vec_ids.extend(ids)
            self._save_vectors()
        self._bm25 = None
        return len(chunks)

    @_locked
    def remove_file(self, file_id: str) -> None:
        rows = [r[0] for r in self.con.execute("SELECT id FROM chunks WHERE file_id=?", (file_id,))]
        if not rows:
            return
        self.con.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
        self.con.commit()
        if self._vecs is not None and self._vec_ids:
            keep = [i for i, cid in enumerate(self._vec_ids) if cid not in set(rows)]
            self._vecs = self._vecs[keep] if keep else np.zeros((0, self._vecs.shape[1]), dtype=np.float32)
            self._vec_ids = [self._vec_ids[i] for i in keep]
            self._save_vectors()
        self._bm25 = None

    def _save_vectors(self) -> None:
        if self._vecs is not None:
            np.save(self.vec_path, self._vecs)
            self.ids_path.write_text(json.dumps(self._vec_ids))

    def _load_vectors(self) -> None:
        if self.vec_path.exists() and self.ids_path.exists():
            self._vecs = np.load(self.vec_path)
            self._vec_ids = json.loads(self.ids_path.read_text())

    # ------------------------------------------------------------------ read
    @_locked
    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        rows = self.con.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
        self._bm25_ids = [r[0] for r in rows]
        self._bm25 = BM25Okapi([tokenize(r[1]) for r in rows]) if rows else None

    @_locked
    def get(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        q = f"SELECT id, file_id, file_name, unit_ids, loc, text, n_tokens FROM chunks WHERE id IN ({','.join('?' * len(ids))})"
        rows = {r[0]: r for r in self.con.execute(q, ids)}
        return [_row(rows[i]) for i in ids if i in rows]

    @_locked
    def file_chunks(self, file_id: str) -> list[dict[str, Any]]:
        return [_row(r) for r in self.con.execute("SELECT id, file_id, file_name, unit_ids, loc, text, n_tokens FROM chunks WHERE file_id=? ORDER BY id", (file_id,))]

    @_locked
    def stats(self) -> dict[str, Any]:
        n, tok = self.con.execute("SELECT COUNT(*), COALESCE(SUM(n_tokens),0) FROM chunks").fetchone()
        return {"chunks": n, "tokens": tok, "vectors": 0 if self._vecs is None else int(self._vecs.shape[0])}

    @_locked
    def search(self, query: str, file_ids: list[str] | None = None, k: int = 10) -> list[dict[str, Any]]:
        """Hybrid search with reciprocal-rank fusion; optional scope to file ids."""
        self._ensure_bm25()
        if self._bm25 is None:
            return []
        allowed: set[int] | None = None
        if file_ids:
            q = f"SELECT id FROM chunks WHERE file_id IN ({','.join('?' * len(file_ids))})"
            allowed = {r[0] for r in self.con.execute(q, file_ids)}
            if not allowed:
                return []
        pool = max(k * 4, 30)
        scores = self._bm25.get_scores(tokenize(query))
        order = np.argsort(-scores)
        lex = [self._bm25_ids[i] for i in order if scores[i] > 0 and (allowed is None or self._bm25_ids[i] in allowed)][:pool]
        sem: list[int] = []
        if embeddings.available() and self._vecs is not None and self._vecs.size:
            qv = embeddings.embed_query(query)
            sims = self._vecs @ qv
            for i in np.argsort(-sims)[: pool * 3]:
                cid = self._vec_ids[i]
                if allowed is None or cid in allowed:
                    sem.append(cid)
                if len(sem) >= pool:
                    break
        fused: dict[int, float] = {}
        for rank, cid in enumerate(lex):
            fused[cid] = fused.get(cid, 0) + 1 / (60 + rank)
        for rank, cid in enumerate(sem):
            fused[cid] = fused.get(cid, 0) + 1 / (60 + rank)
        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        rows = {r["id"]: r for r in self.get([cid for cid, _ in top])}
        return [dict(rows[cid], score=round(s, 4)) for cid, s in top if cid in rows]


def _row(r) -> dict[str, Any]:
    return {"id": r[0], "file_id": r[1], "file_name": r[2], "unit_ids": json.loads(r[3]), "loc": json.loads(r[4]), "text": r[5], "n_tokens": r[6]}
