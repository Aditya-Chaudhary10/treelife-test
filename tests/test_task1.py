"""Task 1 — the deterministic core: discovery signals, alias clustering, binding, execution, zero-diagnosis."""
from __future__ import annotations

import pytest

from task1 import rules
from task1.adapters.base import Collection, FieldMeta
from task1.adapters.pipedrive import PipedriveConnector
from task1.discovery import profile_collection, profiles_to_text
from task1.executor import execute
from task1.explain import build_explanation
from task1.mock_server.data import OWNER_VARIANTS, build_crm, build_jira
from task1.planner import build_plan
from task1.semantic_map import attach_people, cluster_names


def deals_collection() -> Collection:
    crm = build_crm()
    metas, key_to_label, options = PipedriveConnector._field_metas(crm["dealFields"])
    stages = {s["id"]: s["name"] for s in crm["stages"]}
    pipelines = {p["id"]: p["name"] for p in crm["pipelines"]}
    records = [PipedriveConnector._flatten(r, key_to_label, options, stages, pipelines, crm["dealFields"]) for r in crm["deals"]]
    metas.append(FieldMeta("stage", "Stage", "enum", False, list(stages.values())))
    return Collection("deals", "Deals", metas, records)


# a hand-written semantic map: what the LLM step is expected to produce for the mock CRM
FIXTURE_MAP = {
    "collections": {
        "deals": {
            "description": "Sales deals; owner hand-typed, lost deals parked in Dead Leads",
            "record_nouns": ["deal", "opportunity"],
            "concepts": {
                "owner": {"field": "Assigned To", "kind": "person", "confidence": 0.9, "evidence": "custom text field, inconsistent spelling"},
                "status": {"field": "status", "kind": "category", "confidence": 0.9, "evidence": "Lost never used; Dead Leads stage",
                           "value_map": {"open": {"all": [{"field": "status", "in": ["Open"]}, {"field": "stage", "not_in": ["Dead Leads"]}]},
                                         "won": ["Won"], "lost": {"field": "stage", "in": ["Dead Leads"]}}},
                "priority": {"field": "label", "kind": "category", "confidence": 0.8, "evidence": "labels", "value_map": {"high": ["hot 🔥", "urgent"], "low": ["low priority"]}},
                "amount": {"field": "value", "kind": "number", "confidence": 1.0, "evidence": "monetary"},
                "created_at": {"field": "add_time", "kind": "date", "confidence": 1.0, "evidence": ""},
            },
            "missing_concepts": {"region": "no field resembles a region or territory"},
            "notes": [],
        }
    },
    "source_kind": "pipedrive",
}


@pytest.fixture(scope="module")
def ctx():
    col = deals_collection()
    smap = attach_people({k: (dict(v) if isinstance(v, dict) else v) for k, v in FIXTURE_MAP.items()}, [col])
    profiles = {"deals": profile_collection(col).as_dict()}
    return col, smap, profiles


def ask(ctx, ir):
    col, smap, profiles = ctx
    ir.setdefault("operation", "count")
    ir.setdefault("collection", "deals")
    ir.setdefault("interpretation", "")
    plan = build_plan(ir, smap, profiles)
    result = execute(plan, col.records) if plan.executable else None
    expl = build_explanation("q", plan, result, smap, col.records)
    return plan, result, expl


# ----------------------------------------------------------------------------- data + discovery
def test_mock_data_is_messy_by_design():
    crm = build_crm()
    assert all(d["status"] != "lost" for d in crm["deals"]), "nothing is ever marked lost"
    assert all(d["user_id"]["name"] == "Treelife Admin" for d in crm["deals"]), "official owner is a shared login"
    assert len(build_jira()["issues"]) == 60


def test_discovery_signals(ctx):
    col, _, profiles = ctx
    f = {x["name"]: x for x in profiles["deals"]["fields"]}
    assert "CONSTANT" in f["user_id"]["looks_like"]
    assert f["Assigned To"]["is_custom"] and "name_like" in f["Assigned To"]["looks_like"] and "inconsistent_spelling" in f["Assigned To"]["looks_like"]
    assert "Lost" in (f["status"]["unused_options"] or [])
    text = profiles_to_text([profile_collection(col)])
    assert "NEVER USED" in text and "CONSTANT" in text


