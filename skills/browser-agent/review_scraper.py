#!/usr/bin/env python3
"""
Review Scraper — Scrape competitor reviews from G2, Capterra, BBB, Yelp, Google.
Returns structured review data with sentiment analysis and complaint extraction.
Stores results in data/competitive_edge/competitor_reviews/.
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

from browser_agent import navigate_to, BrowserSession, RATE_LIMITER
from browser_utils import (
    log_action, validate_url, extract_domain, CacheManager,
    _load_config, DATA_DIR
)

CONFIG = _load_config()
CACHE = CacheManager()
REVIEWS_DIR = os.path.join(DATA_DIR, "competitive_edge", "competitor_reviews")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")

PLATFORM_URLS = {
    "g2": "https://www.g2.com/products/{slug}/reviews",
    "capterra": "https://www.capterra.com/reviews/{slug}",
    "bbb": "https://www.bbb.org/search?find_text={company_name}",
    "yelp": "https://www.yelp.com/search?find_desc={company_name}",
    "google": "https://www.google.com/search?q={company_name}+reviews",
}

NEGATIVE_WORDS = [
    "terrible", "awful", "horrible", "worst", "bad", "poor", "disappointed",
    "frustrat", "waste", "scam", "rip off", "ripoff", "slow", "unresponsive",
    "expensive", "overpriced", "broken", "bug", "crash", "glitch", "error",
    "unreliable", "downtime", "outage", "misleading", "deceptive", "hidden fees",
    "cancel", "refund", "support", "unhelpful", "rude", "unprofessional",
    "never again", "do not recommend", "stay away", "regret",
]

POSITIVE_WORDS = [
    "great", "excellent", "amazing", "fantastic", "wonderful", "love",
    "recommend", "best", "outstanding", "perfect", "impressed",
    "easy to use", "intuitive", "responsive", "helpful", "professional",
    "reliable", "fast", "efficient", "game changer", "life saver",
]

COMPLAINT_THEMES = {
    "pricing": ["expensive", "overpriced", "costly", "price increase", "hidden fees", "too much", "not worth"],
    "support": ["support", "customer service", "response time", "unhelpful", "wait", "ticket", "hold"],
    "reliability": ["downtime", "outage", "crash", "bug", "glitch", "unreliable", "broken", "error"],
    "onboarding": ["setup", "onboarding", "learning curve", "complicated", "confusing", "difficult to learn"],
    "features": ["missing feature", "limited", "doesn't have", "wish it had", "lacking", "basic"],
    "contract": ["contract", "cancel", "locked in", "refund", "commitment", "annual"],
    "integration": ["integration", "doesn't integrate", "api", "connect", "sync", "compatible"],
    "mobile": ["mobile", "app", "phone", "tablet", "ios", "android"],
    "performance": ["slow", "laggy", "loading", "performance", "speed"],
    "billing": ["billing", "charge", "invoice", "payment", "overcharge", "double charge"],
}


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.0):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "review-scraper",
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


def _analyze_sentiment(text: str) -> str:
    """Rule-based sentiment analysis: positive, negative, neutral."""
    text_lower = text.lower()
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)

    if neg_count > pos_count and neg_count >= 2:
        return "negative"
    if pos_count > neg_count and pos_count >= 2:
        return "positive"
    if neg_count > 0 and pos_count == 0:
        return "negative"
    if pos_count > 0 and neg_count == 0:
        return "positive"
    return "neutral"


def _extract_themes(text: str) -> list:
    """Extract complaint/praise themes from review text."""
    text_lower = text.lower()
    found_themes = []
    for theme, keywords in COMPLAINT_THEMES.items():
        for kw in keywords:
            if kw in text_lower:
                found_themes.append(theme)
                break
    return found_themes


def _parse_rating(text: str) -> Optional[float]:
    """Extract a numeric rating from review text or metadata."""
    patterns = [
        r'(\d(?:\.\d)?)\s*/\s*5',
        r'(\d(?:\.\d)?)\s*(?:out of|of)\s*5',
        r'rating[:\s]*(\d(?:\.\d)?)',
        r'(\d(?:\.\d)?)\s*stars?',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            if 0 <= val <= 5:
                return val
    return None


def _parse_date(text: str) -> Optional[str]:
    """Extract a date from review text."""
    date_formats = [
        (r'(\w+ \d{1,2},?\s*\d{4})', ["%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"]),
        (r'(\d{4}-\d{2}-\d{2})', ["%Y-%m-%d"]),
        (r'(\d{1,2}/\d{1,2}/\d{4})', ["%m/%d/%Y"]),
    ]
    for pattern, fmts in date_formats:
        match = re.search(pattern, text)
        if match:
            raw = match.group(1)
            for fmt in fmts:
                try:
                    parsed = datetime.strptime(raw, fmt)
                    return parsed.strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def _extract_reviews_from_text(text: str, platform: str) -> list:
    """
    Parse review blocks from page text content.
    Each platform has different structure, so we use heuristic splitting.
    """
    reviews = []

    if platform == "g2":
        blocks = re.split(r'(?:Review collected|Verified User|Star Rating)', text, flags=re.IGNORECASE)
    elif platform == "capterra":
        blocks = re.split(r'(?:Overall Rating|Reviewer Source|Review Summary)', text, flags=re.IGNORECASE)
    elif platform == "bbb":
        blocks = re.split(r'(?:Customer Review|Complaint Type|Date of Review)', text, flags=re.IGNORECASE)
    elif platform == "yelp":
        blocks = re.split(r'(?:stars?\s*\d{1,2}/\d{1,2}/\d{4}|Useful|Funny|Cool)', text, flags=re.IGNORECASE)
    elif platform == "google":
        blocks = re.split(r'(?:reviews?\s*\d|stars?\s*\d|ago\s)', text, flags=re.IGNORECASE)
    else:
        blocks = text.split("\n\n")

    for block in blocks:
        block = block.strip()
        if len(block) < 30 or len(block) > 5000:
            continue

        rating = _parse_rating(block)
        date = _parse_date(block)
        sentiment = _analyze_sentiment(block)
        themes = _extract_themes(block)

        review_text = block[:2000].strip()
        if not review_text:
            continue

        reviews.append({
            "rating": rating,
            "date": date,
            "text": review_text,
            "sentiment": sentiment,
            "themes": themes,
            "platform": platform,
        })

    return reviews


def _build_url(platform: str, company_name: str, slug: Optional[str] = None) -> str:
    """Build the review page URL for a given platform."""
    effective_slug = slug or company_name.lower().replace(" ", "-").replace(".", "")
    template = PLATFORM_URLS.get(platform, "")
    return template.format(
        slug=effective_slug,
        company_name=company_name.replace(" ", "+"),
    )


async def scrape_reviews(platform: str, company_name: str,
                         slug: Optional[str] = None,
                         lead_id: Optional[str] = None) -> dict:
    """
    Scrape reviews for a company from a specific platform.

    Args:
        platform: One of 'g2', 'capterra', 'bbb', 'yelp', 'google'.
        company_name: The company name to search for.
        slug: Optional URL slug override for G2/Capterra.
        lead_id: Optional lead ID for logging.

    Returns:
        Dict with reviews list and aggregated stats.
    """
    platform = platform.lower().strip()
    if platform not in PLATFORM_URLS:
        _log("scrape_reviews", lead_id, "failure", f"Unsupported platform: {platform}")
        return {
            "platform": platform,
            "company_name": company_name,
            "reviews": [],
            "average_rating": None,
            "total_reviews": 0,
            "negative_review_count": 0,
            "top_complaints": [],
            "error": f"Unsupported platform: {platform}. Supported: {list(PLATFORM_URLS.keys())}",
        }

    cache_key = f"reviews:{platform}:{company_name}"
    cached = CACHE.get(cache_key, "review")
    if cached is not None:
        _log("scrape_reviews_cache_hit", lead_id, "success",
             f"Cache hit for {platform} reviews of {company_name}")
        return cached

    url = _build_url(platform, company_name, slug)
    _log("scrape_reviews_start", lead_id, "started",
         f"Scraping {platform} reviews for {company_name}: {url}")

    page_data = await navigate_to(url, use_cache=False, cache_type="review")

    if not page_data.get("success"):
        _log("scrape_reviews", lead_id, "failure",
             f"Could not load {platform} page for {company_name}: {page_data.get('error', '')}")
        return {
            "platform": platform,
            "company_name": company_name,
            "reviews": [],
            "average_rating": None,
            "total_reviews": 0,
            "negative_review_count": 0,
            "top_complaints": [],
            "error": page_data.get("error", "Page load failed"),
        }

    text = page_data.get("text_content", "")
    html = page_data.get("html_raw", "")

    reviews = _extract_reviews_from_text(text, platform)

    if not reviews and html:
        reviews = _extract_reviews_from_html(html, platform)

    ratings = [r["rating"] for r in reviews if r["rating"] is not None]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    negative_reviews = [r for r in reviews if r["sentiment"] == "negative"]
    negative_count = len(negative_reviews)

    theme_counts = {}
    for review in negative_reviews:
        for theme in review.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    top_complaints = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_complaints = [{"theme": t, "count": c} for t, c in top_complaints]

    overall_rating = _extract_overall_rating(text, html)
    if overall_rating and avg_rating is None:
        avg_rating = overall_rating

    total_review_count = _extract_total_count(text, html)
    if total_review_count is None:
        total_review_count = len(reviews)

    result = {
        "platform": platform,
        "company_name": company_name,
        "url_scraped": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "reviews": reviews[:50],
        "average_rating": avg_rating,
        "total_reviews": total_review_count,
        "negative_review_count": negative_count,
        "top_complaints": top_complaints,
        "error": None,
    }

    CACHE.set(cache_key, result, "review")

    os.makedirs(REVIEWS_DIR, exist_ok=True)
    safe_name = re.sub(r'[^\w\-]', '_', company_name.lower())
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    filepath = os.path.join(REVIEWS_DIR, f"{safe_name}_{platform}_{ts}.json")
    with open(filepath, "w") as f:
        json.dump(result, f, indent=2)

    _log("scrape_reviews_complete", lead_id, "success",
         f"Scraped {len(reviews)} reviews from {platform} for {company_name}: "
         f"avg={avg_rating}, negative={negative_count}")

    return result


def _extract_reviews_from_html(html: str, platform: str) -> list:
    """Fallback HTML-based review extraction using common review markup patterns."""
    reviews = []
    html_lower = html.lower()

    review_patterns = [
        r'<div[^>]*class="[^"]*review[^"]*"[^>]*>(.*?)</div>',
        r'<article[^>]*class="[^"]*review[^"]*"[^>]*>(.*?)</article>',
        r'<li[^>]*class="[^"]*review[^"]*"[^>]*>(.*?)</li>',
    ]

    for pattern in review_patterns:
        blocks = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        for block in blocks:
            text = re.sub(r'<[^>]+>', ' ', block)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) < 30 or len(text) > 5000:
                continue

            rating = _parse_rating(block)
            date = _parse_date(block)
            sentiment = _analyze_sentiment(text)
            themes = _extract_themes(text)

            reviews.append({
                "rating": rating,
                "date": date,
                "text": text[:2000],
                "sentiment": sentiment,
                "themes": themes,
                "platform": platform,
            })

        if reviews:
            break

    return reviews


def _extract_overall_rating(text: str, html: str) -> Optional[float]:
    """Extract the overall/aggregate rating from the page."""
    patterns = [
        r'(?:overall|average)\s*(?:rating|score)[:\s]*(\d(?:\.\d{1,2})?)\s*/?\s*5?',
        r'(\d\.\d{1,2})\s*(?:out of|/)\s*5\s*(?:stars?|rating)',
        r'itemprop="ratingValue"[^>]*content="(\d(?:\.\d{1,2})?)"',
        r'"ratingValue"\s*:\s*"?(\d(?:\.\d{1,2})?)"?',
        r'aggregate[Rr]ating.*?(\d\.\d)',
    ]
    combined = text + " " + html
    for pattern in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            if 0 < val <= 5:
                return val
    return None


def _extract_total_count(text: str, html: str) -> Optional[int]:
    """Extract total review count from the page."""
    patterns = [
        r'(\d[\d,]*)\s*(?:reviews?|ratings?)',
        r'(?:based on|from)\s*(\d[\d,]*)\s*(?:reviews?|ratings?)',
        r'itemprop="reviewCount"[^>]*content="(\d+)"',
        r'"reviewCount"\s*:\s*"?(\d+)"?',
    ]
    combined = text + " " + html
    for pattern in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            count = int(match.group(1).replace(",", ""))
            if count > 0:
                return count
    return None


async def scrape_all_platforms(company_name: str, slug: Optional[str] = None,
                               platforms: Optional[list] = None,
                               lead_id: Optional[str] = None) -> dict:
    """
    Scrape reviews from all supported platforms for a company.

    Returns aggregated result across all platforms.
    """
    if platforms is None:
        platforms = list(PLATFORM_URLS.keys())

    all_reviews = []
    platform_results = {}

    for platform in platforms:
        result = await scrape_reviews(platform, company_name, slug=slug, lead_id=lead_id)
        platform_results[platform] = result
        all_reviews.extend(result.get("reviews", []))

    all_ratings = [r["rating"] for r in all_reviews if r["rating"] is not None]
    overall_avg = round(sum(all_ratings) / len(all_ratings), 2) if all_ratings else None

    all_negative = [r for r in all_reviews if r["sentiment"] == "negative"]
    theme_counts = {}
    for r in all_negative:
        for theme in r.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    top_complaints = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_complaints = [{"theme": t, "count": c} for t, c in top_complaints]

    aggregate = {
        "company_name": company_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "platforms_scraped": platforms,
        "platform_results": platform_results,
        "total_reviews_all_platforms": len(all_reviews),
        "overall_average_rating": overall_avg,
        "total_negative_reviews": len(all_negative),
        "top_complaints": top_complaints,
    }

    os.makedirs(REVIEWS_DIR, exist_ok=True)
    safe_name = re.sub(r'[^\w\-]', '_', company_name.lower())
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    filepath = os.path.join(REVIEWS_DIR, f"{safe_name}_aggregate_{ts}.json")
    with open(filepath, "w") as f:
        json.dump(aggregate, f, indent=2)

    _log("scrape_all_complete", lead_id, "success",
         f"Scraped {len(all_reviews)} total reviews across {len(platforms)} platforms for {company_name}")

    return aggregate


def run():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Scrape competitor reviews")
    parser.add_argument("platform", nargs="?", help="Platform: g2, capterra, bbb, yelp, google, all")
    parser.add_argument("company_name", nargs="?", help="Company name to search")
    parser.add_argument("--slug", default=None, help="URL slug override")
    args = parser.parse_args()

    if not args.platform or not args.company_name:
        print("Review Scraper ready. Usage:")
        print("  python review_scraper.py <platform> <company_name> [--slug SLUG]")
        print("  python review_scraper.py all <company_name>")
        print(f"  Platforms: {', '.join(PLATFORM_URLS.keys())}, all")
        return

    if args.platform == "all":
        result = asyncio.run(scrape_all_platforms(args.company_name, slug=args.slug))
    else:
        result = asyncio.run(scrape_reviews(args.platform, args.company_name, slug=args.slug))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()
