"""
NeverMiss Free Web Search
==========================
Free web search using DuckDuckGo — no API key, no cost, no limits.
Replaces SerpAPI ($50/mo), Brave Search API, Google Custom Search.

Usage:
    python3 free_search.py --query "plumbers in Phoenix AZ"
    python3 free_search.py --query "ServiceTitan pricing 2026" --max 20
    python3 free_search.py --query "HVAC contractors" --news
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

RESULTS_DIR = os.environ.get("NEVERMISS_DATA_DIR", "/app/data")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search_ddg(query: str, max_results: int = 10, news: bool = False) -> list[dict]:
    """Search DuckDuckGo HTML and extract results. No API key needed."""
    results = []

    # DuckDuckGo HTML search
    q = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    if news:
        url += "&iar=news&ia=news"

    try:
        html = _fetch(url)
    except Exception as e:
        return [{"error": str(e)}]

    # Extract results from DDG HTML
    # Each result is in a div with class "result"
    result_blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>.*?'
        r'<a class="result__snippet".*?>(.*?)</a>',
        html,
        re.DOTALL,
    )

    for href, title, snippet in result_blocks[:max_results]:
        # Clean HTML tags from title and snippet
        title = re.sub(r"<.*?>", "", title).strip()
        snippet = re.sub(r"<.*?>", "", snippet).strip()

        # DDG wraps URLs in a redirect — extract the real URL
        real_url = href
        if "uddg=" in href:
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                real_url = urllib.parse.unquote(match.group(1))

        if title and real_url:
            results.append({
                "title": title,
                "url": real_url,
                "snippet": snippet,
            })

    return results


def search_and_extract(query: str, max_results: int = 10) -> list[dict]:
    """Search and try to extract key data from top results."""
    results = search_ddg(query, max_results)

    # Try to fetch and extract from top 3 results
    for i, r in enumerate(results[:3]):
        try:
            time.sleep(1)  # Rate limit
            html = _fetch(r["url"], timeout=10)
            # Extract emails
            emails = list(set(re.findall(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html
            )))
            # Extract phone numbers
            phones = list(set(re.findall(
                r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", html
            )))
            # Filter out common false positives
            emails = [e for e in emails if not any(
                x in e.lower() for x in ["example.com", "sentry", "webpack", ".png", ".jpg"]
            )]
            results[i]["emails"] = emails[:5]
            results[i]["phones"] = phones[:5]
        except Exception:
            pass

    return results


def find_businesses(trade: str, city: str, state: str = "", max_results: int = 10) -> list[dict]:
    """Search for contractor businesses by trade and location."""
    query = f"{trade} contractors in {city} {state}".strip()
    results = search_and_extract(query, max_results)

    # Also try Yelp-style search
    yelp_query = f"site:yelp.com {trade} {city} {state}".strip()
    yelp_results = search_ddg(yelp_query, 5)

    # And Google Maps style
    maps_query = f"{trade} near {city} {state} phone email".strip()
    maps_results = search_ddg(maps_query, 5)

    all_results = results + yelp_results + maps_results

    # Deduplicate by domain
    seen_domains = set()
    unique = []
    for r in all_results:
        domain = re.sub(r"https?://(?:www\.)?", "", r.get("url", "")).split("/")[0]
        if domain not in seen_domains:
            seen_domains.add(domain)
            unique.append(r)

    return unique[:max_results]


def find_emails(company: str, domain: str = "") -> list[dict]:
    """Find email addresses for a company. Replaces Hunter.io."""
    queries = [
        f'"{company}" email contact',
        f'site:{domain} email' if domain else f'"{company}" "@" email',
        f'"{company}" contact us phone email',
    ]

    all_emails = set()
    all_results = []

    for q in queries:
        results = search_ddg(q, 5)
        for r in results:
            try:
                time.sleep(1)
                html = _fetch(r["url"], timeout=10)
                emails = re.findall(
                    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html
                )
                for e in emails:
                    e_lower = e.lower()
                    if not any(x in e_lower for x in [
                        "example.com", "sentry", "webpack", ".png", ".jpg",
                        "wixpress", "schema.org", "googleapis"
                    ]):
                        all_emails.add(e_lower)
            except Exception:
                pass

    return [{"email": e, "source": "web_scrape"} for e in list(all_emails)[:10]]


def competitor_research(competitor: str) -> list[dict]:
    """Research a competitor's pricing, reviews, complaints."""
    queries = [
        f'"{competitor}" pricing plans cost',
        f'"{competitor}" reviews complaints',
        f'"{competitor}" vs alternative',
        f'site:g2.com "{competitor}"',
        f'site:capterra.com "{competitor}"',
    ]

    all_results = []
    for q in queries:
        time.sleep(1)
        results = search_ddg(q, 5)
        all_results.extend(results)

    return all_results


def _save_results(name: str, results: list):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    path = os.path.join(RESULTS_DIR, f"search_{today}_{name}.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="NeverMiss Free Web Search")
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--max", type=int, default=10, help="Max results")
    parser.add_argument("--news", action="store_true", help="Search news")
    parser.add_argument("--find-business", nargs=2, metavar=("TRADE", "CITY"),
                        help="Find contractors: --find-business plumber Phoenix")
    parser.add_argument("--find-email", help="Find emails for a company")
    parser.add_argument("--domain", default="", help="Company domain for email search")
    parser.add_argument("--competitor", help="Research a competitor")
    parser.add_argument("--save", action="store_true", help="Save results to /app/data/")
    args = parser.parse_args()

    results = []

    if args.find_business:
        trade, city = args.find_business
        results = find_businesses(trade, city, max_results=args.max)
        print(f"Found {len(results)} businesses for '{trade}' in '{city}':")
    elif args.find_email:
        results = find_emails(args.find_email, args.domain)
        print(f"Found {len(results)} emails for '{args.find_email}':")
    elif args.competitor:
        results = competitor_research(args.competitor)
        print(f"Found {len(results)} results for competitor '{args.competitor}':")
    elif args.query:
        if args.news:
            results = search_ddg(args.query, args.max, news=True)
        else:
            results = search_and_extract(args.query, args.max)
        print(f"Found {len(results)} results for '{args.query}':")
    else:
        parser.print_help()
        return

    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r.get('title', 'N/A')}")
        print(f"   {r.get('url', '')}")
        if r.get("snippet"):
            print(f"   {r['snippet'][:150]}")
        if r.get("emails"):
            print(f"   Emails: {', '.join(r['emails'])}")
        if r.get("phones"):
            print(f"   Phones: {', '.join(r['phones'])}")

    if args.save and results:
        name = args.query or args.competitor or "business"
        name = re.sub(r"[^a-zA-Z0-9]", "_", name)[:30]
        _save_results(name, results)
        print(f"\nSaved to /app/data/search_*_{name}.json")


if __name__ == "__main__":
    main()
