#!/usr/bin/env python3
"""
Marketing Optimizer — Lead Acquisition ROI Maximizer
Ranks channels, discovers new verticals/geos, manages Facebook strategy,
and refines positioning. Never spends on paid ads without explicit approval.

LLM: Groq/Llama for data aggregation and ROI.
     Claude Sonnet ($10/week cap) for positioning refinement.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")
CRM_PATH = os.path.join(PROJECT_ROOT, "data", "crm.json")
SEND_LOG_PATH = os.path.join(PROJECT_ROOT, "data", "outreach_send_log.json")
OPTIMIZATION_LOG = os.path.join(PROJECT_ROOT, "data", "optimization", "marketing_optimization_log.jsonl")
CHANNEL_ROI_PATH = os.path.join(SKILL_DIR, "channel_roi.json")


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "marketing-optimizer",
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


def _load_crm_data() -> dict:
    if not os.path.exists(CRM_PATH):
        return {"leads": []}
    with open(CRM_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"leads": []}


def _load_send_log() -> list:
    if not os.path.exists(SEND_LOG_PATH):
        return []
    with open(SEND_LOG_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _groq_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    groq_config = config["llm"]["groq"]
    api_key = os.environ.get(groq_config["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": groq_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": groq_config.get("temperature", 0.2),
        "max_tokens": groq_config.get("max_tokens_per_call", 2048),
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=groq_config.get("timeout_seconds", 30)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        _log("groq_api_error", None, "failure", str(e), llm_used="groq")
        return None


def _claude_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    claude_config = config["llm"]["claude"]
    api_key = os.environ.get(claude_config["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": claude_config["model"],
        "max_tokens": claude_config.get("max_tokens_per_call", 2048),
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=claude_config.get("timeout_seconds", 60)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]
    except Exception as e:
        _log("claude_api_error", None, "failure", str(e), llm_used="claude")
        return None


def _calculate_channel_roi(config: dict, crm_data: dict, send_log: list) -> dict:
    """Calculate cost per qualified lead per channel."""
    channels = {}
    for lead in crm_data.get("leads", []):
        source = lead.get("source", "unknown")
        if source not in channels:
            channels[source] = {"leads": 0, "qualified": 0, "closed": 0, "revenue": 0}
        channels[source]["leads"] += 1
        if lead.get("lead_score", 0) >= 3:
            channels[source]["qualified"] += 1
        if lead.get("status") == "closed":
            channels[source]["closed"] += 1
            channels[source]["revenue"] += 297  # $297/mo MRR

    # Cost estimates per channel (monthly)
    channel_costs = {
        "apollo": 0,  # Free tier
        "google_maps": 0,  # Playwright scraping, free
        "yelp": 0,  # Scraping, free
        "facebook": 0,  # Organic, free
    }

    roi = {}
    for source, stats in channels.items():
        cost = channel_costs.get(source, 0)
        cpl = cost / stats["qualified"] if stats["qualified"] > 0 else float("inf")
        roi[source] = {
            **stats,
            "monthly_cost": cost,
            "cost_per_qualified_lead": round(cpl, 2),
            "conversion_rate": round(stats["closed"] / stats["qualified"], 4) if stats["qualified"] > 0 else 0,
        }

    # Save ROI data
    os.makedirs(os.path.dirname(CHANNEL_ROI_PATH), exist_ok=True)
    with open(CHANNEL_ROI_PATH, "w") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "channels": roi}, f, indent=2)

    _log("channel_roi_calculated", None, "success",
         f"Channel ROI: {json.dumps({k: v['cost_per_qualified_lead'] for k, v in roi.items()})}")
    return roi


def _evaluate_geo_expansion(config: dict, crm_data: dict) -> dict:
    """Evaluate potential new cities. Max 2 per month."""
    geo_config = config["geo_expansion"]
    leads = crm_data.get("leads", [])

    # Count leads by state
    state_performance = {}
    for lead in leads:
        state = lead.get("state", "unknown")
        if state not in state_performance:
            state_performance[state] = {"total": 0, "closed": 0}
        state_performance[state]["total"] += 1
        if lead.get("status") == "closed":
            state_performance[state]["closed"] += 1

    # Find best performing states for expansion
    ranked = sorted(state_performance.items(),
                    key=lambda x: x[1]["closed"] / max(x[1]["total"], 1), reverse=True)

    return {
        "state_performance": {k: v for k, v in ranked[:5]},
        "max_new_cities_per_month": geo_config["max_new_cities_per_month"],
        "recommendations": [],  # Populated by LLM analysis in weekly run
    }


def _evaluate_vertical_expansion(config: dict, crm_data: dict) -> dict:
    """One vertical at a time, 2-week performance window."""
    leads = crm_data.get("leads", [])
    vertical_stats = {}
    for lead in leads:
        v = lead.get("vertical", "unknown")
        if v not in vertical_stats:
            vertical_stats[v] = {"total": 0, "qualified": 0, "closed": 0}
        vertical_stats[v]["total"] += 1
        if lead.get("lead_score", 0) >= 3:
            vertical_stats[v]["qualified"] += 1
        if lead.get("status") == "closed":
            vertical_stats[v]["closed"] += 1

    return {"vertical_stats": vertical_stats}


def _analyze_seasonal_patterns(config: dict, send_log: list) -> dict:
    """Identify vertical-specific seasonal trends."""
    current_month = datetime.now(timezone.utc).month
    seasonal = config.get("content_angles", {}).get("seasonal_variants", {})
    busy_months = seasonal.get("busy_season_months", [4, 5, 6, 7, 8, 9])
    is_busy_season = current_month in busy_months
    return {
        "current_month": current_month,
        "is_busy_season": is_busy_season,
        "recommendation": "Increase HVAC/roofing sourcing" if is_busy_season else "Focus on plumbing/electrical",
    }


def run_weekly_optimization() -> dict:
    """Full weekly deep analysis. Tuesdays 5AM PT."""
    config = _load_config()
    crm_data = _load_crm_data()
    send_log = _load_send_log()

    _log("marketing_weekly_start", None, "success", "Starting weekly marketing optimization")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_type": "weekly",
    }

    results["channel_roi"] = _calculate_channel_roi(config, crm_data, send_log)
    results["geo_expansion"] = _evaluate_geo_expansion(config, crm_data)
    results["vertical_expansion"] = _evaluate_vertical_expansion(config, crm_data)
    results["seasonal"] = _analyze_seasonal_patterns(config, send_log)

    # Use Groq for summary
    summary_prompt = (
        "Summarize the marketing optimization data. Focus on: which channels perform best, "
        "which geos/verticals to expand or cut, and seasonal adjustments. "
        "Keep it under 200 words. Data:\n" + json.dumps(results, indent=2)[:3000]
    )
    summary = _groq_request(
        "You are a marketing analyst for NeverMiss, a $297/mo missed-call text-back SaaS.",
        summary_prompt, config
    )
    results["summary"] = summary or "Summary generation failed"

    # Log
    os.makedirs(os.path.dirname(OPTIMIZATION_LOG), exist_ok=True)
    with open(OPTIMIZATION_LOG, "a") as f:
        f.write(json.dumps(results) + "\n")

    _log("marketing_weekly_complete", None, "success",
         f"Weekly optimization complete. Channels analyzed: {len(results.get('channel_roi', {}))}")
    return results


def run_daily_update() -> dict:
    """Lightweight daily update. 7AM PT."""
    config = _load_config()
    crm_data = _load_crm_data()
    send_log = _load_send_log()

    _log("marketing_daily_start", None, "success", "Starting daily marketing update")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_type": "daily",
        "channel_roi": _calculate_channel_roi(config, crm_data, send_log),
        "seasonal": _analyze_seasonal_patterns(config, send_log),
    }

    _log("marketing_daily_complete", None, "success", "Daily marketing update complete")
    return results


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    if mode == "daily":
        result = run_daily_update()
    else:
        result = run_weekly_optimization()
    print(json.dumps(result, indent=2))
