"""Source registry: name -> how to build a connector from a small config dict."""
from __future__ import annotations

from typing import Any

from shared.config import settings
from task1.mock_server.transport import MOCK_CRM_URL, MOCK_JIRA_URL, mock_transport

from .base import Connector, ConnectorError
from .files import FilesConnector
from .hubspot import HubSpotConnector
from .jira import JiraConnector
from .pipedrive import PipedriveConnector

SOURCES: dict[str, dict[str, Any]] = {
    "mock_crm": {
        "label": "Demo CRM (messy, Pipedrive-shaped, served by this app)",
        "kind": "pipedrive",
        "fields": [],
        "description": "Shared login, hand-typed 'Assigned To', 'Dead Leads' stage instead of status=lost, priority in labels.",
    },
    "mock_jira": {
        "label": "Demo project tool (Jira-shaped, served by this app)",
        "kind": "jira",
        "fields": [],
        "description": "Proper assignee/priority fields, but 'Done' also holds abandoned tickets (resolution = Won't Do).",
    },
    "pipedrive": {
        "label": "Pipedrive (your account)",
        "kind": "pipedrive",
        "fields": [{"name": "api_token", "label": "API token", "secret": True}, {"name": "base_url", "label": "Base URL", "default": "https://api.pipedrive.com"}],
        "description": "Settings → Personal preferences → API.",
    },
    "hubspot": {
        "label": "HubSpot (your portal)",
        "kind": "hubspot",
        "fields": [{"name": "access_token", "label": "Private app access token", "secret": True}],
        "description": "Needs crm.objects.deals/contacts/companies read scopes.",
    },
    "jira": {
        "label": "Jira Cloud (your site)",
        "kind": "jira",
        "fields": [{"name": "base_url", "label": "Site URL", "default": "https://your-site.atlassian.net"},
                   {"name": "email", "label": "Email"}, {"name": "api_token", "label": "API token", "secret": True},
                   {"name": "jql", "label": "JQL filter (optional)", "default": ""}],
        "description": "Uses /rest/api/3/search/jql.",
    },
    "files": {
        "label": "CSV / JSON / XLSX export",
        "kind": "files",
        "fields": [{"name": "path", "label": "Folder or file path on the server"}],
        "description": "Any tool: export it and point here.",
    },
}


def make_connector(source: str, config: dict[str, Any] | None, self_base_url: str | None = None) -> Connector:
    cfg = {k: v for k, v in (config or {}).items() if v not in (None, "")}
    if source == "mock_crm":  # demo sources: the same adapters, answered by an in-process transport (no server needed)
        return PipedriveConnector(base_url=MOCK_CRM_URL, api_token="demo", transport=mock_transport())
    if source == "mock_jira":
        return JiraConnector(base_url=MOCK_JIRA_URL, transport=mock_transport())
    if source == "pipedrive":
        token = cfg.get("api_token") or settings.pipedrive_token
        if not token:
            raise ConnectorError("Pipedrive needs api_token")
        return PipedriveConnector(base_url=cfg.get("base_url") or settings.pipedrive_base_url, api_token=token)
    if source == "hubspot":
        token = cfg.get("access_token") or settings.hubspot_token
        if not token:
            raise ConnectorError("HubSpot needs access_token")
        return HubSpotConnector(access_token=token)
    if source == "jira":
        base = cfg.get("base_url") or settings.jira_base_url
        if not base:
            raise ConnectorError("Jira needs base_url")
        return JiraConnector(base_url=base, email=cfg.get("email") or settings.jira_email, api_token=cfg.get("api_token") or settings.jira_token, jql=cfg.get("jql", ""))
    if source == "files":
        if not cfg.get("path"):
            raise ConnectorError("files source needs a path")
        return FilesConnector(cfg["path"])
    raise ConnectorError(f"unknown source '{source}'")
