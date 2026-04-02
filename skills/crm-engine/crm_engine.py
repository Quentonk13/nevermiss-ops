#!/usr/bin/env python3
"""
CRM Engine — Skill 1
Central pipeline tracking, deduplication, status management, and suppression enforcement.
All logic is deterministic (hard-coded Python), no LLM calls.
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

# Levenshtein distance for fuzzy company matching
def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
CRM_PATH = os.path.join(DATA_DIR, "crm.json")
SUPPRESSION_PATH = os.path.join(DATA_DIR, "suppression_list.json")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

VALID_TRANSITIONS = {
    "new": ["contacted", "lost"],
    "contacted": ["replied", "lost", "stalled"],
    "replied": ["qualified", "lost", "objection_handled", "stalled"],
    "qualified": ["booked", "lost", "stalled"],
    "booked": ["demo_completed", "lost", "stalled"],
    "demo_completed": ["closed", "lost", "stalled"],
    "closed": ["onboarding"],
    "onboarding": [],
    "lost": [],
    "objection_handled": ["replied", "lost"],
    "stalled": ["contacted", "replied", "lost"],
}

COMPETITOR_DOMAINS = [
    "servicetitan.com",
    "housecallpro.com",
    "jobber.com",
    "podium.com",
    "smith.ai",
    "ruby.com",
    "numa.com",
    "hatch.co",
]

SUPPRESSED_ROLE_PREFIXES = ["info@", "admin@", "noreply@", "sales@", "support@"]

DECLINE_KEYWORDS = [
    "not interested",
    "remove me",
    "stop",
    "unsubscribe",
    "take me off",
    "don't contact",
    "do not contact",
    "opt out",
    "opt-out",
]


def _log(skill: str, action: str, lead_id: Optional[str], result: str, details: str):
    """Append a structured log entry to system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": "none",
        "tokens_estimated": 0,
        "cost_estimated": 0.00,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_crm() -> dict:
    """Load CRM data from disk, initializing if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(CRM_PATH):
        with open(CRM_PATH, "r") as f:
            return json.load(f)
    default = {
        "leads": {},
        "suppression_list": [],
        "metrics": {
            "total_leads": 0,
            "leads_by_stage": {},
            "leads_by_vertical": {},
            "leads_by_source": {},
            "conversion_rates": {},
        },
    }
    _save_crm(default)
    return default


def _save_crm(data: dict):
    """Persist CRM data to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CRM_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _load_suppression() -> list:
    """Load the suppression list from disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SUPPRESSION_PATH):
        with open(SUPPRESSION_PATH, "r") as f:
            return json.load(f)
    _save_suppression([])
    return []


def _save_suppression(data: list):
    """Persist the suppression list to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SUPPRESSION_PATH, "w") as f:
        json.dump(data, f, indent=2)


def is_suppressed(email: str) -> bool:
    """
    Check if an email is on the suppression list.
    Checks: exact email match, competitor domain, role prefix.
    This is a HARD GATE — no exceptions.
    """
    email_lower = email.lower().strip()
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""

    # Check competitor domains
    for comp_domain in COMPETITOR_DOMAINS:
        if domain == comp_domain:
            return True

    # Check role prefixes (except support@ at small companies — handled by caller context)
    for prefix in SUPPRESSED_ROLE_PREFIXES:
        if email_lower.startswith(prefix):
            return True

    # Check explicit suppression list
    suppression = _load_suppression()
    for entry in suppression:
        if isinstance(entry, str):
            if email_lower == entry.lower():
                return True
        elif isinstance(entry, dict):
            if email_lower == entry.get("email", "").lower():
                return True
            if domain and domain == entry.get("domain", "").lower():
                return True

    return False


