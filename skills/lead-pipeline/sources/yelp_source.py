#!/usr/bin/env python3
"""
Yelp Source — Lead Pipeline
Searches for contractor businesses via SerpAPI Yelp results.
Extracts: business name, phone, website, review count, response time indicators.
Flags slow/no response time as a STRONG buying signal.
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


def _serpapi_yelp_request(params: dict, api_key: str) -> Optional[dict]:
    """Make a GET request to SerpAPI Yelp engine and return parsed JSON."""
    params["api_key"] = api_key
    params["engine"] = "yelp"
    query_string = urllib.parse.urlencode(params)
    url = f"https://serpapi.com/search.json?{query_string}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        if e.fp:
            body = e.fp.read().decode("utf-8", errors="replace")
        _log("yelp_api_error", None, "failure", f"HTTP {e.code}: {body}")
        return None
    except urllib.error.URLError as e:
        _log("yelp_api_error", None, "failure", f"URL error: {e.reason}")
        return None
    except Exception as e:
        _log("yelp_api_error", None, "failure", f"Unexpected error: {str(e)}")
        return None


def _classify_response_time(snippet: str, response_time_text: str) -> str:
    """
    Classify a Yelp business's response behavior.
    Returns: 'fast', 'slow', 'none', or 'unknown'.
    'slow' and 'none' are STRONG buying signals -- these businesses miss calls.
    """
    combined = f"{snippet} {response_time_text}".lower()

    # Fast response indicators
    fast_keywords = [
        "responds quickly", "response time: within an hour",
        "response time: within a few hours", "responds in about",
        "quick response", "fast response", "prompt",
    ]
    for kw in fast_keywords:
        if kw in combined:
            return "fast"

    # Slow response indicators
    slow_keywords = [
        "response time: within a day", "response time: within a few days",
        "slow to respond", "doesn't respond", "response time: over a week",
        "may not respond", "response time: a few days",
    ]
    for kw in slow_keywords:
        if kw in combined:
            return "slow"

    # No response info available -- also a signal (no effort on Yelp presence)
    if not response_time_text and not any(
        word in combined for word in ["respond", "response"]
    ):
        return "none"

    return "unknown"


def _build_search_queries(config: dict) -> list:
    """Build (find_desc, find_loc, vertical, city, state) tuples from config."""
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
                    display_vertical = vertical.replace("_", " ") + " contractor"
                    location = f"{city}, {state}"
                    queries.append((display_vertical, location, vertical, city, state))
    return queries


def run_yelp_source() -> list:
    """
    Execute the Yelp source pipeline via SerpAPI.
    Searches for contractor businesses and extracts listing data
    with special attention to response time indicators.
    Returns a list of raw lead dicts ready for scoring.
    """
    config = _load_config()
    yelp_config = config["sources"]["yelp"]
    api_key = os.environ.get(yelp_config["api_key_env"], "")
    if not api_key:
        _log("yelp_source_start", None, "failure",
             f"Missing API key: {yelp_config['api_key_env']} env var not set")
        return []

    rate_delay = yelp_config.get("rate_limit_delay_seconds", 2.0)
    max_results = yelp_config.get("max_results_per_query", 20)

    _log("yelp_source_start", None, "success",
         "Starting Yelp source run via SerpAPI")

    queries = _build_search_queries(config)
    leads = []
    seen_phones = set()
    seen_names = set()

    # Tier map
    tier_map = {}
    for tier_num, tier_key in enumerate(["tier_1", "tier_2", "tier_3"], start=1):
        for v in config["verticals"].get(tier_key, []):
            tier_map[v] = tier_num

    for find_desc, find_loc, vertical, city, state in queries:
        time.sleep(rate_delay)
        data = _serpapi_yelp_request({
            "find_desc": find_desc,
            "find_loc": find_loc,
        }, api_key)
        if not data:
            continue

        organic_results = data.get("organic_results", [])
        if not organic_results:
            _log("yelp_no_results", None, "skipped",
                 f"No results for: {find_desc} in {find_loc}")
            continue

        for result in organic_results:
            name = result.get("title", "").strip()
            phone = result.get("phone", "").strip()
            website = result.get("website", "").strip()
            reviews = result.get("reviews", 0)
            rating = result.get("rating", 0)
            snippet = result.get("snippet", "")
            response_time_text = result.get("response_time", "")

            if not name:
                continue

            # In-run dedup
            name_key = f"{name.lower()}|{city.lower()}"
            if phone and phone in seen_phones:
                continue
            if name_key in seen_names:
                continue
            if phone:
                seen_phones.add(phone)
            seen_names.add(name_key)

            # Classify response time
            response_indicator = _classify_response_time(snippet, response_time_text)

            # Determine if website is present and real
            has_website = bool(website) and "yelp.com" not in website.lower()

            lead = {
                "company_name": name,
                "contact_name": "",
                "contact_role": "",
                "email": "",
                "phone": phone,
                "website": website if has_website else "",
                "has_website": has_website,
                "vertical": vertical,
                "tier": tier_map.get(vertical, 3),
                "city": city,
                "state": state,
                "source": "yelp",
                "source_intent": "cold",
                "estimated_employee_count": None,
                "website_has_chat": None,
                "website_has_calltracking": None,
                "google_rating": None,
                "google_review_count": None,
                "yelp_rating": rating if rating else None,
                "yelp_review_count": reviews if reviews else None,
                "yelp_response_indicator": response_indicator,
                "yelp_snippet": snippet,
            }
            leads.append(lead)

        _log("yelp_query_complete", None, "success",
             f"Query '{find_desc}' in '{find_loc}': {len(organic_results)} results, "
             f"{len(leads)} cumulative leads")

    # Log response time distribution for analysis
    response_counts = {"fast": 0, "slow": 0, "none": 0, "unknown": 0}
    for lead in leads:
        indicator = lead.get("yelp_response_indicator", "unknown")
        response_counts[indicator] = response_counts.get(indicator, 0) + 1

    _log("yelp_source_complete", None, "success",
         f"Yelp source complete. {len(leads)} raw leads extracted. "
         f"Response time distribution: {json.dumps(response_counts)}")
    return leads


if __name__ == "__main__":
    results = run_yelp_source()
    print(json.dumps({"leads_found": len(results), "leads": results}, indent=2))
