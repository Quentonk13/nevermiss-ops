#!/usr/bin/env python3
"""
Apollo.io Source — Lead Pipeline
Discovers contractor contacts by vertical + location via the Apollo.io
People Search API (free tier: 10k credits/month). Extracts company name,
contact name, email, phone, website, role.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")

APOLLO_BASE_URL = "https://api.apollo.io/v1"


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "lead-pipeline",
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": llm_used,
        "tokens_estimated": tokens,
        "cost_estimated": cost,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _apollo_api_request(endpoint: str, body: dict, api_key: str) -> Optional[dict]:
    """Make a POST request to the Apollo.io API and return parsed JSON."""
    url = f"{APOLLO_BASE_URL}/{endpoint}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = ""
        if e.fp:
            body_text = e.fp.read().decode("utf-8", errors="replace")
        _log("apollo_api_error", None, "failure",
             f"HTTP {e.code} on {endpoint}: {body_text}")
        return None
    except urllib.error.URLError as e:
        _log("apollo_api_error", None, "failure",
             f"URL error on {endpoint}: {e.reason}")
        return None
    except Exception as e:
        _log("apollo_api_error", None, "failure",
             f"Unexpected error on {endpoint}: {str(e)}")
        return None


def _search_people(vertical: str, city: str, state: str,
                   api_key: str, rate_delay: float) -> list:
    """
    Search Apollo.io for people at companies matching a vertical + location.
    Returns list of person dicts from the API response.
    """
    time.sleep(rate_delay)
    data = _apollo_api_request("mixed_people/search", {
        "q_organization_name": f"{vertical} contractor",
        "person_locations": [f"{city}, {state}"],
        "per_page": 10,
        "person_seniorities": [
            "owner", "founder", "c_suite", "director", "manager"
        ],
    }, api_key)
    if not data:
        return []
    return data.get("people", [])


def _build_search_queries(config: dict) -> list:
    """
    Build a list of (vertical, city, state) tuples from config target geos.
    Uses all phases that are configured.
    """
    queries = []
    verticals_all = (
        config["verticals"]["tier_1"]
        + config["verticals"]["tier_2"]
        + config["verticals"]["tier_3"]
    )
    for phase_key in ("phase_1", "phase_2"):
        geos = config["target_geos"].get(phase_key, [])
        for geo in geos:
            state = geo["state"]
            for city in geo["cities"]:
                for vertical in verticals_all:
                    queries.append((vertical, city, state))
    return queries


def run_apollo_source() -> list:
    """
    Execute the Apollo.io source pipeline.
    Searches for contractor contacts by vertical + location.
    Returns a list of raw lead dicts ready for scoring.
    """
    config = _load_config()
    apollo_config = config.get("sources", {}).get("apollo", {})
    api_key_env = apollo_config.get("api_key_env", "APOLLO_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        _log("apollo_source_start", None, "failure",
             f"Missing API key: {api_key_env} env var not set")
        return []

    rate_delay = apollo_config.get("rate_limit_delay_seconds", 1.5)
    max_requests = apollo_config.get("max_requests_per_run", 100)
    batch_size = apollo_config.get("batch_size", 10)

    _log("apollo_source_start", None, "success",
         f"Starting Apollo.io source run. Max requests: {max_requests}")

    queries = _build_search_queries(config)
    leads = []
    request_count = 0

    # Determine vertical tier for each vertical
    tier_map = {}
    for tier_num, tier_key in enumerate(["tier_1", "tier_2", "tier_3"], start=1):
        for v in config["verticals"].get(tier_key, []):
            tier_map[v] = tier_num

    for vertical, city, state in queries:
        if request_count >= max_requests:
            _log("apollo_source_rate_limit", None, "skipped",
                 f"Reached max requests ({max_requests}), stopping early")
            break

        people = _search_people(vertical, city, state, api_key, rate_delay)
        request_count += 1

        for person in people:
            email = person.get("email", "")
            if not email:
                continue

            first_name = person.get("first_name", "") or ""
            last_name = person.get("last_name", "") or ""
            contact_name = f"{first_name} {last_name}".strip()

            title = person.get("title", "") or ""

            org = person.get("organization") or {}
            company_name = org.get("name", "") or ""
            website_url = org.get("website_url", "") or ""

            phone = ""
            phone_numbers = person.get("phone_numbers") or []
            if phone_numbers:
                phone = phone_numbers[0].get("sanitized_number", "") or ""

            has_website = bool(website_url)

            lead = {
                "company_name": company_name,
                "contact_name": contact_name,
                "contact_role": title,
                "email": email,
                "phone": phone,
                "website": website_url,
                "has_website": has_website,
                "vertical": vertical,
                "tier": tier_map.get(vertical, 3),
                "city": city,
                "state": state,
                "source": "apollo",
                "source_intent": "cold",
                "estimated_employee_count": None,
                "website_has_chat": None,
                "website_has_calltracking": None,
                "google_rating": None,
                "google_review_count": None,
                "yelp_response_indicator": None,
            }
            leads.append(lead)

        # Batch logging
        if request_count % batch_size == 0:
            _log("apollo_source_batch", None, "success",
                 f"Processed {request_count} requests, {len(leads)} leads found so far")

    _log("apollo_source_complete", None, "success",
         f"Apollo.io source complete. {len(leads)} raw leads extracted. "
         f"{request_count} API requests used.")
    return leads


if __name__ == "__main__":
    results = run_apollo_source()
    print(json.dumps({"leads_found": len(results), "leads": results}, indent=2))
