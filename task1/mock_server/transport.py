"""In-process httpx transport for the demo sources: the Pipedrive/Jira adapters issue ordinary HTTP
requests, this transport answers them with the mock service — no server, no sockets, same JSON."""
from __future__ import annotations

import re

import httpx

from . import service

MOCK_CRM_URL = "http://demo-crm.local"
MOCK_JIRA_URL = "http://demo-jira.local"


def _handler(request: httpx.Request) -> httpx.Response:
    path, params = request.url.path, request.url.params
    m = re.fullmatch(r"/v1/([A-Za-z]+)", path)
    if m:
        body = service.crm_list(m.group(1), int(params.get("start", 0)), int(params.get("limit", 100)))
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404, json={"error": "unknown resource"})
    if path == "/rest/api/3/field":
        return httpx.Response(200, json=service.jira_fields())
    if path == "/rest/api/3/search/jql":
        return httpx.Response(200, json=service.jira_search(int(params.get("maxResults", 50)), params.get("nextPageToken")))
    return httpx.Response(404, json={"error": f"no mock route for {path}"})


def mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(_handler)
