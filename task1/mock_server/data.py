"""Deterministic, deliberately messy demo data.

Two "clients" that bend their tools the way real teams do:

  * mock CRM  (Pipedrive-shaped) — a team sharing ONE login.
      - the official owner field is "Treelife Admin" on every deal (useless)
      - the real owner is hand-typed in a custom text field "Assigned To" (typos, nicknames, initials)
      - nothing is ever marked status=lost; abandoned deals sit in a stage called "Dead Leads" with status=open
      - priority is not a field at all; it lives in labels ("hot", "urgent", "low priority")
      - leads (persons) carry their owner in a custom field called "Lead Owner"
  * mock Jira — the opposite habits.
      - assignee + priority are used properly (built-in fields)
      - but "Done" is also used for abandoned tickets, distinguished only by resolution = "Won't Do"
      - the client name is a hand-typed custom field with variants

The numbers are chosen so the brief's example holds: Garima has exactly 14 active deals.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from functools import lru_cache

TODAY = date(2026, 9, 19)

ADMIN_USER = {"id": 1, "name": "Treelife Admin", "email": "crm@treelife-demo.example", "active_flag": True}

STAGES = [
    {"id": 1, "name": "New Lead", "pipeline_id": 1, "order_nr": 1},
    {"id": 2, "name": "Contacted", "pipeline_id": 1, "order_nr": 2},
    {"id": 3, "name": "Proposal Sent", "pipeline_id": 1, "order_nr": 3},
    {"id": 4, "name": "Negotiation", "pipeline_id": 1, "order_nr": 4},
    {"id": 5, "name": "Closed Won", "pipeline_id": 1, "order_nr": 5},
    {"id": 6, "name": "Dead Leads", "pipeline_id": 1, "order_nr": 6},
]
PIPELINES = [{"id": 1, "name": "Sales Pipeline", "active": True}]

ASSIGNED_TO_KEY = "4f1a9c2e7b3d5f6a8c9e1b2d3f4a5c6e7b8d9f0a"  # Pipedrive custom keys are 40-char hashes
LEAD_SOURCE_KEY = "9b2c4d6e8f0a1b3c5d7e9f1a2b4c6d8e0f1a3b5c"
LEAD_OWNER_KEY = "c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5"
LEAD_STATUS_KEY = "e2f4a6b8c0d2e4f6a8b0c2d4e6f8a0b2c4d6e8f0"

LABEL_OPTIONS = [
    {"id": 1, "label": "hot 🔥", "color": "red"},
    {"id": 2, "label": "urgent", "color": "orange"},
    {"id": 3, "label": "low priority", "color": "gray"},
    {"id": 4, "label": "referral", "color": "green"},
    {"id": 5, "label": "enterprise", "color": "purple"},
]

DEAL_FIELDS = [
    {"id": 1, "key": "id", "name": "ID", "field_type": "int", "edit_flag": False},
    {"id": 2, "key": "title", "name": "Title", "field_type": "varchar", "edit_flag": False},
    {"id": 3, "key": "value", "name": "Value", "field_type": "monetary", "edit_flag": False},
    {"id": 4, "key": "currency", "name": "Currency", "field_type": "varchar", "edit_flag": False},
    {"id": 5, "key": "user_id", "name": "Owner", "field_type": "user", "edit_flag": False},
    {"id": 6, "key": "person_id", "name": "Contact person", "field_type": "people", "edit_flag": False},
    {"id": 7, "key": "org_id", "name": "Organization", "field_type": "org", "edit_flag": False},
    {"id": 8, "key": "stage_id", "name": "Stage", "field_type": "stage", "edit_flag": False},
    {"id": 9, "key": "pipeline_id", "name": "Pipeline", "field_type": "pipeline", "edit_flag": False},
    {"id": 10, "key": "status", "name": "Status", "field_type": "status", "edit_flag": False,
     "options": [{"id": "open", "label": "Open"}, {"id": "won", "label": "Won"}, {"id": "lost", "label": "Lost"}, {"id": "deleted", "label": "Deleted"}]},
    {"id": 11, "key": "add_time", "name": "Deal created", "field_type": "date", "edit_flag": False},
    {"id": 12, "key": "update_time", "name": "Update time", "field_type": "date", "edit_flag": False},
    {"id": 13, "key": "expected_close_date", "name": "Expected close date", "field_type": "date", "edit_flag": False},
    {"id": 14, "key": "won_time", "name": "Won time", "field_type": "date", "edit_flag": False},
    {"id": 15, "key": "lost_time", "name": "Lost time", "field_type": "date", "edit_flag": False},
    {"id": 16, "key": "lost_reason", "name": "Lost reason", "field_type": "varchar", "edit_flag": False},
    {"id": 17, "key": "probability", "name": "Probability", "field_type": "double", "edit_flag": False},
    {"id": 18, "key": "label", "name": "Label", "field_type": "set", "edit_flag": False, "options": LABEL_OPTIONS},
    {"id": 19, "key": ASSIGNED_TO_KEY, "name": "Assigned To", "field_type": "varchar", "edit_flag": True},
    {"id": 20, "key": LEAD_SOURCE_KEY, "name": "Lead Source", "field_type": "enum", "edit_flag": True,
     "options": [{"id": 71, "label": "Referral"}, {"id": 72, "label": "Inbound"}, {"id": 73, "label": "Outbound"}, {"id": 74, "label": "Event"}]},
]

PERSON_FIELDS = [
    {"id": 1, "key": "id", "name": "ID", "field_type": "int", "edit_flag": False},
    {"id": 2, "key": "name", "name": "Name", "field_type": "varchar", "edit_flag": False},
    {"id": 3, "key": "email", "name": "Email", "field_type": "varchar", "edit_flag": False},
    {"id": 4, "key": "phone", "name": "Phone", "field_type": "phone", "edit_flag": False},
    {"id": 5, "key": "org_id", "name": "Organization", "field_type": "org", "edit_flag": False},
    {"id": 6, "key": "owner_id", "name": "Owner", "field_type": "user", "edit_flag": False},
    {"id": 7, "key": "add_time", "name": "Person created", "field_type": "date", "edit_flag": False},
    {"id": 8, "key": "open_deals_count", "name": "Open deals", "field_type": "int", "edit_flag": False},
    {"id": 9, "key": LEAD_OWNER_KEY, "name": "Lead Owner", "field_type": "varchar", "edit_flag": True},
    {"id": 10, "key": LEAD_STATUS_KEY, "name": "Lead Status", "field_type": "enum", "edit_flag": True,
     "options": [{"id": 81, "label": "New"}, {"id": 82, "label": "Working"}, {"id": 83, "label": "Qualified"}, {"id": 84, "label": "Unqualified"}, {"id": 85, "label": "Converted"}]},
]

ORG_FIELDS = [
    {"id": 1, "key": "id", "name": "ID", "field_type": "int", "edit_flag": False},
    {"id": 2, "key": "name", "name": "Name", "field_type": "varchar", "edit_flag": False},
    {"id": 3, "key": "address", "name": "Address", "field_type": "address", "edit_flag": False},
    {"id": 4, "key": "owner_id", "name": "Owner", "field_type": "user", "edit_flag": False},
    {"id": 5, "key": "people_count", "name": "People", "field_type": "int", "edit_flag": False},
    {"id": 6, "key": "add_time", "name": "Organization created", "field_type": "date", "edit_flag": False},
]

ORGS = [
    "Acme Corp", "Bluebird Retail", "Cedar Logistics", "Delta Pharma", "Evergreen Foods", "Falcon Media",
    "Granite Builders", "Horizon Travel", "Indigo Textiles", "Juniper Health", "Kestrel Finance", "Lotus Education",
    "Meridian Energy", "Nimbus Software", "Orchid Hotels", "Pinnacle Motors", "Quartz Analytics", "Riverstone Realty",
    "Sapphire Jewels", "Tundra Outdoors",
]
CITIES = ["Mumbai", "Bengaluru", "Delhi", "Pune", "Hyderabad", "Chennai", "Gurugram", "Ahmedabad"]
CONTACTS = [
    "Anita Desai", "Vikram Rao", "Sneha Iyer", "Arjun Bhatt", "Meera Pillai", "Karan Malhotra", "Divya Menon",
    "Rohan Sethi", "Pooja Kulkarni", "Nikhil Jain", "Ayesha Khan", "Siddharth Bose", "Tanvi Joshi", "Manish Verma",
    "Ritika Agarwal", "Aditya Saxena", "Neha Chopra", "Varun Reddy", "Kavya Nambiar", "Harsh Patel", "Shreya Das",
    "Abhishek Tiwari", "Ishita Roy", "Gaurav Mishra", "Nandini Kapoor", "Yash Trivedi", "Simran Gill", "Dev Anand",
    "Lakshmi Krishnan", "Farhan Sheikh",
]
PRODUCTS = [
    "Website revamp", "CRM migration", "Annual support", "Mobile app MVP", "Data pipeline", "SEO retainer",
    "Cloud migration", "Security audit", "ERP integration", "Analytics dashboard",
]

# Raw "Assigned To" spellings per real person — the whole point of the exercise.
OWNER_VARIANTS = {
    "garima": ["Garima", "garima", "Garima S.", "G. Sharma", "Garima Sharma", "Garmia", "garima sharma "],
    "ishan": ["Ishan", "ishan k", "Ishaan", "Ishan Kapoor", "IK", "Ishan K."],
    "rahul": ["Rahul", "rahul m", "Rahul Mehta", "Rahul M"],
    "priya": ["Priya", "priya nair", "Priya N.", "Priya Nair"],
    "": [""],
}
# (owner, active, won, dead)  -> active means stages 1-4 with status=open
OWNER_MIX = [
    ("garima", 14, 4, 3),
    ("ishan", 9, 3, 5),
    ("rahul", 11, 2, 2),
    ("priya", 6, 1, 4),
    ("", 5, 0, 2),
]


def _ts(d: date, hour: int = 10) -> str:
    return datetime(d.year, d.month, d.day, hour, 15, 0).strftime("%Y-%m-%d %H:%M:%S")


@lru_cache(maxsize=1)
def build_crm() -> dict:
    rnd = random.Random(7)
    orgs = []
    for i, name in enumerate(ORGS, start=1):
        orgs.append({
            "id": i, "name": name, "address": f"{CITIES[i % len(CITIES)]}, India",
            "owner_id": dict(ADMIN_USER), "people_count": 1 + i % 3,
            "add_time": _ts(TODAY - timedelta(days=300 - i * 9)),
        })

    persons = []
    lead_owner_cycle = {"garima": 0, "ishan": 0, "rahul": 0, "priya": 0}
    lead_owner_plan = ["ishan"] * 9 + ["garima"] * 8 + ["rahul"] * 7 + ["priya"] * 4 + [""] * 2
    for i, cname in enumerate(CONTACTS, start=1):
        org = orgs[(i - 1) % len(orgs)]
        owner = lead_owner_plan[i - 1]
        variants = OWNER_VARIANTS[owner]
        if owner:
            raw_owner = variants[lead_owner_cycle[owner] % len(variants)]
            lead_owner_cycle[owner] += 1
        else:
            raw_owner = ""
        status_opt = PERSON_FIELDS[9]["options"][i % 5]["id"]
        persons.append({
            "id": i, "name": cname,
            "email": [{"value": cname.lower().replace(" ", ".") + "@" + org["name"].lower().replace(" ", "") + ".example", "primary": True}],
            "phone": [{"value": f"+91 98{rnd.randint(10000000, 99999999)}", "primary": True}],
            "org_id": {"value": org["id"], "name": org["name"]},
            "owner_id": dict(ADMIN_USER),
            "add_time": _ts(TODAY - timedelta(days=260 - i * 7)),
            "open_deals_count": 0,
            LEAD_OWNER_KEY: raw_owner,
            LEAD_STATUS_KEY: status_opt,
        })

    deals = []
    deal_id = 100
    variant_cycle = {k: 0 for k in OWNER_VARIANTS}
    label_plan = ["1", "2", "3", "1,5", "4", "", ""]
    for owner, n_active, n_won, n_dead in OWNER_MIX:
        buckets = [("active", n_active), ("won", n_won), ("dead", n_dead)]
        for bucket, n in buckets:
            for j in range(n):
                deal_id += 1
                variants = OWNER_VARIANTS[owner]
                raw_owner = variants[variant_cycle[owner] % len(variants)]
                variant_cycle[owner] += 1
                org = orgs[deal_id % len(orgs)]
                person = persons[deal_id % len(persons)]
                created = TODAY - timedelta(days=20 + (deal_id * 37) % 240)
                if bucket == "active":
                    stage_id = 1 + j % 4
                    status = "open"
                    won_time = lost_time = None
                    lost_reason = None
                elif bucket == "won":
                    stage_id = 5
                    status = "won"
                    won_time = _ts(created + timedelta(days=25 + j * 3))
                    lost_time = None
                    lost_reason = None
                else:  # parked in "Dead Leads" but never marked lost
                    stage_id = 6
                    status = "open"
                    won_time = lost_time = None
                    lost_reason = ["no response", "went with competitor", None, "budget frozen"][j % 4]
                deals.append({
                    "id": deal_id,
                    "title": f"{org['name']} - {PRODUCTS[deal_id % len(PRODUCTS)]}",
                    "value": rnd.choice([5000, 12000, 18000, 25000, 40000, 60000, 85000, 120000, 150000, 250000]),
                    "currency": "INR",
                    "status": status,
                    "stage_id": stage_id,
                    "pipeline_id": 1,
                    "user_id": dict(ADMIN_USER),
                    "person_id": {"value": person["id"], "name": person["name"]},
                    "org_id": {"value": org["id"], "name": org["name"]},
                    "add_time": _ts(created),
                    "update_time": _ts(created + timedelta(days=(deal_id * 11) % 30)),
                    "expected_close_date": (created + timedelta(days=45 + (deal_id * 13) % 90)).isoformat(),
                    "won_time": won_time,
                    "lost_time": lost_time,
                    "lost_reason": lost_reason,
                    "probability": None,
                    "label": label_plan[deal_id % len(label_plan)],
                    ASSIGNED_TO_KEY: raw_owner,
                    LEAD_SOURCE_KEY: (71 + deal_id % 4) if deal_id % 3 == 0 else None,
                })
    for p in persons:
        p["open_deals_count"] = sum(1 for d in deals if d["person_id"]["value"] == p["id"] and d["status"] == "open")

    return {
        "users": [ADMIN_USER],
        "pipelines": PIPELINES,
        "stages": STAGES,
        "dealFields": DEAL_FIELDS,
        "deals": deals,
        "personFields": PERSON_FIELDS,
        "persons": persons,
        "organizationFields": ORG_FIELDS,
        "organizations": orgs,
    }


# ----------------------------------------------------------------------------- Jira-shaped project tool
JIRA_PEOPLE = {
    "ishan": {"displayName": "Ishan Kapoor", "emailAddress": "ishan@treelife-demo.example", "accountId": "u-ishan"},
    "garima": {"displayName": "Garima Sharma", "emailAddress": "garima@treelife-demo.example", "accountId": "u-garima"},
    "rahul": {"displayName": "Rahul Mehta", "emailAddress": "rahul@treelife-demo.example", "accountId": "u-rahul"},
    "priya": {"displayName": "Priya Nair", "emailAddress": "priya@treelife-demo.example", "accountId": "u-priya"},
}
JIRA_FIELDS = [
    {"id": "summary", "key": "summary", "name": "Summary", "custom": False, "schema": {"type": "string"}},
    {"id": "status", "key": "status", "name": "Status", "custom": False, "schema": {"type": "status"}},
    {"id": "resolution", "key": "resolution", "name": "Resolution", "custom": False, "schema": {"type": "resolution"}},
    {"id": "priority", "key": "priority", "name": "Priority", "custom": False, "schema": {"type": "priority"}},
    {"id": "assignee", "key": "assignee", "name": "Assignee", "custom": False, "schema": {"type": "user"}},
    {"id": "reporter", "key": "reporter", "name": "Reporter", "custom": False, "schema": {"type": "user"}},
    {"id": "labels", "key": "labels", "name": "Labels", "custom": False, "schema": {"type": "array", "items": "string"}},
    {"id": "components", "key": "components", "name": "Components", "custom": False, "schema": {"type": "array", "items": "component"}},
    {"id": "issuetype", "key": "issuetype", "name": "Issue Type", "custom": False, "schema": {"type": "issuetype"}},
    {"id": "project", "key": "project", "name": "Project", "custom": False, "schema": {"type": "project"}},
    {"id": "created", "key": "created", "name": "Created", "custom": False, "schema": {"type": "datetime"}},
    {"id": "updated", "key": "updated", "name": "Updated", "custom": False, "schema": {"type": "datetime"}},
    {"id": "resolutiondate", "key": "resolutiondate", "name": "Resolved", "custom": False, "schema": {"type": "datetime"}},
    {"id": "duedate", "key": "duedate", "name": "Due date", "custom": False, "schema": {"type": "date"}},
    {"id": "customfield_10016", "key": "customfield_10016", "name": "Story Points", "custom": True, "schema": {"type": "number"}},
    {"id": "customfield_10045", "key": "customfield_10045", "name": "Client", "custom": True, "schema": {"type": "string"}},
]
JIRA_SUMMARIES = [
    "Login page throws 500 on SSO callback", "Add export to CSV on reports", "Migrate invoices table to Postgres 16",
    "Dashboard charts overlap on mobile", "Implement audit log retention policy", "Slow search on contacts page",
    "Upgrade to Node 22", "Email notifications sent twice", "Add dark mode", "Bulk import fails on 10k rows",
    "Rate limit public API", "Fix timezone bug in scheduler", "Onboarding tour for new users", "Refactor billing module",
    "Add SAML support", "Broken pagination in deals list", "Improve error messages", "Add webhook retries",
]
CLIENT_VARIANTS = ["Acme Corp", "ACME", "Acme Corporation", "Bluebird Retail", "Bluebird", "Delta Pharma", "delta pharma", "Nimbus Software", "Nimbus", "Internal"]


@lru_cache(maxsize=1)
def build_jira() -> dict:
    rnd = random.Random(11)
    issues = []
    statuses = ["To Do", "In Progress", "In Review", "Done"]
    cat = {"To Do": "To Do", "In Progress": "In Progress", "In Review": "In Progress", "Done": "Done"}
    prios = ["Highest", "High", "Medium", "Low"]
    types = ["Bug", "Task", "Story"]
    comps = ["Backend", "Frontend", "Data"]
    people = list(JIRA_PEOPLE.values())
    for i in range(1, 61):
        status = statuses[(i * 7) % 4]
        # hidden meaning: some "Done" tickets were abandoned, only the resolution tells
        resolution = None
        if status == "Done":
            resolution = {"name": "Won't Do"} if i % 5 == 0 else {"name": "Done"}
        assignee = None if i % 9 == 0 else people[i % 4]
        created = TODAY - timedelta(days=10 + (i * 23) % 200)
        issues.append({
            "id": str(10000 + i),
            "key": f"TL-{i}",
            "fields": {
                "summary": JIRA_SUMMARIES[i % len(JIRA_SUMMARIES)] + ("" if i < 19 else f" ({i})"),
                "status": {"name": status, "statusCategory": {"name": cat[status]}},
                "resolution": resolution,
                "priority": {"name": prios[(i * 3) % 4]},
                "assignee": assignee,
                "reporter": people[(i + 1) % 4],
                "labels": (["tech-debt"] if i % 6 == 0 else []) + (["customer-request"] if i % 4 == 1 else []),
                "components": [{"name": comps[i % 3]}],
                "issuetype": {"name": types[i % 3]},
                "project": {"key": "TL", "name": "Treelife Platform"},
                "created": created.isoformat() + "T09:00:00.000+0530",
                "updated": (created + timedelta(days=(i * 5) % 20)).isoformat() + "T15:30:00.000+0530",
                "resolutiondate": ((created + timedelta(days=(i * 5) % 20)).isoformat() + "T15:30:00.000+0530") if status == "Done" else None,
                "duedate": (created + timedelta(days=30)).isoformat() if i % 3 == 0 else None,
                "customfield_10016": rnd.choice([1, 2, 3, 5, 8, None]),
                "customfield_10045": CLIENT_VARIANTS[i % len(CLIENT_VARIANTS)],
            },
        })
    return {"fields": JIRA_FIELDS, "issues": issues}
