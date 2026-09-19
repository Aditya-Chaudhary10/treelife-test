"""Jira Cloud connector (REST v3). Works unchanged against the built-in mock (`base_url=.../mock/jira`).

Uses the paginated /search/jql endpoint (nextPageToken). Field ids like customfield_10045 are renamed
to their display names from /field; nested objects (status, priority, assignee...) collapse to names.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import Collection, Connector, ConnectorError, FieldMeta

_TYPE_MAP = {
    "string": "text", "number": "number", "date": "date", "datetime": "date", "user": "user",
    "status": "enum", "priority": "enum", "resolution": "enum", "issuetype": "enum", "project": "enum",
    "array": "set", "option": "enum",
}
_SKIP = {"attachment", "comment", "worklog", "issuelinks", "subtasks", "votes", "watches", "progress",
         "aggregateprogress", "timetracking", "environment", "description", "parent", "thumbnail", "issuerestriction"}


class JiraConnector(Connector):
    kind = "jira"

    def __init__(self, base_url: str, email: str = "", api_token: str = "", jql: str = "", transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.jql = jql
        auth = (email, api_token) if email and api_token else None
        self._http = httpx.Client(timeout=30, auth=auth, transport=transport)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "base_url": self.base_url, "jql": self.jql}

    def _get(self, path: str, **params):
        r = self._http.get(f"{self.base_url}{path}", params=params, headers={"Accept": "application/json"})
        if r.status_code in (401, 403):
            raise ConnectorError("Jira rejected the credentials")
        if r.status_code >= 400:
            raise ConnectorError(f"Jira {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def load(self, max_records: int = 2000) -> list[Collection]:
        fdefs = self._get("/rest/api/3/field")
        id_to_name = {f["id"]: f.get("name") or f["id"] for f in fdefs}
        custom_ids = {f["id"] for f in fdefs if f.get("custom")}
        types = {f["id"]: (f.get("schema") or {}).get("type", "unknown") for f in fdefs}

        issues: list[dict] = []
        token: str | None = None
        while len(issues) < max_records:
            params: dict[str, Any] = {"jql": self.jql, "maxResults": 100, "fields": "*all"}
            if token:
                params["nextPageToken"] = token
            body = self._get("/rest/api/3/search/jql", **params)
            issues.extend(body.get("issues") or [])
            token = body.get("nextPageToken")
            if body.get("isLast", True) or not token:
                break

        records = []
        seen: dict[str, FieldMeta] = {}
        for iss in issues:
            rec: dict[str, Any] = {"key": iss.get("key")}
            for fid, val in (iss.get("fields") or {}).items():
                if fid in _SKIP:
                    continue
                if val is None and fid not in id_to_name:
                    continue
                name = id_to_name.get(fid, fid)
                if isinstance(val, dict):
                    val = val.get("name") or val.get("displayName") or val.get("value") or val.get("key")
                elif isinstance(val, list):
                    val = [v.get("name") or v.get("value") or v.get("displayName") if isinstance(v, dict) else v for v in val]
                rec[name] = val
                if name not in seen:
                    seen[name] = FieldMeta(name=name, label=name, type=_TYPE_MAP.get(types.get(fid, ""), "unknown"), is_custom=fid in custom_ids)
            records.append(rec)
        seen.setdefault("key", FieldMeta("key", "Issue key", "text", False))
        notes = [
            f"issues: {len(records)} records fetched via JQL '{self.jql or '(all)'}'.",
            "Jira 'Done' status can hold both completed and abandoned work; the resolution field usually tells them apart.",
        ]
        return [Collection(name="issues", label="Issues / Tickets", fields=list(seen.values()), records=records, notes=notes)]
