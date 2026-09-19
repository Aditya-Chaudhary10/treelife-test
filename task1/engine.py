"""Orchestration: connect -> discover -> map (cached) -> ask -> explain."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from shared import llm
from shared.config import settings

from .adapters.base import Collection, Connector
from .adapters.registry import make_connector
from .discovery import CollectionProfile, profile_collection, schema_fingerprint
from .executor import execute
from .explain import build_explanation
from .intent import parse_intent
from .planner import build_plan
from .semantic_map import attach_people, build_semantic_map

MAPS_DIR = settings.data_dir / "task1" / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Connection:
    id: str
    source: str
    connector: Connector
    collections: list[Collection]
    profiles: list[CollectionProfile]
    semantic_map: dict[str, Any]
    fingerprint: str
    created_at: float = field(default_factory=time.time)
    map_from_cache: bool = False
    discovery_usage: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "connector": self.connector.describe(),
            "fingerprint": self.fingerprint,
            "map_from_cache": self.map_from_cache,
            "collections": [{"name": c.name, "label": c.label, "records": len(c.records), "fields": len(c.fields)} for c in self.collections],
            "discovery_usage": self.discovery_usage,
        }

    def profiles_dict(self) -> dict[str, Any]:
        return {p.name: p.as_dict() for p in self.profiles}


class Engine:
    def __init__(self) -> None:
        self.connections: dict[str, Connection] = {}

    # ------------------------------------------------------------------ connect
    def connect(self, source: str, config: dict[str, Any] | None, self_base_url: str | None = None, force_remap: bool = False) -> Connection:
        connector = make_connector(source, config, self_base_url)
        collections = connector.load()
        profiles = [profile_collection(c) for c in collections]
        fp = schema_fingerprint(collections)
        cache_file = MAPS_DIR / f"{re.sub(r'[^a-z0-9]+', '_', source.lower())}_{fp}.json"
        usage: dict[str, Any] = {}
        from_cache = False
        if cache_file.exists() and not force_remap:
            semantic_map = json.loads(cache_file.read_text(encoding="utf-8"))
            from_cache = True
        else:
            with llm.track_usage() as u:
                semantic_map = build_semantic_map(profiles, connector.kind)
                semantic_map = attach_people(semantic_map, collections)
            usage = u.as_dict()
            cache_file.write_text(json.dumps(semantic_map, indent=1, ensure_ascii=False), encoding="utf-8")
        conn = Connection(
            id=uuid.uuid4().hex[:10], source=source, connector=connector, collections=collections, profiles=profiles,
            semantic_map=semantic_map, fingerprint=fp, map_from_cache=from_cache, discovery_usage=usage,
        )
        self.connections[conn.id] = conn
        return conn

    def get(self, conn_id: str) -> Connection:
        if conn_id not in self.connections:
            raise KeyError(conn_id)
        return self.connections[conn_id]

    def override(self, conn_id: str, collection: str, concept: str, spec: dict[str, Any] | None) -> dict[str, Any]:
        """Human-in-the-loop correction: set or delete a concept mapping, then re-cache."""
        conn = self.get(conn_id)
        cmap = conn.semantic_map["collections"].setdefault(collection, {"concepts": {}, "record_nouns": [collection], "missing_concepts": {}, "notes": []})
        if spec is None:
            cmap["concepts"].pop(concept, None)
        else:
            spec.setdefault("kind", "text")
            spec.setdefault("confidence", 1.0)
            spec.setdefault("evidence", "set manually by the user")
            cmap["concepts"][concept] = spec
            cmap.get("missing_concepts", {}).pop(concept, None)
        conn.semantic_map = attach_people(conn.semantic_map, conn.collections)
        cache_file = MAPS_DIR / f"{re.sub(r'[^a-z0-9]+', '_', conn.source.lower())}_{conn.fingerprint}.json"
        cache_file.write_text(json.dumps(conn.semantic_map, indent=1, ensure_ascii=False), encoding="utf-8")
        return conn.semantic_map

    # ------------------------------------------------------------------ ask
    def ask(self, conn_id: str, question: str) -> dict[str, Any]:
        conn = self.get(conn_id)
        t0 = time.time()
        with llm.track_usage() as usage:
            ir = parse_intent(question, conn.semantic_map, date.today().isoformat())
            plan = build_plan(ir, conn.semantic_map, conn.profiles_dict())
            plan.confidence = float(ir.get("confidence") or 0.7)  # type: ignore[attr-defined]
            records = next((c.records for c in conn.collections if c.name == plan.collection), [])
            result = execute(plan, records) if plan.executable else None
            explanation = build_explanation(question, plan, result, conn.semantic_map, records)
        response = {
            "question": question,
            "connection_id": conn_id,
            **explanation,
            "result": result.as_dict() if result else None,
            "plan": plan.as_dict(),
            "intent": ir,
            "usage": usage.as_dict(),
            "elapsed_s": round(time.time() - t0, 2),
        }
        conn.history.append({"question": question, "answer": explanation["answer"], "answer_type": explanation["answer_type"]})
        return response


engine = Engine()
