#!/usr/bin/env python3
"""
Market Intel — Competitor and Market Research Intelligence

Tracks competitor pricing, positioning, contractor community language patterns,
and generates competitive positioning documents. Feeds intelligence to
performance-engine and email-optimizer for messaging refinement.

LLM: Groq/Llama 3.1 70B for all analysis. NO Claude usage.
HTTP: urllib.request for fetching, BeautifulSoup for HTML parsing.
"""

import argparse
import json
import os
import re
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

# Data directories (resolved from config at load time)
COMPETITORS_DIR = os.path.join(PROJECT_ROOT, "data", "market_research", "competitors")
POSITIONING_DIR = os.path.join(PROJECT_ROOT, "data", "market_research", "positioning")
VERTICALS_DIR = os.path.join(PROJECT_ROOT, "data", "market_research", "verticals")
MESSAGING_DIR = os.path.join(PROJECT_ROOT, "data", "market_research", "messaging")

# Groq cost estimates
GROQ_COST_PER_1K_INPUT = 0.00059
GROQ_COST_PER_1K_OUTPUT = 0.00079
AVG_ANALYSIS_INPUT_TOKENS = 1500
AVG_ANALYSIS_OUTPUT_TOKENS = 800

# HTTP request settings
HTTP_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(action: str, target: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    """Append a structured log entry to data/system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "market-intel",
        "action": action,
        "target": target,
        "result": result,
        "details": details,
        "llm_used": llm_used,
        "tokens_estimated": tokens,
        "cost_estimated": cost,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load skill config from config.json."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _ensure_dirs():
    """Create all required data directories."""
    for d in [COMPETITORS_DIR, POSITIONING_DIR, VERTICALS_DIR, MESSAGING_DIR]:
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# HTTP / Scraping
# ---------------------------------------------------------------------------

def _scrape_competitor_page(url: str) -> str:
    """
    Fetch a competitor page via urllib and extract visible text with
    BeautifulSoup. Returns extracted text or empty string on failure.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, nav, footer elements for cleaner text
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # Collapse multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Truncate to ~15k chars to stay within LLM context limits
        return text[:15000]

    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        _log("scrape_page", url, "error", f"Failed to fetch: {e}")
        return ""
    except Exception as e:
        _log("scrape_page", url, "error", f"Unexpected scrape error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Groq / LLM
# ---------------------------------------------------------------------------

def _groq_call(system_prompt: str, user_prompt: str, config: dict,
               max_tokens: int = 2048) -> tuple[Optional[str], int, float]:
    """
    Call Groq chat completions API. Returns (content, tokens, cost).
    Returns (None, 0, 0.0) on failure.
    """
    api_key = os.environ.get(config["llm"]["api_key_env"], "")
    if not api_key:
        _log("groq_call", None, "error",
             f"Missing env var {config['llm']['api_key_env']}")
        return None, 0, 0.0

    model = config["llm"]["model"]
    temperature = config["llm"].get("temperature", 0.1)

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

        content = response_data["choices"][0]["message"]["content"]
        usage = response_data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", AVG_ANALYSIS_INPUT_TOKENS)
        output_tokens = usage.get("completion_tokens", AVG_ANALYSIS_OUTPUT_TOKENS)
        total_tokens = input_tokens + output_tokens
        cost = (
            (input_tokens / 1000) * GROQ_COST_PER_1K_INPUT
            + (output_tokens / 1000) * GROQ_COST_PER_1K_OUTPUT
        )
        return content, total_tokens, cost

    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        _log("groq_call", None, "error", f"Groq API error: {e}")
        return None, 0, 0.0
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        _log("groq_call", None, "error", f"Groq response parse error: {e}")
        return None, 0, 0.0


# ---------------------------------------------------------------------------
# Competitor Analysis
# ---------------------------------------------------------------------------

def _analyze_competitor(name: str, page_text: str, config: dict) -> Optional[dict]:
    """
    Use Groq/Llama to extract pricing tiers, value proposition, weaknesses,
    and customer complaints from scraped competitor page text.
    Returns parsed JSON dict or None on failure.
    """
    if not page_text.strip():
        _log("analyze_competitor", name, "skipped", "No page text to analyze")
        return None

    system_prompt = (
        "You are a competitive intelligence analyst for a SaaS company that provides "
        "AI-powered phone answering for home service contractors. Analyze the competitor's "
        "pricing page text and extract structured intelligence. "
        "Respond ONLY with valid JSON.\n\n"
        "Required JSON fields:\n"
        '- "pricing_tiers": array of objects, each with "name", "price" (string), '
        '"billing_period", and "features" (array of strings)\n'
        '- "value_proposition": string summarizing their core value prop\n'
        '- "target_audience": string describing who they target\n'
        '- "weaknesses": array of strings — potential weaknesses or gaps based on what '
        "you can infer from their positioning\n"
        '- "competitive_notes": string — how our AI phone answering service could '
        "position against them\n"
        '- "last_known_pricing_change": string or null — any indication of recent changes\n'
        '- "confidence": "high", "medium", or "low" — how confident you are in the '
        "extracted pricing data"
    )

    user_prompt = (
        f"Competitor: {name}\n\n"
        f"--- Page Text ---\n{page_text}\n--- End ---\n\n"
        "Extract pricing tiers, value proposition, weaknesses, and competitive notes."
    )

    content, tokens, cost = _groq_call(system_prompt, user_prompt, config)
    if content is None:
        _log("analyze_competitor", name, "error", "Groq call failed")
        return None

    try:
        data = json.loads(content)
        _log("analyze_competitor", name, "success",
             f"Extracted {len(data.get('pricing_tiers', []))} pricing tiers",
             llm_used=f"groq/{config['llm']['model']}", tokens=tokens, cost=cost)
        return data
    except json.JSONDecodeError as e:
        _log("analyze_competitor", name, "error",
             f"Failed to parse Groq response as JSON: {e}")
        return None


def _update_competitor_profile(name: str, data: dict, config: dict):
    """
    Write or update competitor profile to data/market_research/competitors/{slug}.json.
    Merges new data with existing profile, preserving history.
    """
    # Find the competitor config entry
    comp_config = None
    for c in config["competitors"]:
        if c["name"] == name:
            comp_config = c
            break

    if comp_config is None:
        _log("update_profile", name, "error", "Competitor not found in config")
        return

    slug = comp_config["slug"]
    filepath = os.path.join(COMPETITORS_DIR, f"{slug}.json")

    # Load existing profile if present
    existing = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Build updated profile
    now = datetime.now(timezone.utc).isoformat()
    pricing_history = existing.get("pricing_history", [])

    # Add current pricing to history if it changed
    current_tiers = data.get("pricing_tiers", [])
    previous_tiers = existing.get("current_pricing_tiers", [])
    if current_tiers and current_tiers != previous_tiers:
        if previous_tiers:
            pricing_history.append({
                "date": existing.get("last_updated", now),
                "tiers": previous_tiers,
            })
        # Keep only last 12 entries in history
        pricing_history = pricing_history[-12:]

    profile = {
        "name": name,
        "slug": slug,
        "category": comp_config["category"],
        "website": comp_config["website"],
        "pricing_url": comp_config["pricing_url"],
        "last_updated": now,
        "current_pricing_tiers": current_tiers,
        "value_proposition": data.get("value_proposition", existing.get("value_proposition", "")),
        "target_audience": data.get("target_audience", existing.get("target_audience", "")),
        "weaknesses": data.get("weaknesses", existing.get("weaknesses", [])),
        "competitive_notes": data.get("competitive_notes", existing.get("competitive_notes", "")),
        "confidence": data.get("confidence", "low"),
        "pricing_history": pricing_history,
        "review_sources": comp_config.get("review_sources", []),
    }

    with open(filepath, "w") as f:
        json.dump(profile, f, indent=2)

    _log("update_profile", name, "success",
         f"Profile written to {filepath}")


# ---------------------------------------------------------------------------
# Positioning Document Generation
# ---------------------------------------------------------------------------

def _generate_positioning_doc(config: dict):
    """
    Generate competitive positioning documents for each category
    (vs_live_answering, vs_fsm_platforms, vs_basic_missed_call).
    Reads current competitor profiles and synthesizes positioning guidance.
    """
    categories = config.get("positioning_categories", {})

    for category_key, category_data in categories.items():
        competitor_slugs = category_data.get("competitors", [])
        advantages = category_data.get("nevermiss_advantages", [])

        # Load competitor profiles for this category
        competitor_summaries = []
        for slug in competitor_slugs:
            filepath = os.path.join(COMPETITORS_DIR, f"{slug}.json")
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r") as f:
                        profile = json.load(f)
                    competitor_summaries.append(
                        f"**{profile['name']}** ({profile.get('category', 'unknown')})\n"
                        f"  Value Prop: {profile.get('value_proposition', 'N/A')}\n"
                        f"  Pricing: {json.dumps(profile.get('current_pricing_tiers', []))}\n"
                        f"  Weaknesses: {', '.join(profile.get('weaknesses', []))}\n"
                    )
                except (json.JSONDecodeError, OSError):
                    continue

        if not competitor_summaries:
            _log("positioning_doc", category_key, "skipped",
                 "No competitor profiles available")
            continue

        system_prompt = (
            "You are a competitive positioning strategist for NeverMiss.ai, an AI-powered "
            "phone answering service for home service contractors. Generate a competitive "
            "positioning document. Respond ONLY with valid JSON.\n\n"
            "Required JSON fields:\n"
            '- "category": string — the competitive category\n'
            '- "headline": string — one-line positioning statement\n'
            '- "key_differentiators": array of strings — top 5 differentiators\n'
            '- "objection_handlers": array of objects with "objection" and "response" fields\n'
            '- "talk_tracks": array of strings — 3-5 talk tracks for sales conversations\n'
            '- "email_angles": array of strings — 3-5 angles for outreach emails\n'
            '- "pricing_comparison": string — summary of how our pricing compares\n'
            '- "when_we_lose": string — honest assessment of when competitors win\n'
        )

        advantages_str = ", ".join(a.replace("_", " ") for a in advantages)
        user_prompt = (
            f"Category: {category_key.replace('_', ' ')}\n"
            f"Our known advantages: {advantages_str}\n\n"
            f"Competitor Intelligence:\n{''.join(competitor_summaries)}\n\n"
            "Generate a competitive positioning document for our sales team."
        )

        content, tokens, cost = _groq_call(system_prompt, user_prompt, config)
        if content is None:
            _log("positioning_doc", category_key, "error", "Groq call failed")
            continue

        try:
            doc = json.loads(content)
            doc["generated_at"] = datetime.now(timezone.utc).isoformat()
            doc["competitors_analyzed"] = competitor_slugs

            filepath = os.path.join(POSITIONING_DIR, f"{category_key}.json")
            with open(filepath, "w") as f:
                json.dump(doc, f, indent=2)

            _log("positioning_doc", category_key, "success",
                 f"Positioning doc written to {filepath}",
                 llm_used=f"groq/{config['llm']['model']}", tokens=tokens, cost=cost)

        except json.JSONDecodeError as e:
            _log("positioning_doc", category_key, "error",
                 f"Failed to parse positioning doc JSON: {e}")


# ---------------------------------------------------------------------------
# Forum / Language Monitoring
# ---------------------------------------------------------------------------

def _monitor_language_patterns(vertical: str, config: dict):
    """
    Monitor contractor community language patterns for a given vertical.
    Searches Reddit and aggregates language patterns contractors use when
    discussing phone issues, missed calls, and answering services.
    Stores findings in data/market_research/verticals/{vertical}.json.
    """
    search_phrases = config.get("forum_monitoring", {}).get("search_phrases", [])
    subreddits = config.get("forum_monitoring", {}).get("reddit_subreddits", [])

    # Build search queries combining vertical + pain-point phrases
    collected_text = []
    for phrase in search_phrases[:6]:  # Limit to avoid rate limiting
        query = f"{vertical.replace('_', ' ')} {phrase}"
        search_url = (
            f"https://www.reddit.com/search.json?"
            f"q={urllib.request.quote(query)}&sort=new&limit=10&t=week"
        )

        try:
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": USER_AGENT},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            posts = data.get("data", {}).get("children", [])
            for post in posts:
                post_data = post.get("data", {})
                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")[:500]
                subreddit = post_data.get("subreddit", "")
                collected_text.append(
                    f"[r/{subreddit}] {title}\n{selftext}"
                )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
            continue

        # Small delay to be respectful of rate limits
        time.sleep(1)

    if not collected_text:
        _log("language_monitor", vertical, "skipped",
             "No forum posts collected")
        return

    # Use Groq to extract language patterns
    system_prompt = (
        "You are a market research analyst studying how home service contractors "
        "talk about phone management problems. Analyze the following forum posts and "
        "extract language patterns. Respond ONLY with valid JSON.\n\n"
        "Required JSON fields:\n"
        '- "pain_point_phrases": array of strings — exact phrases contractors use to '
        "describe missed call / phone problems\n"
        '- "emotional_language": array of strings — emotional words and phrases used\n'
        '- "competitor_mentions": array of objects with "name" and "sentiment" fields\n'
        '- "common_objections": array of strings — objections to answering services or AI\n'
        '- "buying_triggers": array of strings — what events push contractors to seek solutions\n'
        '- "terminology": array of strings — industry-specific terms and jargon used\n'
        '- "sample_quotes": array of strings — 3-5 representative quotes from the posts\n'
    )

    user_prompt = (
        f"Vertical: {vertical.replace('_', ' ')}\n\n"
        f"--- Forum Posts ({len(collected_text)} collected) ---\n"
        f"{chr(10).join(collected_text[:20])}\n"  # Limit to 20 posts
        f"--- End ---\n\n"
        "Extract contractor language patterns related to phone and call management."
    )

    content, tokens, cost = _groq_call(system_prompt, user_prompt, config)
    if content is None:
        _log("language_monitor", vertical, "error", "Groq analysis failed")
        return

    try:
        patterns = json.loads(content)
    except json.JSONDecodeError as e:
        _log("language_monitor", vertical, "error",
             f"Failed to parse language patterns JSON: {e}")
        return

    # Load existing vertical file and merge
    filepath = os.path.join(VERTICALS_DIR, f"{vertical}.json")
    existing = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    now = datetime.now(timezone.utc).isoformat()

    # Merge: append new patterns to existing lists, deduplicate
    def _merge_lists(key):
        old = existing.get(key, [])
        new = patterns.get(key, [])
        if isinstance(new, list) and isinstance(old, list):
            combined = old + [item for item in new if item not in old]
            return combined[-50:]  # Cap at 50 entries
        return new if new else old

    vertical_data = {
        "vertical": vertical,
        "last_updated": now,
        "pain_point_phrases": _merge_lists("pain_point_phrases"),
        "emotional_language": _merge_lists("emotional_language"),
        "competitor_mentions": patterns.get("competitor_mentions",
                                            existing.get("competitor_mentions", [])),
        "common_objections": _merge_lists("common_objections"),
        "buying_triggers": _merge_lists("buying_triggers"),
        "terminology": _merge_lists("terminology"),
        "sample_quotes": patterns.get("sample_quotes",
                                      existing.get("sample_quotes", [])),
        "posts_analyzed_total": existing.get("posts_analyzed_total", 0) + len(collected_text),
    }

    with open(filepath, "w") as f:
        json.dump(vertical_data, f, indent=2)

    _log("language_monitor", vertical, "success",
         f"Updated vertical patterns for {vertical} "
         f"({len(collected_text)} posts analyzed)",
         llm_used=f"groq/{config['llm']['model']}", tokens=tokens, cost=cost)


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------

def run_weekly_refresh():
    """
    Main weekly entry point — Sundays 6AM PT.
    For each of 8 competitors: scrape pricing, extract intelligence, store profile.
    Then generate competitive positioning documents.
    """
    _log("weekly_refresh", None, "started", "Beginning full weekly competitor refresh")
    config = _load_config()
    _ensure_dirs()

    total_tokens = 0
    total_cost = 0.0
    success_count = 0
    error_count = 0

    for competitor in config["competitors"]:
        name = competitor["name"]
        pricing_url = competitor["pricing_url"]

        _log("weekly_refresh", name, "scraping", f"Fetching {pricing_url}")

        # Step 1: Scrape pricing page
        page_text = _scrape_competitor_page(pricing_url)
        if not page_text:
            # Try main website as fallback
            page_text = _scrape_competitor_page(competitor["website"])

        if not page_text:
            _log("weekly_refresh", name, "error",
                 "Could not scrape pricing or main page")
            error_count += 1
            continue

        # Step 2: Analyze with Groq/Llama
        analysis = _analyze_competitor(name, page_text, config)
        if analysis is None:
            error_count += 1
            continue

        # Step 3: Update competitor profile
        _update_competitor_profile(name, analysis, config)
        success_count += 1

        # Be polite with rate limits between competitors
        time.sleep(2)

    # Step 4: Generate positioning documents
    _log("weekly_refresh", None, "positioning",
         "Generating competitive positioning documents")
    _generate_positioning_doc(config)

    _log("weekly_refresh", None, "completed",
         f"Weekly refresh done: {success_count} succeeded, {error_count} failed "
         f"out of {len(config['competitors'])} competitors")


def run_daily_forum_monitor():
    """
    Daily entry point — 7AM PT.
    Track contractor community language patterns across verticals.
    Monitor keywords related to missed calls, phone issues, answering services.
    """
    _log("daily_monitor", None, "started",
         "Beginning daily forum and language monitoring")
    config = _load_config()
    _ensure_dirs()

    verticals_config = config.get("verticals", {})
    # Process Tier 1 verticals daily, Tier 2 on odd days, Tier 3 weekly
    day_of_week = datetime.now(timezone.utc).weekday()
    day_of_month = datetime.now(timezone.utc).day

    verticals_to_process = list(verticals_config.get("tier_1", []))

    if day_of_month % 2 == 1:
        verticals_to_process.extend(verticals_config.get("tier_2", []))

    if day_of_week == 0:  # Monday
        verticals_to_process.extend(verticals_config.get("tier_3", []))

    processed = 0
    for vertical in verticals_to_process:
        _log("daily_monitor", vertical, "processing",
             f"Monitoring language patterns for {vertical}")
        _monitor_language_patterns(vertical, config)
        processed += 1
        # Respect rate limits
        time.sleep(3)

    _log("daily_monitor", None, "completed",
         f"Daily monitoring done: {processed} verticals processed")


def run_competitor_check(name: str):
    """
    On-demand check for a single competitor.
    Scrapes, analyzes, and updates profile for the given competitor.
    """
    config = _load_config()
    _ensure_dirs()

    competitor = None
    for c in config["competitors"]:
        if c["name"].lower() == name.lower():
            competitor = c
            break

    if competitor is None:
        print(f"Error: Competitor '{name}' not found in config.")
        print("Available:", ", ".join(c["name"] for c in config["competitors"]))
        _log("competitor_check", name, "error", "Competitor not found in config")
        return

    _log("competitor_check", competitor["name"], "started",
         f"On-demand check for {competitor['name']}")

    page_text = _scrape_competitor_page(competitor["pricing_url"])
    if not page_text:
        page_text = _scrape_competitor_page(competitor["website"])

    if not page_text:
        print(f"Error: Could not scrape pages for {competitor['name']}")
        _log("competitor_check", competitor["name"], "error", "Scrape failed")
        return

    analysis = _analyze_competitor(competitor["name"], page_text, config)
    if analysis is None:
        print(f"Error: Analysis failed for {competitor['name']}")
        return

    _update_competitor_profile(competitor["name"], analysis, config)
    print(f"Updated profile for {competitor['name']}")
    _log("competitor_check", competitor["name"], "completed",
         "On-demand check finished")


def run_vertical_update(vertical: str):
    """
    On-demand language monitoring for a specific vertical.
    """
    config = _load_config()
    _ensure_dirs()

    all_verticals = []
    for tier in config.get("verticals", {}).values():
        all_verticals.extend(tier)

    if vertical not in all_verticals:
        print(f"Error: Vertical '{vertical}' not found in config.")
        print("Available:", ", ".join(all_verticals))
        _log("vertical_update", vertical, "error", "Vertical not found in config")
        return

    _log("vertical_update", vertical, "started",
         f"On-demand language monitoring for {vertical}")
    _monitor_language_patterns(vertical, config)
    print(f"Updated language patterns for {vertical}")
    _log("vertical_update", vertical, "completed",
         "On-demand vertical update finished")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Market Intel — Competitor and market research intelligence"
    )
    parser.add_argument("--weekly-refresh", action="store_true",
                        help="Run full weekly competitor pricing and positioning sweep")
    parser.add_argument("--daily-monitor", action="store_true",
                        help="Run daily forum and language monitoring")
    parser.add_argument("--competitor-check", action="store_true",
                        help="On-demand check for a single competitor")
    parser.add_argument("--name", type=str,
                        help="Competitor name (used with --competitor-check)")
    parser.add_argument("--vertical-update", action="store_true",
                        help="On-demand language monitoring for a vertical")
    parser.add_argument("--vertical", type=str,
                        help="Vertical slug (used with --vertical-update)")

    args = parser.parse_args()

    if args.weekly_refresh:
        run_weekly_refresh()
    elif args.daily_monitor:
        run_daily_forum_monitor()
    elif args.competitor_check:
        if not args.name:
            parser.error("--competitor-check requires --name")
        run_competitor_check(args.name)
    elif args.vertical_update:
        if not args.vertical:
            parser.error("--vertical-update requires --vertical")
        run_vertical_update(args.vertical)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
