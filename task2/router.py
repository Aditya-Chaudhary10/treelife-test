"""REST API + UI for Task 2."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from shared.llm import LLMNotConfigured

from .engine import engine
from .workspace import store

router = APIRouter(tags=["task2"])
STATIC = Path(__file__).parent / "static"


class CreateWorkspace(BaseModel):
    name: str = "workspace"


class ChatRequest(BaseModel):
    message: str


@router.get("/task2", response_class=HTMLResponse, include_in_schema=False)
def ui():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@router.get("/api/task2/workspaces")
def list_workspaces():
    return {"workspaces": store.list()}


@router.post("/api/task2/workspaces")
def create_workspace(req: CreateWorkspace):
    ws = store.create(req.name)
    return ws.as_dict()


def _ws(ws_id: str):
    try:
        return store.get(ws_id)
    except KeyError:
        raise HTTPException(404, "unknown workspace")


@router.get("/api/task2/workspaces/{ws_id}")
def get_workspace(ws_id: str):
    ws = _ws(ws_id)
    return {**ws.as_dict(), "index": engine.index(ws).stats(), "chat": ws.chat}


@router.post("/api/task2/workspaces/{ws_id}/upload")
async def upload(ws_id: str, files: list[UploadFile] = File(...)):
    ws = _ws(ws_id)
    uploads = [(f.filename or "file", await f.read()) for f in files]
    return engine.upload(ws, uploads)


@router.post("/api/task2/workspaces/{ws_id}/chat")
def chat(ws_id: str, req: ChatRequest):
    ws = _ws(ws_id)
    if not ws.latest_files():
        raise HTTPException(400, "upload some files first")
    try:
        return engine.chat(ws, req.message)
    except LLMNotConfigured as e:
        raise HTTPException(500, str(e))


@router.get("/api/task2/workspaces/{ws_id}/files/{file_id}/download")
def download(ws_id: str, file_id: str):
    ws = _ws(ws_id)
    if file_id not in ws.files:
        raise HTTPException(404, "unknown file")
    rec = ws.files[file_id]
    return FileResponse(ws.file_path(file_id), filename=rec.name)


@router.get("/api/task2/workspaces/{ws_id}/files/{file_id}")
def file_detail(ws_id: str, file_id: str):
    ws = _ws(ws_id)
    if file_id not in ws.files:
        raise HTTPException(404, "unknown file")
    from .ingest import load_parsed

    parsed = load_parsed(ws, file_id)
    return {"file": ws.files[file_id].__dict__, "outline": parsed.outline, "tables": parsed.tables,
            "units": [{"id": u.id, "kind": u.kind, "text": u.text[:300], "loc": u.loc} for u in parsed.units[:200]]}
