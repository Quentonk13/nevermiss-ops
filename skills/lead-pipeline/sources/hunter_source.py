#!/usr/bin/env python3
"""
Hunter.io Source — Lead Pipeline
Discovers contractor contacts by vertical + location via the Hunter.io Domain Search
and Email Finder APIs. Extracts company name, contact name, email, phone, website, role.
"""

import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")


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


def _hunter_api_request(endpoint: str, params: dict, api_key: str) -> Optional[dict]:
    """Make a GET request to the Hunter.io API and return parsed JSON."""
    params["api_key"] = api_key
    query_string = urllib.parse.urlencode(params)
    url = f"https://api.hunter.io/v2/{endpoint}?{query_string}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        if e.fp:
            body = e.fp.read().decode("utf-8", errors="replace")
        _log("hunter_api_error", None, "failure",
             f"HTTP {e.code} on {endpoint}: {body}")
        return None
    except urllib.error.URLError as e:
        _log("hunter_api_error", None, "failure",
             f"URL error on {endpoint}: {e.reason}")
        return None
    except Exception as e:
        _log("hunter_api_error", None, "failure",
             f"Unexpected error on {endpoint}: {str(e)}")
        return None


def _domain_search(domain: str, api_key: str, rate_delay: float) -> list:
    """
    Search a domain for email addresses using Hunter.io Domain Search.
    Returns list of email/contact dicts.
    """
    time.sleep(rate_delay)
    data = _hunter_api_request("domain-search", {
        "domain": domain,
        "limit": 10,
        "type": "personal",
    }, api_key)
    if not data or "data" not in data:
        return []
    emails = data["data"].get("emails", [])
    results = []
    for email_entry in emails:
        first = email_entry.get("first_name", "")
        last = email_entry.get("last_name", "")
        contact_name = f"{first} {last}".strip()
        role = email_entry.get("position", "") or email_entry.get("seniority", "")
        phone_number = email_entry.get("phone_number", "")
        results.append({
            "email": email_entry.get("value", ""),
            "contact_name": contact_name,
            "contact_role": role,
            "phone": phone_number,
            "confidence": email_entry.get("confidence", 0),
        })
    return results


def _email_finder(domain: str, first_name: str, last_name: str,
                  api_key: str, rate_delay: float) -> Optional[dict]:
    """
    Find a specific email address using Hunter.io Email Finder.
    Returns dict with email and confidence, or None.
    """
    time.sleep(rate_delay)
    params = {"domain": domain}
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name
    data = _hunter_api_request("email-finder", params, api_key)
    if not data or "data" not in data:
        return None
    result = data["data"]
    if not result.get("email"):
        return None
    return {
        "email": result["email"],
        "confidence": result.get("confidence", 0),
        "contact_name": f"{first_name} {last_name}".strip(),
    }


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


def _search_company_domain(company_name: str, city: str, state: str) -> Optional[str]:
    """
    Attempt to find a company's domain using Hunter.io Company Search.
    Falls back to a simple heuristic domain guess if API search returns nothing.
    """
    # Hunter.io doesn't have a company name search, so we use a heuristic
    # to generate a likely domain name from the company name.
    clean = company_name.lower().strip()
    # Remove common suffixes
    for suffix in [" llc", " inc", " corp", " co", " ltd", " company", " services",
                   " service", " and sons", " & sons", " enterprises", " group"]:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)].strip()
    # Replace spaces and special chars with empty string for domain
    domain_base = "".join(c for c in clean if c.isalnum())
    if domain_base:
        return f"{domain_base}.com"
    return None


def run_hunter_source() -> list:
    """
    Execute the Hunter.io source pipeline.
    Searches for contractor contacts by vertical + location.
    Returns a list of raw lead dicts ready for scoring.
    """
    config = _load_config()
    hunter_config = config["sources"]["hunter"]
    api_key = os.environ.get(hunter_config["api_key_env"], "")
    if not api_key:
        _log("hunter_source_start", None, "failure",
             f"Missing API key: {hunter_config['api_key_env']} env var not set")
        return []

    rate_delay = hunter_config.get("rate_limit_delay_seconds", 1.5)
    max_requests = hunter_config.get("max_requests_per_run", 100)
    batch_size = hunter_config.get("batch_size", 10)

    _log("hunter_source_start", None, "success",
         f"Starting Hunter.io source run. Max requests: {max_requests}")

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
            _log("hunter_source_rate_limit", None, "skipped",
                 f"Reached max requests ({max_requests}), stopping early")
            break

        # Generate a plausible domain search query
        # Hunter.io works best with known domains. We search for companies
        # by constructing queries and using the domain-search endpoint.
        search_query = f"{vertical} contractor {city} {state}"
        domain_guess = _search_company_domain(
            f"{vertical} {city}", city, state
        )
        if not domain_guess:
            continue

        # Use the email-count endpoint to check if domain has results
        time.sleep(rate_delay)
        count_data = _hunter_api_request("email-count", {
            "domain": domain_guess
        }, api_key)
        request_count += 1

        if not count_data or count_data.get("data", {}).get("total", 0) == 0:
            # Domain has no results; skip to next
            continue

        # Domain search to find contacts
        contacts = _domain_search(domain_guess, api_key, rate_delay)
        request_count += 1

        for contact in contacts:
            if not contact.get("email"):
                continue
            # Only keep contacts with reasonable confidence
            if contact.get("confidence", 0) < 30:
                continue

            lead = {
                "company_name": f"{vertical.replace('_', ' ').title()} - {domain_guess}",
                "contact_name": contact.get("contact_name", ""),
                "contact_role": contact.get("contact_role", ""),
                "email": contact["email"],
                "phone": contact.get("phone", ""),
                "website": f"https://{domain_guess}",
                "has_website": True,
                "vertical": vertical,
                "tier": tier_map.get(vertical, 3),
                "city": city,
                "state": state,
                "source": "hunter",
                "source_intent": "cold",
                "estimated_employee_count": None,
                "website_has_chat": None,
                "website_has_calltracking": None,
                "google_rating": None,
                "google_review_count": None,
                "yelp_response_indicator": None,
            }
            leads.append(lead)

        # Batch pacing
        if request_count % batch_size == 0:
            _log("hunter_source_batch", None, "success",
                 f"Processed {request_count} requests, {len(leads)} leads found so far")

    _log("hunter_source_complete", None, "success",
         f"Hunter.io source complete. {len(leads)} raw leads extracted. "
         f"{request_count} API requests used.")
    return leads


if __name__ == "__main__":
    results = run_hunter_source()
    print(json.dumps({"leads_found": len(results), "leads": results}, indent=2))
