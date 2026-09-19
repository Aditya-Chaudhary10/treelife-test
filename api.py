"""Optional REST API (the product UI is the Streamlit app: `streamlit run streamlit_app.py`).

Run with:  uvicorn api:app --port 8000
  /api/task1/*   connect / ask against any source          /api/task2/*  workspaces, upload, chat, downloads
  /mock/*        the demo CRM / Jira endpoints over HTTP    /docs         OpenAPI
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from task1.mock_server.routes import router as mock_router
from task1.router import router as task1_router
from task2.router import router as task2_router

app = FastAPI(title="Treelife AI — Technical Assessment API", version="1.0")
app.include_router(mock_router)
app.include_router(task1_router)
app.include_router(task2_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
