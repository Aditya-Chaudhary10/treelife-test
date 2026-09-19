"""HubSpot connector (CRM v3, private-app token). Written against the public API reference; the
mock server does not emulate HubSpot, so exercise this against a real portal.

  * /crm/v3/properties/{object}   -> labels, types, options, hubspotDefined (custom = not hubspotDefined)
  * /crm/v3/objects/{object}      -> records (paged via paging.next.after)
  * /crm/v3/owners                -> owner id -> name
  * /crm/v3/pipelines/deals       -> dealstage id -> label
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import Collection, Connector, ConnectorError, FieldMeta

_OBJECTS = [("deals", "Deals"), ("contacts", "Contacts"), ("companies", "Companies"), ("tickets", "Tickets")]
_BUILTIN_KEEP = {
    "deals": ["dealname", "amount", "dealstage", "pipeline", "closedate", "createdate", "hs_lastmodifieddate",
              "hubspot_owner_id", "hs_priority", "dealtype", "description", "hs_deal_stage_probability", "hs_is_closed_won", "hs_is_closed"],
    "contacts": ["firstname", "lastname", "email", "company", "jobtitle", "lifecyclestage", "hs_lead_status",
                 "hubspot_owner_id", "createdate", "lastmodifieddate", "city", "country"],
    "companies": ["name", "domain", "industry", "city", "country", "hubspot_owner_id", "createdate", "numberofemployees", "annualrevenue", "lifecyclestage"],
    "tickets": ["subject", "content", "hs_pipeline_stage", "hs_ticket_priority", "hubspot_owner_id", "createdate", "closed_date", "hs_ticket_category"],
}
_TYPE_MAP = {"string": "text", "number": "number", "date": "date", "datetime": "date", "enumeration": "enum", "bool": "bool"}


class HubSpotConnector(Connector):
    kind = "hubspot"

    def __init__(self, access_token: str, base_url: str = "https://api.hubapi.com"):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {access_token}"})

    def _get(self, path: str, **params):
        r = self._http.get(f"{self.base_url}{path}", params=params)
        if r.status_code in (401, 403):
            raise ConnectorError("HubSpot rejected the access token (needs crm.objects.*.read scopes)")
        if r.status_code >= 400:
            raise ConnectorError(f"HubSpot {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def load(self, max_records: int = 2000) -> list[Collection]:
        owners = {}
        try:
            owners = {o["id"]: f"{o.get('firstName','')} {o.get('lastName','')}".strip() or o.get("email", o["id"]) for o in self._get("/crm/v3/owners", limit=500).get("results", [])}
        except ConnectorError:
            pass
        stage_labels: dict[str, str] = {}
        try:
            for p in self._get("/crm/v3/pipelines/deals").get("results", []):
                for s in p.get("stages", []):
                    stage_labels[s["id"]] = f"{s['label']}"
        except ConnectorError:
            pass

        collections = []
        for obj, label in _OBJECTS:
            try:
                props = self._get(f"/crm/v3/properties/{obj}").get("results", [])
            except ConnectorError:
                continue
            keep = [p for p in props if (not p.get("hubspotDefined")) or p["name"] in _BUILTIN_KEEP.get(obj, [])]
            names = [p["name"] for p in keep]
            options = {p["name"]: {o["value"]: o["label"] for o in p.get("options", [])} for p in keep if p.get("options")}
            metas = [FieldMeta(name=p["name"], label=p.get("label") or p["name"], type=_TYPE_MAP.get(p.get("type", ""), "unknown"),
                               is_custom=not p.get("hubspotDefined"), options=[o["label"] for o in p.get("options", [])] or None) for p in keep]
            records: list[dict[str, Any]] = []
            after = None
            while len(records) < max_records:
                params: dict[str, Any] = {"limit": 100, "properties": ",".join(names)}
                if after:
                    params["after"] = after
                body = self._get(f"/crm/v3/objects/{obj}", **params)
                for r in body.get("results", []):
                    rec = {"id": r.get("id")}
                    for k, v in (r.get("properties") or {}).items():
                        if k == "hubspot_owner_id" and v:
                            v = owners.get(v, v)
                        elif k in ("dealstage", "hs_pipeline_stage") and v:
                            v = stage_labels.get(v, v)
                        elif k in options and v not in (None, ""):
                            v = options[k].get(v, v)
                        rec[k] = v
                    records.append(rec)
                after = ((body.get("paging") or {}).get("next") or {}).get("after")
                if not after:
                    break
            if not records:
                continue
            # drop fields empty on (almost) every record — keeps the profile readable
            fill = {m.name: sum(1 for r in records if r.get(m.name) not in (None, "")) for m in metas}
            metas = [m for m in metas if fill[m.name] > 0 or m.is_custom]
            metas.insert(0, FieldMeta("id", "ID", "number", False))
            collections.append(Collection(name=obj, label=label, fields=metas, records=records,
                                          notes=[f"{obj}: {len(records)} records. Custom = properties not defined by HubSpot."]))
        if not collections:
            raise ConnectorError("No HubSpot objects readable with this token")
        return collections