def test_cluster_names_merges_typos_initials_and_nicknames():
    groups = cluster_names(OWNER_VARIANTS["garima"] + OWNER_VARIANTS["ishan"] + OWNER_VARIANTS["rahul"])
    by_member = {m: i for i, g in enumerate(groups) for m in g}
    assert len({by_member[v.strip()] for v in OWNER_VARIANTS["garima"]}) == 1  # Garmia, G. Sharma, garima sharma -> one person
    assert len({by_member[v.strip()] for v in OWNER_VARIANTS["ishan"]}) == 1   # IK, Ishaan, ishan k -> one person
    assert by_member["Garima"] != by_member["Rahul"]
    assert len(groups) == 3


# ----------------------------------------------------------------------------- binding + execution
def test_open_deals_for_garima_is_14(ctx):
    plan, result, expl = ask(ctx, {"filters": [{"concept": "owner", "op": "eq", "value": "Garima"}, {"concept": "status", "op": "eq", "value": "open"}]})
    assert plan.executable and result.value == 14
    assert expl["answer_type"] == "answer" and "14" in expl["answer"]
    owner = next(b for b in plan.filters if b.concept == "owner")
    assert owner.canonical == "Garima Sharma" and "Garmia" in owner.raw_values
    assert any("Dead Leads" in s for s in expl["steps"]), "explanation must surface the hidden meaning"


def test_typo_and_synonym_resolution(ctx):
    plan, result, _ = ask(ctx, {"filters": [{"concept": "owner", "op": "eq", "value": "Garmia"}, {"concept": "status", "op": "eq", "value": "active"}]})
    assert result.value == 14
    assert "interpreted 'Garmia' as Garima Sharma" in next(b for b in plan.filters if b.concept == "owner").note


def test_lost_means_dead_leads_stage(ctx):
    plan, result, _ = ask(ctx, {"operation": "list", "filters": [{"concept": "status", "op": "eq", "value": "lost"}]})
    assert result.count == 16 and all(r["stage"] == "Dead Leads" for r in result.matched)


def test_group_sum_uses_canonical_people(ctx):
    plan, result, _ = ask(ctx, {"operation": "group_sum", "metric_concept": "amount", "group_by": "owner", "filters": [{"concept": "status", "op": "eq", "value": "open"}]})
    keys = [k for k, _ in result.groups]
    assert "Garima Sharma" in keys and "garima" not in keys


def test_missing_concept_is_unanswerable_not_zero(ctx):
    plan, result, expl = ask(ctx, {"filters": [{"concept": "region", "op": "eq", "value": "London"}]})
    assert not plan.executable and result is None
    assert expl["answer_type"] == "unanswerable" and "region" in expl["answer"]


def test_zero_result_gets_a_diagnosis(ctx):
    plan, result, expl = ask(ctx, {"filters": [{"concept": "owner", "op": "is_empty", "value": None}, {"concept": "status", "op": "eq", "value": "won"}]})
    assert result.value == 0
    assert expl["answer_type"] == "empty_with_reason" and expl["zero_diagnosis"]["kind"] == "combination_empty"
    assert expl["zero_diagnosis"]["pool_size"] > 0


def test_unknown_person_suggests_names(ctx):
    plan, result, expl = ask(ctx, {"filters": [{"concept": "owner", "op": "eq", "value": "Zebediah"}]})
    assert not plan.executable and expl["answer_type"] == "unanswerable"
    assert expl["problems"] and "Did you mean" in expl["problems"][0]


def test_rules_language():
    rec = {"status": "Open", "stage": "Dead Leads", "tags": ["hot 🔥"]}
    assert rules.evaluate(rec, {"field": "stage", "in": ["dead leads"]})
    assert not rules.evaluate(rec, {"all": [{"field": "status", "in": ["Open"]}, {"field": "stage", "not_in": ["Dead Leads"]}]})
    assert rules.evaluate(rec, {"field": "tags", "in": ["HOT 🔥"]})
    assert "∉" in rules.describe({"field": "stage", "not_in": ["Dead Leads"]})


def test_demo_sources_load_through_in_process_transport():
    """The real Pipedrive/Jira adapters talk HTTP to the demo transport — no server required."""
    from task1.adapters.registry import make_connector

    crm = {c.name: c for c in make_connector("mock_crm", {}).load()}
    assert set(crm) == {"deals", "persons", "organizations"} and len(crm["deals"].records) == 71
    assert crm["deals"].records[0]["stage"] in {"New Lead", "Contacted", "Proposal Sent", "Negotiation", "Closed Won", "Dead Leads"}
    jira = make_connector("mock_jira", {}).load()
    assert jira[0].name == "issues" and len(jira[0].records) == 60 and "Client" in jira[0].records[0]
