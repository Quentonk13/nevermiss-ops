#!/usr/bin/env python3
"""
Competitor Monitor — Track competitor websites for pricing, features, content changes.
Stores snapshots in data/competitor_snapshots/{competitor}/{date}.json.
Detects changes between snapshots and flags new features, pricing changes.
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
sys.path.insert(0, SKILL_DIR)

from browser_agent import navigate_to, take_screenshot, BrowserSession, RATE_LIMITER
from browser_utils import (
    log_action, validate_url, extract_domain, CacheManager,
    _load_config, DATA_DIR
)

CONFIG = _load_config()
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "competitor_snapshots")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.0):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "competitor-monitor",
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


def _extract_pricing(text: str, html: str) -> list:
    """Extract pricing information from page content."""
    pricing = []
    price_patterns = [
        r'\$(\d[\d,]*(?:\.\d{2})?)\s*(?:/\s*)?(?:per\s+)?(?:month|mo|monthly)',
        r'\$(\d[\d,]*(?:\.\d{2})?)\s*(?:/\s*)?(?:per\s+)?(?:year|yr|annually)',
        r'(\d[\d,]*(?:\.\d{2})?)\s*(?:/\s*)?(?:mo(?:nth)?|yr|year)',
        r'(?:starting at|from|as low as)\s*\$(\d[\d,]*(?:\.\d{2})?)',
        r'(?:plan|tier|package)[^$]*\$(\d[\d,]*(?:\.\d{2})?)',
    ]

    for pattern in price_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            full_match = match.group(0).strip()
            amount = match.group(1).replace(",", "")
            try:
                amount_float = float(amount)
                if 1 <= amount_float <= 50000:
                    pricing.append({
                        "amount": amount_float,
                        "context": full_match[:200],
                        "period": "monthly" if re.search(r'mo(?:nth)?', full_match, re.IGNORECASE) else "yearly" if re.search(r'yr|year|annual', full_match, re.IGNORECASE) else "unknown",
                    })
            except ValueError:
                continue

    seen = set()
    unique_pricing = []
    for p in pricing:
        key = (p["amount"], p["period"])
        if key not in seen:
            seen.add(key)
            unique_pricing.append(p)

    return unique_pricing


def _extract_features(text: str) -> list:
    """Extract feature mentions from page content."""
    feature_keywords = [
        "scheduling", "dispatch", "invoicing", "payment processing",
        "customer management", "CRM", "reporting", "analytics",
        "mobile app", "GPS tracking", "estimates", "proposals",
        "online booking", "chat", "text messaging", "email marketing",
        "review management", "reputation management", "call tracking",
        "inventory management", "fleet management", "time tracking",
        "payroll", "QuickBooks integration", "AI", "automation",
        "voice AI", "chatbot", "missed call text back", "IVR",
        "live answering", "virtual receptionist", "call routing",
        "after hours", "24/7", "multi-location", "franchise",
        "membership plans", "maintenance agreements", "financing",
        "pricebook", "job costing", "photo documentation",
    ]
    text_lower = text.lower()
    found = []
    for feature in feature_keywords:
        if feature.lower() in text_lower:
            found.append(feature)
    return found


def _extract_testimonials(text: str, html: str) -> list:
    """Extract customer testimonials from page content."""
    testimonials = []

    quote_patterns = [
        r'["\u201c](.*?)["\u201d]\s*[-\u2014]\s*([\w\s,.]+)',
        r'<blockquote[^>]*>(.*?)</blockquote>',
        r'class="[^"]*testimonial[^"]*"[^>]*>(.*?)</div>',
    ]

    for pattern in quote_patterns:
        matches = re.finditer(pattern, html if '<' in pattern else text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            quote_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            if 20 < len(quote_text) < 1000:
                author = match.group(2).strip() if match.lastindex >= 2 else None
                testimonials.append({
                    "text": quote_text[:500],
                    "author": author[:100] if author else None,
                })
                if len(testimonials) >= 10:
                    break
        if len(testimonials) >= 10:
            break

    return testimonials


def _extract_blog_posts(text: str, html: str) -> list:
    """Extract recent blog post titles and dates."""
    posts = []

    blog_patterns = [
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*(?:blog|post|article)[^"]*"[^>]*>(.*?)</div>',
        r'<h[23][^>]*class="[^"]*(?:blog|post|entry)[^"]*"[^>]*>(.*?)</h[23]>',
    ]

    for pattern in blog_patterns:
        blocks = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        for block in blocks:
            title_match = re.search(r'<h[1-4][^>]*>(.*?)</h[1-4]>', block, re.DOTALL | re.IGNORECASE)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else None

            date_match = re.search(r'<time[^>]*datetime=["\'](\d{4}-\d{2}-\d{2})["\']', block)
            if not date_match:
                date_match = re.search(r'(\w+ \d{1,2},?\s*\d{4})', block)
            date = date_match.group(1) if date_match else None

            if title and len(title) > 5:
                posts.append({
                    "title": title[:200],
                    "date": date,
                })
                if len(posts) >= 10:
                    break
        if posts:
            break

    return posts


def _extract_job_postings(text: str) -> list:
    """Detect job posting indicators on the page."""
    postings = []
    text_lower = text.lower()

    job_patterns = [
        r'(?:we\'re|we are)\s*hiring',
        r'(?:join|careers?|jobs?|positions?|openings?)\s',
        r'(?:software engineer|developer|sales|marketing|customer success|support|account executive)',
    ]

    for pattern in job_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 100)
            context = text[start:end].strip()
            postings.append(context[:200])

    career_indicators = ["careers", "jobs", "hiring", "open positions", "join our team"]
    has_careers_page = any(kw in text_lower for kw in career_indicators)

    return postings[:10]


def _load_previous_snapshot(competitor_name: str) -> Optional[dict]:
    """Load the most recent previous snapshot for comparison."""
    safe_name = re.sub(r'[^\w\-]', '_', competitor_name.lower())
    comp_dir = os.path.join(SNAPSHOTS_DIR, safe_name)

    if not os.path.exists(comp_dir):
        return None

    files = sorted([f for f in os.listdir(comp_dir) if f.endswith(".json")], reverse=True)
    if not files:
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for f in files:
        if today not in f:
            filepath = os.path.join(comp_dir, f)
            try:
                with open(filepath, "r") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, IOError):
                continue
    return None


def _detect_changes(current: dict, previous: dict) -> dict:
    """Compare current snapshot to previous and identify changes."""
    changes = {
        "pricing_changed": False,
        "new_features_since_last": [],
        "removed_features": [],
        "new_testimonials": 0,
        "new_blog_posts": 0,
        "new_job_postings": 0,
    }

    current_prices = {(p["amount"], p["period"]) for p in current.get("pricing", [])}
    previous_prices = {(p["amount"], p["period"]) for p in previous.get("pricing", [])}
    if current_prices != previous_prices:
        changes["pricing_changed"] = True

    current_features = set(current.get("features_listed", []))
    previous_features = set(previous.get("features_listed", []))
    changes["new_features_since_last"] = list(current_features - previous_features)
    changes["removed_features"] = list(previous_features - current_features)

    prev_testimonial_texts = {t.get("text", "") for t in previous.get("testimonials", [])}
    new_testimonials = [t for t in current.get("testimonials", [])
                        if t.get("text", "") not in prev_testimonial_texts]
    changes["new_testimonials"] = len(new_testimonials)

    prev_blog_titles = {p.get("title", "") for p in previous.get("blog_posts", [])}
    new_posts = [p for p in current.get("blog_posts", [])
                 if p.get("title", "") not in prev_blog_titles]
    changes["new_blog_posts"] = len(new_posts)

    prev_job_count = len(previous.get("job_postings", []))
    curr_job_count = len(current.get("job_postings", []))
    changes["new_job_postings"] = max(0, curr_job_count - prev_job_count)

    return changes


async def monitor_competitor(competitor_url: str, competitor_name: str,
                             lead_id: Optional[str] = None) -> dict:
    """
    Monitor a competitor's website for pricing, features, and content changes.

    Args:
        competitor_url: The competitor's website URL.
        competitor_name: Human-readable competitor name.
        lead_id: Optional lead ID for logging.

    Returns:
        Dict with current snapshot data and change detection results.
    """
    _log("monitor_start", lead_id, "started", f"Monitoring {competitor_name}: {competitor_url}")

    urls_to_visit = [competitor_url]

    pricing_url = competitor_url.rstrip("/") + "/pricing"
    features_url = competitor_url.rstrip("/") + "/features"
    blog_url = competitor_url.rstrip("/") + "/blog"
    careers_url = competitor_url.rstrip("/") + "/careers"

    main_data = await navigate_to(competitor_url, use_cache=False, cache_type="competitor")

    if not main_data.get("success"):
        _log("monitor_fail", lead_id, "failure",
             f"Could not load {competitor_url}: {main_data.get('error', '')}")
        return {
            "competitor_name": competitor_name,
            "competitor_url": competitor_url,
            "pricing": [],
            "pricing_changed": False,
            "features_listed": [],
            "new_features_since_last": [],
            "testimonials": [],
            "blog_posts": [],
            "job_postings": [],
            "screenshot_path": None,
            "error": main_data.get("error", "Page load failed"),
        }

    all_text = main_data.get("text_content", "")
    all_html = main_data.get("html_raw", "")

    pricing_data = await navigate_to(pricing_url, use_cache=False, cache_type="competitor")
    if pricing_data.get("success"):
        all_text += "\n" + pricing_data.get("text_content", "")
        all_html += "\n" + pricing_data.get("html_raw", "")

    features_data = await navigate_to(features_url, use_cache=False, cache_type="competitor")
    if features_data.get("success"):
        all_text += "\n" + features_data.get("text_content", "")
        all_html += "\n" + features_data.get("html_raw", "")

    blog_data = await navigate_to(blog_url, use_cache=False, cache_type="competitor")
    blog_text = blog_data.get("text_content", "") if blog_data.get("success") else ""
    blog_html = blog_data.get("html_raw", "") if blog_data.get("success") else ""

    careers_data = await navigate_to(careers_url, use_cache=False, cache_type="competitor")
    careers_text = careers_data.get("text_content", "") if careers_data.get("success") else ""

    pricing = _extract_pricing(all_text, all_html)
    features = _extract_features(all_text)
    testimonials = _extract_testimonials(all_text, all_html)
    blog_posts = _extract_blog_posts(blog_text, blog_html)
    job_postings = _extract_job_postings(careers_text + "\n" + all_text)

    screenshot_result = await take_screenshot(competitor_url)
    screenshot_path = screenshot_result.get("screenshot_path") if screenshot_result.get("success") else None

    current_snapshot = {
        "competitor_name": competitor_name,
        "competitor_url": competitor_url,
        "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
        "pricing": pricing,
        "features_listed": features,
        "testimonials": testimonials,
        "blog_posts": blog_posts,
        "job_postings": job_postings,
        "screenshot_path": screenshot_path,
    }

    previous = _load_previous_snapshot(competitor_name)

    if previous:
        changes = _detect_changes(current_snapshot, previous)
        current_snapshot["pricing_changed"] = changes["pricing_changed"]
        current_snapshot["new_features_since_last"] = changes["new_features_since_last"]
        current_snapshot["removed_features"] = changes["removed_features"]
        current_snapshot["new_testimonials_count"] = changes["new_testimonials"]
        current_snapshot["new_blog_posts_count"] = changes["new_blog_posts"]
    else:
        current_snapshot["pricing_changed"] = False
        current_snapshot["new_features_since_last"] = []
        current_snapshot["removed_features"] = []
        current_snapshot["new_testimonials_count"] = 0
        current_snapshot["new_blog_posts_count"] = 0

    safe_name = re.sub(r'[^\w\-]', '_', competitor_name.lower())
    comp_dir = os.path.join(SNAPSHOTS_DIR, safe_name)
    os.makedirs(comp_dir, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = os.path.join(comp_dir, f"{date_str}.json")
    with open(filepath, "w") as f:
        json.dump(current_snapshot, f, indent=2)

    _log("monitor_complete", lead_id, "success",
         f"Monitored {competitor_name}: {len(pricing)} prices, {len(features)} features, "
         f"pricing_changed={current_snapshot['pricing_changed']}, "
         f"new_features={len(current_snapshot['new_features_since_last'])}")

    return current_snapshot


async def monitor_all_competitors(lead_id: Optional[str] = None) -> list:
    """Monitor all configured competitors."""
    competitors = CONFIG.get("competitors_to_monitor", [])
    results = []

    competitor_urls = {
        "smith.ai": ("https://smith.ai", "Smith.ai"),
        "ruby.com": ("https://www.ruby.com", "Ruby Receptionists"),
        "numa.com": ("https://www.numa.com", "Numa"),
        "hatch.co": ("https://www.usehatchapp.com", "Hatch"),
        "podium.com": ("https://www.podium.com", "Podium"),
        "housecallpro.com": ("https://www.housecallpro.com", "Housecall Pro"),
        "servicetitan.com": ("https://www.servicetitan.com", "ServiceTitan"),
        "jobber.com": ("https://getjobber.com", "Jobber"),
    }

    for comp_domain in competitors:
        if comp_domain in competitor_urls:
            url, name = competitor_urls[comp_domain]
            result = await monitor_competitor(url, name, lead_id=lead_id)
            results.append(result)
        else:
            url = f"https://{comp_domain}"
            result = await monitor_competitor(url, comp_domain, lead_id=lead_id)
            results.append(result)

    _log("monitor_all_complete", lead_id, "success",
         f"Monitored {len(results)} competitors")

    return results


def run():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Monitor competitor websites")
    parser.add_argument("url", nargs="?", help="Competitor URL to monitor")
    parser.add_argument("name", nargs="?", help="Competitor name")
    parser.add_argument("--all", action="store_true", help="Monitor all configured competitors")
    args = parser.parse_args()

    if args.all:
        results = asyncio.run(monitor_all_competitors())
        print(json.dumps(results, indent=2))
    elif args.url and args.name:
        result = asyncio.run(monitor_competitor(args.url, args.name))
        print(json.dumps(result, indent=2))
    else:
        print("Competitor Monitor ready. Usage:")
        print("  python competitor_monitor.py <url> <name>")
        print("  python competitor_monitor.py --all")


if __name__ == "__main__":
    run()
