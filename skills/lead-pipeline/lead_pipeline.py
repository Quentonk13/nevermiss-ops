#!/usr/bin/env python3
"""
Lead Pipeline — Main Orchestrator
Sources, enriches, deduplicates, scores, and stores contractor leads from
multiple channels. Feeds qualified leads (score >= 3) into CRM engine.

LLM: Groq/Llama for enrichment and Facebook post classification. NO Claude.
Scoring is fully DETERMINISTIC (no LLM involvement in scoring).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")

# Add sources directory to path for source imports
SOURCES_DIR = os.path.join(SKILL_DIR, "sources")
sys.path.insert(0, SOURCES_DIR)
from apollo_source import run_apollo_source
from google_maps_source import run_google_maps_source
from yelp_source import run_yelp_source
from facebook_source import run_facebook_source

# Lazy import for CRM engine to avoid circular deps
CRM_ENGINE = None

# Groq cost estimates for enrichment calls
GROQ_COST_PER_1K_INPUT = 0.00059
GROQ_COST_PER_1K_OUTPUT = 0.00079
AVG_ENRICHMENT_INPUT_TOKENS = 400
AVG_ENRICHMENT_OUTPUT_TOKENS = 100


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


def _get_crm_engine():
    """Lazy-load CRM engine to avoid import issues at module level."""
    global CRM_ENGINE
    if CRM_ENGINE is None:
        import importlib.util
        crm_path = os.path.join(PROJECT_ROOT, "skills", "crm-engine", "crm_engine.py")
        spec = importlib.util.spec_from_file_location("crm_engine", crm_path)
        crm_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crm_module)
        CRM_ENGINE = crm_module.insert_lead
    return CRM_ENGINE


def _groq_enrich_lead(lead: dict, groq_api_key: str, model: str) -> dict:
    """
    Use Groq/Llama to enrich a lead with estimated employee count and
    website technology signals when we have a website but missing data.
    Returns the lead dict with enrichment fields populated.
    """
    website = lead.get("website", "")
    company_name = lead.get("company_name", "")
    vertical = lead.get("vertical", "")
    city = lead.get("city", "")
    state = lead.get("state", "")

    # Only enrich if we have something to work with and are missing data
    has_employee_count = lead.get("estimated_employee_count") is not None
    has_chat_info = lead.get("website_has_chat") is not None
    has_calltracking_info = lead.get("website_has_calltracking") is not None

    if has_employee_count and has_chat_info and has_calltracking_info:
        return lead

    if not company_name and not website:
        return lead

    system_prompt = (
        "You are a business analyst estimating company attributes for a home service "
        "contractor. Based on the company info provided, estimate the following. "
        "Respond ONLY with valid JSON.\n\n"
        "Required JSON fields:\n"
        '- "estimated_employees": integer estimate (1-500), based on typical company size '
        "for this vertical and location\n"
        '- "likely_has_live_chat": true or false, whether a company like this likely has '
        "live chat on their website\n"
        '- "likely_has_call_tracking": true or false, whether they likely use call tracking '
        "software\n"
        '- "reasoning": one sentence explaining your estimates'
    )

    user_prompt = (
        f"Company: {company_name}\n"
        f"Website: {website}\n"
        f"Vertical: {vertical.replace('_', ' ')}\n"
        f"Location: {city}, {state}\n"
        f"Google rating: {lead.get('google_rating', 'unknown')}\n"
        f"Google reviews: {lead.get('google_review_count', 'unknown')}\n"
        f"Yelp reviews: {lead.get('yelp_review_count', 'unknown')}"
    )

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

        content = response_data["choices"][0]["message"]["content"]
        usage = response_data.get("usage", {})
        actual_tokens = usage.get("total_tokens", AVG_ENRICHMENT_INPUT_TOKENS + AVG_ENRICHMENT_OUTPUT_TOKENS)
        actual_input = usage.get("prompt_tokens", AVG_ENRICHMENT_INPUT_TOKENS)
        actual_output = usage.get("completion_tokens", AVG_ENRICHMENT_OUTPUT_TOKENS)
        actual_cost = (
            (actual_input / 1000) * GROQ_COST_PER_1K_INPUT
            + (actual_output / 1000) * GROQ_COST_PER_1K_OUTPUT
        )

        enrichment = json.loads(content)

        if not has_employee_count:
            est = enrichment.get("estimated_employees")
            if isinstance(est, (int, float)) and 1 <= est <= 500:
                lead["estimated_employee_count"] = int(est)

        if not has_chat_info:
            lead["website_has_chat"] = bool(enrichment.get("likely_has_live_chat", False))

        if not has_calltracking_info:
            lead["website_has_calltracking"] = bool(enrichment.get("likely_has_call_tracking", False))

        _log("enrich_lead", None, "success",
             f"Enriched {company_name}: employees={lead.get('estimated_employee_count')}, "
             f"chat={lead.get('website_has_chat')}, calltrack={lead.get('website_has_calltracking')}",
             llm_used="groq", tokens=actual_tokens, cost=round(actual_cost, 6))
        return lead

    except urllib.error.HTTPError as e:
        body = ""
        if e.fp:
            body = e.fp.read().decode("utf-8", errors="replace")
        _log("enrich_lead_error", None, "failure",
             f"Groq enrichment failed for {company_name}: HTTP {e.code}: {body}",
             llm_used="groq", tokens=0, cost=0.00)
        return lead
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        _log("enrich_lead_parse_error", None, "failure",
             f"Failed to parse Groq enrichment for {company_name}: {str(e)}",
             llm_used="groq", tokens=0, cost=0.00)
        return lead
    except Exception as e:
        _log("enrich_lead_error", None, "failure",
             f"Unexpected enrichment error for {company_name}: {str(e)}",
             llm_used="groq", tokens=0, cost=0.00)
        return lead


def score_lead(lead: dict, config: dict) -> int:
    """
    DETERMINISTIC lead scoring. No LLM involvement.
    Score range: 1-5 points.

    +1  Base point (every lead gets this)
    +1  Tier 1 vertical (HVAC, plumbing, electrical)
    +1  Estimated employees < 20
    +1  No live chat/call tracking on website OR Yelp slow response OR no website
    +1  Warm intent source OR Google reviews > 50 OR contact role is owner/president/founder
    """
    scoring = config.get("scoring", {})
    score = scoring.get("base_points", 1)

    # +1 if Tier 1 vertical
    tier_1_verticals = config.get("verticals", {}).get("tier_1", [])
    vertical = lead.get("vertical", "")
    if vertical in tier_1_verticals:
        score += scoring.get("tier_1_vertical_bonus", 1)

    # +1 if estimated employees < 20
    employee_threshold = scoring.get("small_company_threshold_employees", 20)
    estimated_employees = lead.get("estimated_employee_count")
    if estimated_employees is not None and estimated_employees < employee_threshold:
        score += scoring.get("small_company_bonus", 1)

    # +1 if no live chat/call tracking on website OR Yelp slow response OR no website
    no_tech_signal = False
    has_website = lead.get("has_website", True)
    website_has_chat = lead.get("website_has_chat")
    website_has_calltracking = lead.get("website_has_calltracking")
    yelp_response = lead.get("yelp_response_indicator", "")

    if not has_website:
        no_tech_signal = True
    elif website_has_chat is not None and not website_has_chat:
        no_tech_signal = True
    elif website_has_calltracking is not None and not website_has_calltracking:
        no_tech_signal = True

    if yelp_response in ("slow", "none"):
        no_tech_signal = True

    if no_tech_signal:
        score += scoring.get("no_tech_bonus", 1)

    # +1 if warm_intent source OR Google reviews > 50 OR contact role is owner/president/founder
    warm_signal = False
    source_intent = lead.get("source_intent", "cold")
    if source_intent == "warm_intent":
        warm_signal = True

    review_threshold = scoring.get("high_review_threshold", 50)
    google_reviews = lead.get("google_review_count")
    if google_reviews is not None and google_reviews > review_threshold:
        warm_signal = True

    owner_roles = scoring.get("owner_roles", [
        "owner", "president", "founder", "co-founder", "ceo", "principal"
    ])
    contact_role = lead.get("contact_role", "").lower().strip()
    if contact_role:
        for role in owner_roles:
            if role.lower() in contact_role:
                warm_signal = True
                break

    if warm_signal:
        score += scoring.get("warm_intent_bonus", 1)

    # Cap at 5
    return min(score, 5)


def run_daily_sources() -> dict:
    """
    Run the daily source pipeline: Hunter.io, Google Maps, Yelp.
    Triggered at 6:00 AM PT.
    Returns run summary.
    """
    return _run_pipeline(["apollo", "google_maps", "yelp"], "daily")


def run_facebook_pipeline() -> dict:
    """
    Run the Facebook source pipeline.
    Triggered every 4 hours during 8 AM - 8 PM PT.
    Returns run summary.
    """
    return _run_pipeline(["facebook"], "facebook")


def _run_pipeline(source_names: list, run_type: str) -> dict:
    """
    Core pipeline execution: source -> enrich -> score -> gate -> CRM.
    """
    config = _load_config()
    groq_api_key = os.environ.get(config["llm"]["api_key_env"], "")
    groq_model = config["llm"].get("model", "llama-3.1-70b-versatile")
    min_score = config["scoring"].get("minimum_qualifying_score", 3)

    run_start = datetime.now(timezone.utc)
    _log("pipeline_run_start", None, "success",
         f"Starting {run_type} pipeline run. Sources: {source_names}")

    # Stage 1: Source leads
    source_runners = {
        "apollo": run_apollo_source,
        "google_maps": run_google_maps_source,
        "yelp": run_yelp_source,
        "facebook": run_facebook_source,
    }

    all_leads = []
    leads_by_channel = {}

    for source_name in source_names:
        runner = source_runners.get(source_name)
        if not runner:
            _log("pipeline_unknown_source", None, "failure",
                 f"Unknown source: {source_name}")
            continue

        _log("pipeline_source_start", None, "success",
             f"Running source: {source_name}")
        try:
            source_leads = runner()
            all_leads.extend(source_leads)
            leads_by_channel[source_name] = len(source_leads)
            _log("pipeline_source_complete", None, "success",
                 f"Source {source_name}: {len(source_leads)} leads")
        except Exception as e:
            leads_by_channel[source_name] = 0
            _log("pipeline_source_error", None, "failure",
                 f"Source {source_name} failed: {str(e)}")

    _log("pipeline_sourcing_complete", None, "success",
         f"All sources complete. Total raw leads: {len(all_leads)}. "
         f"By channel: {json.dumps(leads_by_channel)}")

    # Stage 2: Enrich leads with Groq/Llama (employee count, website tech signals)
    enriched_count = 0
    if groq_api_key:
        for i, lead in enumerate(all_leads):
            # Rate limit enrichment to avoid Groq throttling
            if i > 0 and i % 10 == 0:
                time.sleep(1.0)
            all_leads[i] = _groq_enrich_lead(lead, groq_api_key, groq_model)
            enriched_count += 1
    else:
        _log("pipeline_enrichment_skipped", None, "skipped",
             "GROQ_API_KEY not set, skipping LLM enrichment")

    # Stage 3: Score leads (DETERMINISTIC)
    score_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for lead in all_leads:
        lead["lead_score"] = score_lead(lead, config)
        s = lead["lead_score"]
        if s in score_distribution:
            score_distribution[s] += 1

    qualified_leads = [l for l in all_leads if l["lead_score"] >= min_score]
    rejected_leads = [l for l in all_leads if l["lead_score"] < min_score]

    _log("pipeline_scoring_complete", None, "success",
         f"Scoring complete. Distribution: {json.dumps(score_distribution)}. "
         f"Qualified (>={min_score}): {len(qualified_leads)}, "
         f"Rejected: {len(rejected_leads)}")

    # Log each rejected lead
    for lead in rejected_leads:
        _log("pipeline_lead_rejected", None, "rejected",
             f"Score {lead['lead_score']} < {min_score}: "
             f"{lead.get('company_name', 'unknown')} ({lead.get('source', 'unknown')})")

    # Stage 4: Send qualified leads to CRM engine (dedup + store)
    crm_results = {"inserted": 0, "merged": 0, "suppressed": 0, "below_threshold": 0, "error": 0}

    try:
        crm_insert = _get_crm_engine()
    except ImportError as e:
        _log("pipeline_crm_import_error", None, "failure",
             f"Could not import CRM engine: {str(e)}")
        crm_insert = None

    if crm_insert:
        for lead in qualified_leads:
            lead["source_skill"] = "lead-pipeline"
            try:
                result = crm_insert(lead)
                status = result.get("status", "error")
                crm_results[status] = crm_results.get(status, 0) + 1
                if result.get("lead_id"):
                    _log("pipeline_crm_insert", result["lead_id"], "success",
                         f"CRM result: {status} for {lead.get('company_name', 'unknown')}")
            except Exception as e:
                crm_results["error"] += 1
                _log("pipeline_crm_error", None, "failure",
                     f"CRM insert failed for {lead.get('company_name', 'unknown')}: {str(e)}")
    else:
        _log("pipeline_crm_unavailable", None, "failure",
             f"CRM engine not available. {len(qualified_leads)} qualified leads could not be stored.")

    # Stage 5: Build run summary
    run_end = datetime.now(timezone.utc)
    duration_seconds = (run_end - run_start).total_seconds()

    summary = {
        "run_type": run_type,
        "run_start": run_start.isoformat(),
        "run_end": run_end.isoformat(),
        "duration_seconds": round(duration_seconds, 1),
        "leads_by_channel": leads_by_channel,
        "total_raw_leads": len(all_leads),
        "enriched_count": enriched_count,
        "score_distribution": score_distribution,
        "qualified_leads": len(qualified_leads),
        "rejected_leads": len(rejected_leads),
        "crm_results": crm_results,
        "duplicates_found": crm_results.get("merged", 0),
    }

    _log("pipeline_run_complete", None, "success",
         f"Pipeline run complete in {duration_seconds:.1f}s. "
         f"Raw: {len(all_leads)}, Qualified: {len(qualified_leads)}, "
         f"Inserted: {crm_results['inserted']}, Merged: {crm_results['merged']}, "
         f"Suppressed: {crm_results['suppressed']}")

    # Write daily output log
    _write_daily_output(summary)

    return summary


def _write_daily_output(summary: dict):
    """Write the daily output summary to the log for reporting."""
    output_dir = os.path.join(PROJECT_ROOT, "data")
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = os.path.join(output_dir, f"lead_pipeline_output_{date_str}.json")

    # Append to existing daily output if multiple runs in a day
    existing_outputs = []
    if os.path.exists(output_path):
        with open(output_path, "r") as f:
            try:
                existing_outputs = json.load(f)
                if not isinstance(existing_outputs, list):
                    existing_outputs = [existing_outputs]
            except json.JSONDecodeError:
                existing_outputs = []

    existing_outputs.append(summary)
    with open(output_path, "w") as f:
        json.dump(existing_outputs, f, indent=2)

    _log("pipeline_daily_output_written", None, "success",
         f"Daily output written to {output_path}")


def run_full_pipeline() -> dict:
    """
    Run the complete pipeline with all sources.
    Used for manual/testing runs.
    """
    return _run_pipeline(["apollo", "google_maps", "yelp", "facebook"], "full")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "daily":
            result = run_daily_sources()
        elif mode == "facebook":
            result = run_facebook_pipeline()
        elif mode == "full":
            result = run_full_pipeline()
        else:
            print(f"Unknown mode: {mode}. Use: daily, facebook, or full")
            sys.exit(1)
    else:
        result = run_full_pipeline()

    print(json.dumps(result, indent=2))
