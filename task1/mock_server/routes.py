"""Optional HTTP exposure of the mock SaaS (used by api.py). The Streamlit app talks to the same
service through an in-process httpx transport (transport.py) and needs no server."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import service

router = APIRouter(prefix="/mock", tags=["mock-saas"])


@router.get("/crm/v1/{resource}")
def pipedrive_like(resource: str, start: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    body = service.crm_list(resource, start, limit)
    if body is None:
        raise HTTPException(404, f"unknown resource {resource}")
    return body


@router.get("/jira/rest/api/3/field")
def jira_fields():
    return service.jira_fields()


@router.get("/jira/rest/api/3/search/jql")
def jira_search(jql: str = "", maxResults: int = Query(50, ge=1, le=100), nextPageToken: str | None = None, fields: str = "*all"):
    return service.jira_search(maxResults, nextPageToken)
