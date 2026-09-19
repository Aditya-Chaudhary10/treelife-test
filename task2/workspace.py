"""Workspace = the single place files live. Upload once; everything else references file ids.

  data/task2/workspaces/<ws>/workspace.json           registry (files, versions, chat state)
  data/task2/workspaces/<ws>/files/<file_id>/original.<ext>
  data/task2/workspaces/<ws>/files/<file_id>/parsed.json      structured units (parse once)
  data/task2/workspaces/<ws>/files/<file_id>/tables/<sheet>.pkl  DataFrames for SQL queries
  data/task2/workspaces/<ws>/index.db + vectors.npy    search index (hybrid BM25 + embeddings)

Duplicates are detected by SHA-256 — re-uploading the same 30-file ZIP costs nothing.
Edits never overwrite: they create a new version file linked to its parent.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from shared.config import settings

WS_ROOT = settings.data_dir / "task2" / "workspaces"
WS_ROOT.mkdir(parents=True, exist_ok=True)

SUPPORTED = {".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".txt", ".md"}


@dataclass
class FileRecord:
    id: str
    name: str
    ext: str
    sha256: str
    size: int
    version: int = 1
    parent_id: str | None = None
    status: str = "uploaded"          # uploaded | indexed | error
    error: str | None = None
    kind: str = ""                    # pdf | docx | xlsx | csv | text
    pages: int = 0
    sheets: list[str] = field(default_factory=list)
    hidden_sheets: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    summary: str = ""
    tokens_estimate: int = 0          # what it would cost to stuff this file into a prompt
    chunks: int = 0
    added_at: float = field(default_factory=time.time)
    note: str = ""                    # e.g. "edited: payment terms 30 -> 45 days"

    def manifest_line(self) -> str:
        bits = [f"[{self.id}] {self.name}"]
        if self.version > 1:
            bits.append(f"v{self.version}")
        if self.kind in ("xlsx", "csv"):
            sh = ", ".join(self.sheets[:8])
            bits.append(f"sheets: {sh}" + (" (+hidden: " + ", ".join(self.hidden_sheets) + ")" if self.hidden_sheets else ""))
        elif self.pages:
            bits.append(f"{self.pages} pages")
        if self.summary:
            bits.append(self.summary)
        elif self.outline:
            bits.append("sections: " + "; ".join(self.outline[:6]))
        return " — ".join(bits)


@dataclass
class Workspace:
    id: str
    name: str
    files: dict[str, FileRecord] = field(default_factory=dict)
    chat: list[dict[str, Any]] = field(default_factory=list)   # compact memory: {q, strategy, files, summary}
    created_at: float = field(default_factory=time.time)

    # -- paths ------------------------------------------------------------------------------------
    @property
    def dir(self) -> Path:
        return WS_ROOT / self.id

    def file_dir(self, file_id: str) -> Path:
        return self.dir / "files" / file_id

    def file_path(self, file_id: str) -> Path:
        f = self.files[file_id]
        return self.file_dir(file_id) / f"original{f.ext}"

    def parsed_path(self, file_id: str) -> Path:
        return self.file_dir(file_id) / "parsed.json"

    # -- persistence ------------------------------------------------------------------------------
    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {"id": self.id, "name": self.name, "created_at": self.created_at, "chat": self.chat,
                "files": {k: asdict(v) for k, v in self.files.items()}}
        (self.dir / "workspace.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, ws_id: str) -> "Workspace":
        p = WS_ROOT / ws_id / "workspace.json"
        if not p.exists():
            raise KeyError(ws_id)
        d = json.loads(p.read_text(encoding="utf-8"))
        ws = cls(id=d["id"], name=d["name"], created_at=d.get("created_at", 0), chat=d.get("chat", []))
        ws.files = {k: FileRecord(**v) for k, v in d.get("files", {}).items()}
        return ws

    # -- files ------------------------------------------------------------------------------------
    def add_bytes(self, name: str, data: bytes) -> list[tuple[FileRecord, bool]]:
        """Add one upload. ZIPs are expanded. Returns [(record, was_duplicate)]."""
        name = Path(name).name
        ext = Path(name).suffix.lower()
        if ext == ".zip":
            out: list[tuple[FileRecord, bool]] = []
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    base = Path(info.filename).name
                    if info.is_dir() or not base or base.startswith((".", "~$")) or "__MACOSX" in info.filename:
                        continue
                    if Path(base).suffix.lower() in SUPPORTED:
                        out.extend(self.add_bytes(base, z.read(info)))
            return out
        if ext not in SUPPORTED:
            raise ValueError(f"unsupported file type: {ext or name}")
        sha = hashlib.sha256(data).hexdigest()
        for f in self.files.values():
            if f.sha256 == sha:
                return [(f, True)]
        fid = uuid.uuid4().hex[:8]
        rec = FileRecord(id=fid, name=name, ext=ext, sha256=sha, size=len(data), kind=_kind(ext))
        d = self.file_dir(fid)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"original{ext}").write_bytes(data)
        self.files[fid] = rec
        self.save()
        return [(rec, False)]

    def add_version(self, parent_id: str, data: bytes, note: str) -> FileRecord:
        parent = self.files[parent_id]
        sha = hashlib.sha256(data).hexdigest()
        fid = uuid.uuid4().hex[:8]
        stem = re.sub(r"\s+v\d+$", "", Path(parent.name).stem)
        rec = FileRecord(id=fid, name=f"{stem} v{parent.version + 1}{parent.ext}", ext=parent.ext, sha256=sha, size=len(data),
                         version=parent.version + 1, parent_id=parent_id, kind=parent.kind, note=note)
        d = self.file_dir(fid)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"original{parent.ext}").write_bytes(data)
        self.files[fid] = rec
        self.save()
        return rec

    def find(self, ref: str) -> FileRecord | None:
        """Resolve a file id or (fuzzy) name to a record; latest versions preferred."""
        if ref in self.files:
            return self.files[ref]
        ref_l = ref.lower().strip()
        cands = sorted(self.files.values(), key=lambda f: -f.version)
        for f in cands:
            if f.name.lower() == ref_l or Path(f.name).stem.lower() == ref_l:
                return f
        for f in cands:
            if ref_l in f.name.lower():
                return f
        return None

    def latest_files(self) -> list[FileRecord]:
        superseded = {f.parent_id for f in self.files.values() if f.parent_id}
        return sorted((f for f in self.files.values() if f.id not in superseded), key=lambda f: f.added_at)

    def manifest_text(self) -> str:
        """The compact table of contents the planner sees on every turn (~1-2 lines per file)."""
        return "\n".join(f.manifest_line() for f in self.latest_files() if f.status == "indexed")

    def total_tokens(self) -> int:
        return sum(f.tokens_estimate for f in self.latest_files())

    def remember(self, question: str, strategy: str, files: list[str], summary: str) -> None:
        self.chat.append({"q": question[:300], "strategy": strategy, "files": files[:10], "summary": summary[:400], "t": time.time()})
        self.chat = self.chat[-12:]
        self.save()

    def memory_text(self) -> str:
        if not self.chat:
            return "(no previous turns)"
        return "\n".join(f"- Q: {t['q']} → [{t['strategy']} on {', '.join(t['files'])}] {t['summary']}" for t in self.chat[-6:])

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "created_at": self.created_at,
                "files": [asdict(f) for f in sorted(self.files.values(), key=lambda f: f.added_at)],
                "total_tokens": self.total_tokens(), "turns": len(self.chat)}


def _kind(ext: str) -> str:
    return {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv", ".txt": "text", ".md": "text"}[ext]


class Store:
    def create(self, name: str) -> Workspace:
        ws = Workspace(id=uuid.uuid4().hex[:8], name=name or "workspace")
        ws.save()
        return ws

    def get(self, ws_id: str) -> Workspace:
        return Workspace.load(ws_id)

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(WS_ROOT.glob("*/workspace.json")):
            try:
                ws = Workspace.load(p.parent.name)
                out.append({"id": ws.id, "name": ws.name, "files": len(ws.latest_files()), "created_at": ws.created_at})
            except Exception:
                continue
        return sorted(out, key=lambda w: -w["created_at"])


store = Store()
