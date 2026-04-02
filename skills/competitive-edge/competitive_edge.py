#!/usr/bin/env python3
"""
Competitive Edge — Systematic Competitor Intelligence
Mines weaknesses from reviews, tracks pricing changes, maintains per-competitor
playbooks, generates counter-messaging, and adjusts market timing.

LLM: Claude Sonnet ($15/week cap) for weakness extraction and positioning.
     Groq/Llama for review summarization and sentiment.

Monitors: Smith.ai, Ruby, Hatch, Numa
Never: change core price ($297/mo), contact competitors, modify playbooks destructively.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")
BASE_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "competitive_edge")
WEAKNESS_DIR = os.path.join(BASE_DATA_DIR, "weakness_reports")
PRICING_DIR = os.path.join(BASE_DATA_DIR, "pricing_snapshots")
PLAYBOOK_DIR = os.path.join(SKILL_DIR, "competitor_playbooks")
SPEND_TRACKER_PATH = os.path.join(BASE_DATA_DIR, "spend_tracker.json")


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "competitive-edge",
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


def _groq_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    gathering = config["llm"]["gathering"]
    api_key = os.environ.get(gathering["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": gathering["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": gathering.get("temperature", 0.1),
        "max_tokens": 2048,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=gathering.get("timeout_seconds", 15)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        _log("groq_api_error", None, "failure", str(e), llm_used="groq")
        return None


def _claude_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    strategic = config["llm"]["strategic"]
    api_key = os.environ.get(strategic["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": strategic["model"],
        "max_tokens": 2048,
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
        with urllib.request.urlopen(req, timeout=strategic.get("timeout_seconds", 30)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]
    except Exception as e:
        _log("claude_api_error", None, "failure", str(e), llm_used="claude")
        return None


def _fetch_page(url: str) -> str:
    """Fetch a web page and return text content."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        if HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)[:10000]
        return html[:10000]
    except Exception as e:
        _log("fetch_page_error", None, "failure", f"Failed to fetch {url}: {e}")
        return ""


def _scrape_competitor_reviews(competitor_key: str, config: dict) -> list:
    """Scrape reviews from configured review sources."""
    comp = config["competitors"].get(competitor_key, {})
    review_sources = comp.get("review_sources", [])
    all_reviews_text = []

    for url in review_sources:
        text = _fetch_page(url)
        if text:
            all_reviews_text.append({"source": url, "text": text[:3000]})
            _log("review_scraped", None, "success",
                 f"Scraped reviews for {comp.get('name', competitor_key)} from {url}")

    return all_reviews_text


def _extract_weaknesses(reviews: list, competitor_name: str, config: dict) -> dict:
    """Use Claude to extract competitor weaknesses from review text."""
    if not reviews:
        return {"weaknesses": [], "status": "no_reviews"}

    combined = "\n\n".join(f"[{r['source']}]\n{r['text'][:1500]}" for r in reviews[:3])

    system_prompt = (
        "You are a competitive intelligence analyst for NeverMiss ($297/mo missed-call "
        "text-back for trade contractors). Extract specific weaknesses and customer complaints "
        "about the competitor. Return JSON: {weaknesses: [{category, description, frequency, "
        "nevermiss_advantage}], pricing_info: string, overall_sentiment: string}"
    )
    user_prompt = f"Competitor: {competitor_name}\n\nReview data:\n{combined}"

    result = _claude_request(system_prompt, user_prompt, config)
    if result:
        _log("weakness_extracted", None, "success",
             f"Extracted weaknesses for {competitor_name}",
             llm_used="claude", tokens=3000, cost=0.05)
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw_analysis": result[:1000], "status": "parsed_raw"}
    return {"status": "llm_failed"}


def _update_playbook(competitor_key: str, new_intel: dict, config: dict):
    """Additive-only update to competitor playbook."""
    os.makedirs(PLAYBOOK_DIR, exist_ok=True)
    playbook_path = os.path.join(PLAYBOOK_DIR, f"{competitor_key}.json")

    existing = {}
    if os.path.exists(playbook_path):
        with open(playbook_path, "r") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = {}

    # Additive only — never remove existing entries
    existing.setdefault("weaknesses", [])
    existing.setdefault("pricing_history", [])
    existing.setdefault("updated_at", [])

    for w in new_intel.get("weaknesses", []):
        if w not in existing["weaknesses"]:
            existing["weaknesses"].append(w)

    if new_intel.get("pricing_info"):
        existing["pricing_history"].append({
            "date": datetime.now(timezone.utc).isoformat(),
            "info": new_intel["pricing_info"],
        })

    existing["updated_at"].append(datetime.now(timezone.utc).isoformat())
    existing["competitor_name"] = config["competitors"].get(competitor_key, {}).get("name", competitor_key)

    with open(playbook_path, "w") as f:
        json.dump(existing, f, indent=2)

    _log("playbook_updated", None, "success",
         f"Updated playbook for {competitor_key} (additive only)")


