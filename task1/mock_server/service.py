"""Mock SaaS behaviour as plain functions, shared by the optional FastAPI routes and the in-process
httpx transport. Response shapes mirror Pipedrive v1 and Jira Cloud v3 closely enough that the
real adapters run against them unchanged."""
from __future__ import annotations

from typing import Any

from .data import build_crm, build_jira

CRM_RESOURCES = {"deals", "persons", "organizations", "stages", "pipelines", "users", "dealFields", "personFields", "organizationFields"}


def crm_list(resource: str, start: int = 0, limit: int = 100) -> dict[str, Any] | None:
    if resource not in CRM_RESOURCES:
        return None
    limit = max(1, min(int(limit), 500))
    start = max(0, int(start))
    rows = build_crm()[resource]
    page = rows[start : start + limit]
    more = start + limit < len(rows)
    return {
        "success": True,
        "data": page,
        "additional_data": {"pagination": {"start": start, "limit": limit, "more_items_in_collection": more, "next_start": start + limit if more else None}},
    }


def jira_fields() -> list[dict[str, Any]]:
    return build_jira()["fields"]


def jira_search(max_results: int = 50, next_page_token: str | None = None) -> dict[str, Any]:
    issues = build_jira()["issues"]
    max_results = max(1, min(int(max_results), 100))
    start = int(next_page_token) if next_page_token else 0
    page = issues[start : start + max_results]
    is_last = start + max_results >= len(issues)
    body: dict[str, Any] = {"issues": page, "isLast": is_last}
    if not is_last:
        body["nextPageToken"] = str(start + max_results)
    return body
