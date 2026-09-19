"""Mock SaaS endpoints. Shapes mirror the real Pipedrive v1 and Jira Cloud v3 APIs closely enough
that the *same* adapters used for real accounts run against them (the translation layer talks REST
to these, it never imports the data module directly)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .data import build_crm, build_jira

router = APIRouter(prefix="/mock", tags=["mock-saas"])

_CRM_RESOURCES = {"deals", "persons", "organizations", "stages", "pipelines", "users", "dealFields", "personFields", "organizationFields"}


@router.get("/crm/v1/{resource}")
def pipedrive_like(resource: str, start: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    if resource not in _CRM_RESOURCES:
        raise HTTPException(404, f"unknown resource {resource}")
    rows = build_crm()[resource]
    page = rows[start : start + limit]
    more = start + limit < len(rows)
    return {
        "success": True,
        "data": page,
        "additional_data": {
            "pagination": {"start": start, "limit": limit, "more_items_in_collection": more, "next_start": start + limit if more else None}
        },
    }


@router.get("/jira/rest/api/3/field")
def jira_fields():
    return build_jira()["fields"]


@router.get("/jira/rest/api/3/search/jql")
def jira_search(jql: str = "", maxResults: int = Query(50, ge=1, le=100), nextPageToken: str | None = None, fields: str = "*all"):
    issues = build_jira()["issues"]
    start = int(nextPageToken) if nextPageToken else 0
    page = issues[start : start + maxResults]
    is_last = start + maxResults >= len(issues)
    body = {"issues": page, "isLast": is_last}
    if not is_last:
        body["nextPageToken"] = str(start + maxResults)
    return body


@router.get("/jira/rest/api/3/myself")
def jira_me():
    return {"displayName": "Treelife Admin", "accountId": "u-admin"}