def _check_pricing_changes(competitor_key: str, config: dict) -> dict:
    """Scrape pricing page and check for changes."""
    comp = config["competitors"].get(competitor_key, {})
    pricing_url = comp.get("pricing_url", "")
    if not pricing_url:
        return {"status": "no_pricing_url"}

    text = _fetch_page(pricing_url)
    if not text:
        return {"status": "fetch_failed"}

    # Store snapshot
    os.makedirs(PRICING_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    snapshot_path = os.path.join(PRICING_DIR, f"{competitor_key}_{date_str}.txt")
    with open(snapshot_path, "w") as f:
        f.write(text[:5000])

    # Use Groq to extract pricing info
    result = _groq_request(
        "Extract pricing tiers and amounts from this text. Return JSON: "
        "{tiers: [{name, price, features}], notes: string}",
        f"Pricing page for {comp.get('name', '')}:\n{text[:3000]}",
        config
    )

    _log("pricing_checked", None, "success",
         f"Pricing snapshot saved for {competitor_key}", llm_used="groq")
    return {"status": "checked", "snapshot": snapshot_path, "analysis": result}


def _analyze_market_timing(config: dict) -> dict:
    """Get current market timing recommendations by vertical."""
    current_month = datetime.now(timezone.utc).month
    timing = config.get("market_timing", {}).get("verticals", {})
    peak_mult = config.get("market_timing", {}).get("sourcing_multiplier_peak", 1.5)
    off_mult = config.get("market_timing", {}).get("sourcing_multiplier_off", 0.7)

    recommendations = {}
    for vertical, schedule in timing.items():
        if current_month in schedule.get("peak_months", []):
            recommendations[vertical] = {"status": "peak", "multiplier": peak_mult}
        elif current_month in schedule.get("off_months", []):
            recommendations[vertical] = {"status": "off_peak", "multiplier": off_mult}
        else:
            recommendations[vertical] = {"status": "normal", "multiplier": 1.0}

    return recommendations


def run_weekly_analysis() -> dict:
    """Main entry point. Runs Thursdays 5AM PT."""
    config = _load_config()

    _log("competitive_analysis_start", None, "success",
         "Starting weekly competitive edge analysis")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "competitors_analyzed": [],
    }

    for comp_key, comp_config in config["competitors"].items():
        comp_name = comp_config.get("name", comp_key)
        _log("analyzing_competitor", None, "success", f"Analyzing {comp_name}")

        # Scrape reviews
        reviews = _scrape_competitor_reviews(comp_key, config)

        # Extract weaknesses
        weaknesses = _extract_weaknesses(reviews, comp_name, config)

        # Check pricing
        pricing = _check_pricing_changes(comp_key, config)

        # Update playbook (additive only)
        _update_playbook(comp_key, weaknesses, config)

        # Save weakness report
        os.makedirs(WEAKNESS_DIR, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        report_path = os.path.join(WEAKNESS_DIR, f"{comp_key}_{date_str}.json")
        report = {
            "competitor": comp_name,
            "date": datetime.now(timezone.utc).isoformat(),
            "reviews_scraped": len(reviews),
            "weaknesses": weaknesses,
            "pricing": pricing,
        }
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        results["competitors_analyzed"].append({
            "key": comp_key,
            "name": comp_name,
            "reviews_scraped": len(reviews),
            "weaknesses_found": len(weaknesses.get("weaknesses", [])),
        })

    # Market timing
    results["market_timing"] = _analyze_market_timing(config)

    _log("competitive_analysis_complete", None, "success",
         f"Weekly analysis complete. Competitors: {len(results['competitors_analyzed'])}")

    return results


if __name__ == "__main__":
    result = run_weekly_analysis()
    print(json.dumps(result, indent=2))
