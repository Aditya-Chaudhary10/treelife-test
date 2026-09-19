"""Optional REST API for Task 1 (the Streamlit pages call the engine directly)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from shared.llm import LLMNotConfigured

from .adapters.base import ConnectorError
from .adapters.registry import SOURCES
from .engine import engine

router = APIRouter(tags=["task1"])


class ConnectRequest(BaseModel):
    source: str = Field(..., description="one of /api/task1/sources")
    config: dict[str, Any] = Field(default_factory=dict)
    force_remap: bool = False


class AskRequest(BaseModel):
    connection_id: str
    question: str


class OverrideRequest(BaseModel):
    collection: str
    concept: str
    spec: dict[str, Any] | None = None  # null deletes the concept


@router.get("/api/task1/sources")
def sources():
    return {"sources": [{"id": k, **v} for k, v in SOURCES.items()]}


@router.post("/api/task1/connect")
def connect(req: ConnectRequest, request: Request):
    self_base = str(request.base_url).rstrip("/")
    try:
        conn = engine.connect(req.source, req.config, self_base, force_remap=req.force_remap)
    except ConnectorError as e:
        raise HTTPException(400, str(e))
    except LLMNotConfigured as e:
        raise HTTPException(500, str(e))
    return {"connection": conn.summary(), "semantic_map": conn.semantic_map, "profiles": conn.profiles_dict()}


@router.get("/api/task1/connections")
def connections():
    return {"connections": [c.summary() for c in engine.connections.values()]}


@router.get("/api/task1/connections/{conn_id}")
def connection(conn_id: str):
    try:
        conn = engine.get(conn_id)
    except KeyError:
        raise HTTPException(404, "unknown connection")
    return {"connection": conn.summary(), "semantic_map": conn.semantic_map, "profiles": conn.profiles_dict(), "history": conn.history}


@router.post("/api/task1/connections/{conn_id}/override")
def override(conn_id: str, req: OverrideRequest):
    try:
        smap = engine.override(conn_id, req.collection, req.concept, req.spec)
    except KeyError:
        raise HTTPException(404, "unknown connection")
    return {"semantic_map": smap}


@router.post("/api/task1/ask")
def ask(req: AskRequest):
    try:
        return engine.ask(req.connection_id, req.question)
    except KeyError:
        raise HTTPException(404, "unknown connection — connect first")
    except LLMNotConfigured as e:
        raise HTTPException(500, str(e))