def add_to_suppression(email: str, reason: str):
    """Add an email to the permanent suppression list."""
    suppression = _load_suppression()
    email_lower = email.lower().strip()

    # Avoid duplicates
    for entry in suppression:
        if isinstance(entry, dict) and entry.get("email", "").lower() == email_lower:
            return
        if isinstance(entry, str) and entry.lower() == email_lower:
            return

    suppression.append({
        "email": email_lower,
        "reason": reason,
        "added_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_suppression(suppression)
    _log("crm-engine", "suppression_add", None, "success",
         f"Added {email_lower} to suppression list. Reason: {reason}")


def check_decline_keywords(text: str) -> bool:
    """Check if text contains decline/unsubscribe keywords."""
    text_lower = text.lower()
    for keyword in DECLINE_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def _find_duplicate(crm: dict, lead_data: dict) -> Optional[str]:
    """
    Check for duplicates using three-tier matching:
    1. Exact email match
    2. Company name + city + state fuzzy match (Levenshtein < 3)
    3. Exact phone match
    Returns the existing lead_id if duplicate found, else None.
    """
    email = lead_data.get("email", "").lower().strip()
    phone = lead_data.get("phone", "").strip()
    company = lead_data.get("company_name", "").lower().strip()
    city = lead_data.get("city", "").lower().strip()
    state = lead_data.get("state", "").lower().strip()

    for lid, existing in crm["leads"].items():
        # Primary: exact email match
        if email and existing.get("email", "").lower().strip() == email:
            return lid

        # Secondary: company_name + city + state fuzzy
        ex_company = existing.get("company_name", "").lower().strip()
        ex_city = existing.get("city", "").lower().strip()
        ex_state = existing.get("state", "").lower().strip()
        if (company and ex_company and ex_city == city and ex_state == state
                and _levenshtein(company, ex_company) < 3):
            return lid

        # Tertiary: exact phone match
        if phone and existing.get("phone", "").strip() == phone:
            return lid

    return None


def _merge_leads(existing: dict, new_data: dict) -> dict:
    """Merge missing fields from new_data into existing lead, keep highest score."""
    for key, value in new_data.items():
        if key in ("id", "status", "status_history", "conversation", "created_at"):
            continue
        if value and not existing.get(key):
            existing[key] = value

    # Keep highest score
    new_score = new_data.get("lead_score", 0)
    if new_score > existing.get("lead_score", 0):
        existing["lead_score"] = new_score

    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    return existing


def insert_lead(lead_data: dict) -> dict:
    """
    Insert a new lead into the CRM.
    Runs deduplication, suppression check, and scoring gate.
    Returns {"status": "inserted"|"merged"|"suppressed"|"below_threshold", "lead_id": ...}
    """
    crm = _load_crm()
    email = lead_data.get("email", "").strip()

    # Suppression check
    if email and is_suppressed(email):
        _log("crm-engine", "insert_blocked_suppressed", None, "skipped",
             f"Email {email} is on suppression list")
        return {"status": "suppressed", "lead_id": None}

    # Score gate: only leads >= 3 pass
    score = lead_data.get("lead_score", 0)
    if score < 3:
        _log("crm-engine", "insert_below_threshold", None, "skipped",
             f"Lead {email} scored {score}, below threshold of 3")
        return {"status": "below_threshold", "lead_id": None}

    # Deduplication check
    dup_id = _find_duplicate(crm, lead_data)
    if dup_id:
        crm["leads"][dup_id] = _merge_leads(crm["leads"][dup_id], lead_data)
        _save_crm(crm)
        _log("crm-engine", "duplicate_merged", dup_id, "success",
             f"Duplicate detected: {email} matches {dup_id}. Merged.")
        return {"status": "merged", "lead_id": dup_id}

    # Create new lead
    lead_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    source_skill = lead_data.get("source_skill", "lead-pipeline")

    new_lead = {
        "id": lead_id,
        "company_name": lead_data.get("company_name", ""),
        "contact_name": lead_data.get("contact_name", ""),
        "contact_role": lead_data.get("contact_role", ""),
        "email": email,
        "phone": lead_data.get("phone", ""),
        "vertical": lead_data.get("vertical", ""),
        "tier": lead_data.get("tier", 3),
        "city": lead_data.get("city", ""),
        "state": lead_data.get("state", ""),
        "website": lead_data.get("website", ""),
        "has_website": lead_data.get("has_website", True),
        "website_has_chat": lead_data.get("website_has_chat"),
        "website_has_calltracking": lead_data.get("website_has_calltracking"),
        "google_rating": lead_data.get("google_rating"),
        "google_review_count": lead_data.get("google_review_count"),
        "yelp_response_indicator": lead_data.get("yelp_response_indicator"),
        "estimated_employee_count": lead_data.get("estimated_employee_count"),
        "source": lead_data.get("source", "unknown"),
        "source_intent": lead_data.get("source_intent", "cold"),
        "lead_score": score,
        "status": "new",
        "status_history": [
            {
                "status": "new",
                "timestamp": now,
                "changed_by": source_skill,
                "reason": "Initial import",
            }
        ],
        "conversation": [],
        "variant_used": None,
        "objections_raised": [],
        "created_at": now,
        "updated_at": now,
        "notes": lead_data.get("notes", ""),
    }

    crm["leads"][lead_id] = new_lead
    crm["metrics"]["total_leads"] = len(crm["leads"])
    _update_metrics(crm)
    _save_crm(crm)

    _log("crm-engine", "lead_inserted", lead_id, "success",
         f"New lead: {email}, score={score}, vertical={new_lead['vertical']}")

    return {"status": "inserted", "lead_id": lead_id}


def update_status(lead_id: str, new_status: str, changed_by: str, reason: str) -> bool:
    """
    Update a lead's pipeline status. Enforces valid transitions.
    Returns True if transition was valid and applied, False otherwise.
    """
    crm = _load_crm()

    if lead_id not in crm["leads"]:
        _log("crm-engine", "status_update_failed", lead_id, "failure",
             f"Lead {lead_id} not found")
        return False

    lead = crm["leads"][lead_id]
    current_status = lead["status"]

    # Enforce valid transitions
    allowed = VALID_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        _log("crm-engine", "status_update_rejected", lead_id, "failure",
             f"Invalid transition: {current_status} -> {new_status}. Allowed: {allowed}")
        return False

    now = datetime.now(timezone.utc).isoformat()
    lead["status"] = new_status
    lead["status_history"].append({
        "status": new_status,
        "timestamp": now,
        "changed_by": changed_by,
        "reason": reason,
    })
    lead["updated_at"] = now

    _update_metrics(crm)
    _save_crm(crm)

    _log("crm-engine", "status_updated", lead_id, "success",
         f"Status changed: {current_status} -> {new_status}. By: {changed_by}. Reason: {reason}")

    return True


def add_conversation_message(lead_id: str, direction: str, message: str, channel: str = "email"):
    """
    Add a message to a lead's conversation history.
    direction: 'inbound' or 'outbound'
    """
    crm = _load_crm()
    if lead_id not in crm["leads"]:
        _log("crm-engine", "conversation_add_failed", lead_id, "failure", "Lead not found")
        return False

    now = datetime.now(timezone.utc).isoformat()
    crm["leads"][lead_id]["conversation"].append({
        "direction": direction,
        "message": message,
        "channel": channel,
        "timestamp": now,
    })
    crm["leads"][lead_id]["updated_at"] = now
    _save_crm(crm)
    return True


def add_objection(lead_id: str, objection_type: str):
    """Record an objection raised by a lead."""
    crm = _load_crm()
    if lead_id not in crm["leads"]:
        return False
    crm["leads"][lead_id]["objections_raised"].append({
        "type": objection_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_crm(crm)
    return True


def set_variant(lead_id: str, variant: str):
    """Record which email variant was used for a lead."""
    crm = _load_crm()
    if lead_id not in crm["leads"]:
        return False
    crm["leads"][lead_id]["variant_used"] = variant
    _save_crm(crm)
    return True


def get_lead(lead_id: str) -> Optional[dict]:
    """Retrieve a single lead by ID."""
    crm = _load_crm()
    return crm["leads"].get(lead_id)


def get_lead_by_email(email: str) -> Optional[dict]:
    """Retrieve a lead by email address."""
    crm = _load_crm()
    email_lower = email.lower().strip()
    for lid, lead in crm["leads"].items():
        if lead.get("email", "").lower().strip() == email_lower:
            return lead
    return None


def get_leads_by_status(status: str) -> list:
    """Retrieve all leads with a given status."""
    crm = _load_crm()
    return [lead for lead in crm["leads"].values() if lead["status"] == status]


def get_leads_for_outreach() -> list:
    """Get leads that are ready for initial outreach (status=new, score>=3, not suppressed)."""
    crm = _load_crm()
    results = []
    for lead in crm["leads"].values():
        if lead["status"] == "new" and lead["lead_score"] >= 3:
            if not is_suppressed(lead["email"]):
                results.append(lead)
    return results


def _update_metrics(crm: dict):
    """Recalculate pipeline metrics."""
    stage_counts = {}
    vertical_counts = {}
    source_counts = {}

    for lead in crm["leads"].values():
        s = lead["status"]
        stage_counts[s] = stage_counts.get(s, 0) + 1

        v = lead.get("vertical", "unknown")
        vertical_counts[v] = vertical_counts.get(v, 0) + 1

        src = lead.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    crm["metrics"]["total_leads"] = len(crm["leads"])
    crm["metrics"]["leads_by_stage"] = stage_counts
    crm["metrics"]["leads_by_vertical"] = vertical_counts
    crm["metrics"]["leads_by_source"] = source_counts

    # Conversion rates
    total = len(crm["leads"])
    contacted = sum(1 for l in crm["leads"].values() if l["status"] != "new")
    replied = sum(1 for l in crm["leads"].values()
                  if l["status"] in ("replied", "qualified", "booked", "demo_completed",
                                     "closed", "onboarding", "objection_handled"))
    qualified = sum(1 for l in crm["leads"].values()
                    if l["status"] in ("qualified", "booked", "demo_completed",
                                       "closed", "onboarding"))
    booked = sum(1 for l in crm["leads"].values()
                 if l["status"] in ("booked", "demo_completed", "closed", "onboarding"))
    closed = sum(1 for l in crm["leads"].values()
                 if l["status"] in ("closed", "onboarding"))

    crm["metrics"]["conversion_rates"] = {
        "lead_to_contacted": round(contacted / total * 100, 1) if total else 0,
        "contacted_to_replied": round(replied / contacted * 100, 1) if contacted else 0,
        "replied_to_qualified": round(qualified / replied * 100, 1) if replied else 0,
        "qualified_to_booked": round(booked / qualified * 100, 1) if qualified else 0,
        "booked_to_closed": round(closed / booked * 100, 1) if booked else 0,
        "overall_lead_to_closed": round(closed / total * 100, 1) if total else 0,
    }


def run_daily_audit() -> dict:
    """
    Daily audit at 11:00 PM PT.
    Flags leads stuck in any stage > 14 days with no activity.
    Returns audit summary.
    """
    crm = _load_crm()
    now = datetime.now(timezone.utc)
    threshold = timedelta(days=14)
    stale_leads = []

    for lid, lead in crm["leads"].items():
        if lead["status"] in ("closed", "onboarding", "lost"):
            continue
        updated = datetime.fromisoformat(lead["updated_at"].replace("Z", "+00:00"))
        if now - updated > threshold:
            stale_leads.append({
                "lead_id": lid,
                "email": lead["email"],
                "company": lead["company_name"],
                "status": lead["status"],
                "days_stale": (now - updated).days,
            })

    _update_metrics(crm)
    _save_crm(crm)

    audit_result = {
        "timestamp": now.isoformat(),
        "total_leads": len(crm["leads"]),
        "stale_leads": stale_leads,
        "stale_count": len(stale_leads),
        "pipeline_snapshot": crm["metrics"]["leads_by_stage"],
    }

    _log("crm-engine", "daily_audit", None, "success",
         f"Audit complete. {len(stale_leads)} stale leads found.")

    return audit_result


def generate_weekly_summary() -> dict:
    """
    Generate the weekly pipeline summary for owner notification.
    Returns structured summary data.
    """
    crm = _load_crm()
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    new_this_week = 0
    demos_booked = 0
    deals_closed = 0
    leads_lost = []
    mrr_added = 0

    for lead in crm["leads"].values():
        for entry in lead.get("status_history", []):
            ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if ts < week_ago:
                continue
            if entry["status"] == "new":
                new_this_week += 1
            elif entry["status"] == "booked":
                demos_booked += 1
            elif entry["status"] == "closed":
                deals_closed += 1
                mrr_added += 297
            elif entry["status"] == "lost":
                leads_lost.append({
                    "company": lead["company_name"],
                    "reason": entry.get("reason", "unknown"),
                })

    summary = {
        "week_ending": now.isoformat(),
        "pipeline_snapshot": crm["metrics"]["leads_by_stage"],
        "new_leads_this_week": new_this_week,
        "demos_booked": demos_booked,
        "deals_closed": deals_closed,
        "mrr_added": mrr_added,
        "leads_lost": leads_lost,
        "conversion_rates": crm["metrics"]["conversion_rates"],
    }

    _log("crm-engine", "weekly_summary", None, "success",
         f"Weekly summary: {new_this_week} new, {demos_booked} booked, "
         f"{deals_closed} closed, ${mrr_added} MRR added")

    return summary


def get_all_metrics() -> dict:
    """Return current CRM metrics for other skills to consume."""
    crm = _load_crm()
    _update_metrics(crm)
    _save_crm(crm)
    return crm["metrics"]


def get_pipeline_data() -> dict:
    """Return full pipeline data for CEO-bot and performance-engine."""
    crm = _load_crm()
    return {
        "leads": crm["leads"],
        "metrics": crm["metrics"],
        "suppression_count": len(_load_suppression()),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "audit":
        result = run_daily_audit()
        print(json.dumps(result, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        result = generate_weekly_summary()
        print(json.dumps(result, indent=2))
    else:
        print("CRM Engine ready. Usage: python crm_engine.py [audit|summary]")
