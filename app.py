"""Treelife AI technical assessment — single FastAPI app.

  /task1   Semantic Business Data Translation Layer (UI)      /api/task1/*
  /task2   Enterprise Document Workspace (UI)                 /api/task2/*
  /mock    Messy demo SaaS endpoints (Pipedrive/Jira-shaped)  used by Task 1's adapters over HTTP
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from task1.mock_server.routes import router as mock_router

app = FastAPI(title="Treelife AI — Technical Assessment", version="1.0")
app.include_router(mock_router)

try:  # routers are optional so the mock server can be booted while the rest is being built/tested
    from task1.router import router as task1_router

    app.include_router(task1_router)
except ImportError:  # pragma: no cover
    pass
try:
    from task2.router import router as task2_router

    app.include_router(task2_router)
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).parent


@app.get("/", include_in_schema=False)
def landing():
    page = ROOT / "static_index.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return RedirectResponse("/task1")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
