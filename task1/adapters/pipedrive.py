"""Pipedrive connector (v1 REST). Works unchanged against the built-in mock (`base_url=.../mock/crm`).

What it does that matters for messy data:
  * custom fields arrive as 40-char hash keys -> we rename them to the label the client sees
  * enum/set fields arrive as option ids -> resolved to labels, sets become lists
  * nested user/person/org objects -> their display name
  * stage_id / pipeline_id -> stage / pipeline names via the /stages and /pipelines endpoints
Nothing here decides what a field *means*; that is the semantic layer's job.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import Collection, Connector, ConnectorError, FieldMeta

_TYPE_MAP = {
    "varchar": "text", "varchar_auto": "text", "text": "text", "address": "text", "phone": "text",
    "int": "number", "double": "number", "monetary": "number",
    "date": "date", "daterange": "date", "time": "text",
    "enum": "enum", "set": "set", "status": "enum",
    "user": "user", "people": "user", "org": "text", "stage": "enum", "pipeline": "enum",
}
_COLLECTIONS = [  # (collection, fields endpoint, human label)
    ("deals", "dealFields", "Deals"),
    ("persons", "personFields", "Persons / Leads"),
    ("organizations", "organizationFields", "Organizations"),
]
_DROP = {"pipeline_id", "stage_id", "creator_user_id", "cc_email", "visible_to", "active", "deleted", "first_char"}


class PipedriveConnector(Connector):
    kind = "pipedrive"

    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.token = api_token
        self._http = httpx.Client(timeout=30)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "base_url": self.base_url}

    # -- raw API -----------------------------------------------------------------------------------
    def _get_all(self, resource: str, max_records: int) -> list[dict]:
        out: list[dict] = []
        start = 0
        while len(out) < max_records:
            r = self._http.get(
                f"{self.base_url}/v1/{resource}",
                params={"api_token": self.token, "start": start, "limit": 500},
            )
            if r.status_code == 401:
                raise ConnectorError("Pipedrive rejected the API token")
            if r.status_code >= 400:
                raise ConnectorError(f"Pipedrive {resource}: HTTP {r.status_code} {r.text[:200]}")
            body = r.json()
            out.extend(body.get("data") or [])
            pag = (body.get("additional_data") or {}).get("pagination") or {}
            if not pag.get("more_items_in_collection"):
                break
            start = pag.get("next_start") or start + 500
        return out[:max_records]

    # -- normalisation -----------------------------------------------------------------------------
    def load(self, max_records: int = 2000) -> list[Collection]:
        stages = {s["id"]: s["name"] for s in self._get_all("stages", 500)}
        pipelines = {p["id"]: p["name"] for p in self._get_all("pipelines", 100)}
        collections = []
        for name, fields_ep, label in _COLLECTIONS:
            fdefs = self._get_all(fields_ep, 1000)
            raw = self._get_all(name, max_records)
            metas, key_to_label, options = self._field_metas(fdefs)
            records = [self._flatten(rec, key_to_label, options, stages, pipelines, fdefs) for rec in raw]
            if name == "deals":
                metas.append(FieldMeta("stage", "Stage", "enum", False, list(stages.values())))
                metas.append(FieldMeta("pipeline", "Pipeline", "enum", False, list(pipelines.values())))
            present = {k for r in records for k in r}
            metas = [m for m in metas if m.name in present]
            notes = [
                f"{name}: {len(records)} records fetched.",
                "Fields marked custom were created by the client, not shipped with the tool.",
            ]
            if name == "deals":
                notes.append("Pipedrive has a built-in status field (open/won/lost) AND a stage field; teams often use only one of them.")
            collections.append(Collection(name=name, label=label, fields=metas, records=records, notes=notes))
        return collections

    @staticmethod
    def _field_metas(fdefs: list[dict]):
        metas: list[FieldMeta] = []
        key_to_label: dict[str, str] = {}
        options: dict[str, dict[Any, str]] = {}
        for f in fdefs:
            key = f["key"]
            if key in _DROP:
                continue
            custom = bool(f.get("edit_flag")) and len(key) == 40
            label = f.get("name") or key
            # keep built-in keys as-is (they're already readable), rename hashes to their label
            flat_name = label if custom else key
            key_to_label[key] = flat_name
            opts = f.get("options") or []
            if opts:
                options[key] = {o.get("id"): o.get("label") for o in opts}
            metas.append(FieldMeta(
                name=flat_name, label=label, type=_TYPE_MAP.get(f.get("field_type", ""), "unknown"),
                is_custom=custom, options=[o.get("label") for o in opts] or None,
            ))
        return metas, key_to_label, options

    @staticmethod
    def _flatten(rec: dict, key_to_label, options, stages, pipelines, fdefs) -> dict[str, Any]:
        out: dict[str, Any] = {}
        types = {f["key"]: f.get("field_type") for f in fdefs}
        for key, val in rec.items():
            if key in _DROP and key not in ("stage_id", "pipeline_id"):
                continue
            if key == "stage_id":
                out["stage"] = stages.get(val, val)
                continue
            if key == "pipeline_id":
                out["pipeline"] = pipelines.get(val, val)
                continue
            name = key_to_label.get(key)
            if name is None:
                continue  # field not declared -> ignore (keeps profile focused)
            ftype = types.get(key)
            if isinstance(val, dict):
                val = val.get("name") or val.get("value")
            elif isinstance(val, list):
                val = [v.get("value") if isinstance(v, dict) else v for v in val]
                if ftype in ("phone", "varchar", "email") and val:
                    val = val[0]
            if key in options and val not in (None, ""):
                if ftype == "set":
                    ids = [v.strip() for v in str(val).split(",") if v.strip()]
                    val = [options[key].get(_maybe_int(i), i) for i in ids]
                else:
                    val = options[key].get(_maybe_int(val), options[key].get(val, val))
            elif ftype == "set" and val in (None, ""):
                val = []
            out[name] = val
        return out


def _maybe_int(v: Any) -> Any:
    try:
        return int(v)
    except (TypeError, ValueError):
        return v
