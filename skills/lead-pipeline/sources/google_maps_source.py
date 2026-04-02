#!/usr/bin/env python3
"""
Google Maps Source — Lead Pipeline
Searches for contractor businesses via Playwright browser scraping of Google Maps.
Extracts: business name, phone, website, rating, review count, address.
Prioritizes: high review count, no/basic website, 4+ stars.
"""

import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")

MAX_QUERIES_PER_RUN = 50
ELEMENT_WAIT_TIMEOUT = 5000  # 5 seconds max wait for elements
RATE_DELAY_SECONDS = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


def _extract_website_domain(url: str) -> str:
    """Extract the domain from a URL for dedup and display."""
    if not url:
        return ""
    url = url.lower().strip()
    for prefix in ["https://", "http://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    # Remove trailing path
    url = url.split("/")[0]
    return url


def _is_basic_website(website: str) -> bool:
    """
    Heuristic check for basic/no website.
    Returns True if the website looks like a free/basic site or is missing.
    """
    if not website:
        return True
    domain = _extract_website_domain(website).lower()
    basic_indicators = [
        "facebook.com", "yelp.com", "yellowpages.com", "bbb.org",
        "homeadvisor.com", "angieslist.com", "angi.com", "thumbtack.com",
        "nextdoor.com", "google.com", "wix.com", "weebly.com",
        "squarespace.com", "godaddy.com", "wordpress.com",
    ]
    for indicator in basic_indicators:
        if indicator in domain:
            return True
    return False


def _parse_address(address_text: str) -> dict:
    """Extract city and state from an address string."""
    city = ""
    state = ""
    full_address = address_text.strip() if address_text else ""
    if full_address:
        parts = [p.strip() for p in full_address.split(",")]
        if len(parts) >= 2:
            city = parts[-2].strip() if len(parts) >= 3 else parts[0].strip()
            # Last part is usually "State ZIP" or "City, State ZIP"
            state_zip = parts[-1].strip()
            state_parts = state_zip.split()
            if state_parts:
                state = state_parts[0]
    return {"city": city, "state": state, "full_address": full_address}


def _build_search_queries(config: dict) -> list:
    """Build (query_string, vertical, city, state) tuples from config."""
    queries = []
    verticals_all = (
        config["verticals"]["tier_1"]
        + config["verticals"]["tier_2"]
        + config["verticals"]["tier_3"]
    )
    template = config["sources"]["google_maps"].get(
        "search_template", "{vertical} contractor {city} {state}"
    )
    for phase_key in ("phase_1", "phase_2"):
        geos = config["target_geos"].get(phase_key, [])
        for geo in geos:
            state = geo["state"]
            for city in geo["cities"]:
                for vertical in verticals_all:
                    display_vertical = vertical.replace("_", " ")
                    query = template.format(
                        vertical=display_vertical, city=city, state=state
                    )
                    queries.append((query, vertical, city, state))
    return queries


def _scrape_listing_details(page) -> dict:
    """
    Extract phone, website, and address from the currently open
    Google Maps detail panel.
    """
    details = {"phone": "", "website": "", "full_address": ""}

    # Website
    try:
        website_el = page.query_selector('a[data-item-id="authority"]')
        if website_el:
            details["website"] = website_el.get_attribute("href") or ""
    except Exception:
        pass
    if not details["website"]:
        try:
            website_el = page.query_selector('[aria-label*="Website"]')
            if website_el:
                href = website_el.get_attribute("href") or ""
                if href:
                    details["website"] = href
        except Exception:
            pass

    # Phone
    try:
        phone_el = page.query_selector('button[data-item-id^="phone:tel:"]')
        if phone_el:
            item_id = phone_el.get_attribute("data-item-id") or ""
            # data-item-id="phone:tel:+18005551234"
            if "tel:" in item_id:
                details["phone"] = item_id.split("tel:")[-1]
    except Exception:
        pass
    if not details["phone"]:
        try:
            phone_el = page.query_selector('[aria-label*="Phone"]')
            if phone_el:
                label = phone_el.get_attribute("aria-label") or ""
                # Try to extract phone number from aria-label
                phone_match = re.search(r'[\d\(\)\-\+ ]{7,}', label)
                if phone_match:
                    details["phone"] = phone_match.group(0).strip()
        except Exception:
            pass

    # Address
    try:
        addr_el = page.query_selector('button[data-item-id="address"]')
        if addr_el:
            label = addr_el.get_attribute("aria-label") or ""
            # aria-label is typically "Address: 123 Main St, City, ST 12345"
            if label.startswith("Address:"):
                details["full_address"] = label[len("Address:"):].strip()
            elif label:
                details["full_address"] = label.strip()
    except Exception:
        pass

    return details


def _extract_rating_reviews(result_el) -> tuple:
    """Extract rating and review count from a result element or detail panel."""
    rating = 0.0
    reviews = 0

    try:
        rating_el = result_el.query_selector('span[role="img"]')
        if rating_el:
            label = rating_el.get_attribute("aria-label") or ""
            # e.g. "4.5 stars"
            rating_match = re.search(r'([\d.]+)\s*star', label)
            if rating_match:
                rating = float(rating_match.group(1))
    except Exception:
        pass

    try:
        # Reviews are typically in parentheses like "(123)"
        text_content = result_el.inner_text()
        review_match = re.search(r'\((\d[\d,]*)\)', text_content)
        if review_match:
            reviews = int(review_match.group(1).replace(",", ""))
    except Exception:
        pass

    return rating, reviews


def run_google_maps_source() -> list:
    """
    Execute the Google Maps source pipeline via Playwright browser scraping.
    Searches for contractor businesses and extracts listing data.
    Returns a list of raw lead dicts ready for scoring.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("google_maps_source_start", None, "failure",
             "Playwright is not installed. Run: pip install playwright && playwright install chromium")
        return []

    config = _load_config()
    gm_config = config["sources"]["google_maps"]

    rate_delay = max(gm_config.get("rate_limit_delay_seconds", 3.0), RATE_DELAY_SECONDS)
    min_rating = gm_config.get("min_rating", 4.0)

    _log("google_maps_source_start", None, "success",
         "Starting Google Maps source run via Playwright scraping")

    queries = _build_search_queries(config)
    # Cap queries to avoid excessive scraping
    if len(queries) > MAX_QUERIES_PER_RUN:
        _log("google_maps_query_cap", None, "info",
             f"Capping queries from {len(queries)} to {MAX_QUERIES_PER_RUN}")
        queries = queries[:MAX_QUERIES_PER_RUN]

    leads = []
    seen_phones = set()
    seen_names = set()

    # Tier map for scoring
    tier_map = {}
    for tier_num, tier_key in enumerate(["tier_1", "tier_2", "tier_3"], start=1):
        for v in config["verticals"].get(tier_key, []):
            tier_map[v] = tier_num

    browser = None
    pw_instance = None
    try:
        pw_instance = sync_playwright().start()
        browser = pw_instance.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        for query_string, vertical, city, state in queries:
            time.sleep(rate_delay)

            page = context.new_page()
            encoded_query = urllib.parse.quote(query_string)
            maps_url = f"https://www.google.com/maps/search/{encoded_query}"
            query_lead_count = 0

            try:
                page.goto(maps_url, timeout=15000, wait_until="domcontentloaded")

                # Wait for results feed to appear
                try:
                    page.wait_for_selector('div[role="feed"]', timeout=ELEMENT_WAIT_TIMEOUT)
                except Exception:
                    _log("google_maps_no_results", None, "skipped",
                         f"No results feed for: {query_string}")
                    page.close()
                    continue

                # Scroll the feed a couple times to load more results
                feed = page.query_selector('div[role="feed"]')
                if feed:
                    for _ in range(3):
                        feed.evaluate('el => el.scrollTop = el.scrollHeight')
                        time.sleep(0.8)

                # Gather all result links
                result_links = page.query_selector_all(
                    'div[role="feed"] a[href*="/maps/place/"]'
                )

                if not result_links:
                    _log("google_maps_no_results", None, "skipped",
                         f"No results for: {query_string}")
                    page.close()
                    continue

                for result_el in result_links:
                    try:
                        # Extract business name from aria-label
                        aria_label = result_el.get_attribute("aria-label") or ""
                        title = aria_label.strip()
                        if not title:
                            continue

                        # Extract rating and reviews from the result card
                        rating, reviews = _extract_rating_reviews(result_el)

                        # Click the result to open the detail panel
                        result_el.click()
                        time.sleep(1.5)

                        # Wait for detail panel to load
                        try:
                            page.wait_for_selector(
                                'button[data-item-id="address"], a[data-item-id="authority"], button[data-item-id^="phone:tel:"]',
                                timeout=ELEMENT_WAIT_TIMEOUT
                            )
                        except Exception:
                            # Detail panel may not have all fields, continue anyway
                            pass

                        detail = _scrape_listing_details(page)
                        phone = detail.get("phone", "").strip()
                        website = detail.get("website", "").strip()
                        full_address = detail.get("full_address", "")

                        # If we didn't get rating from the card, try the detail panel
                        if not rating:
                            rating, reviews = _extract_rating_reviews(page)

                        # Dedup within this run by phone or name+city
                        name_key = f"{title.lower()}|{city.lower()}"
                        if phone and phone in seen_phones:
                            continue
                        if name_key in seen_names:
                            continue
                        if phone:
                            seen_phones.add(phone)
                        seen_names.add(name_key)

                        # Filter: require minimum rating if we have rating data
                        if rating and rating < min_rating:
                            continue

                        address_info = _parse_address(full_address)
                        has_website = bool(website) and not _is_basic_website(website)

                        lead = {
                            "company_name": title,
                            "contact_name": "",
                            "contact_role": "",
                            "email": "",
                            "phone": phone,
                            "website": website,
                            "has_website": has_website,
                            "vertical": vertical,
                            "tier": tier_map.get(vertical, 3),
                            "city": address_info.get("city", "") or city,
                            "state": address_info.get("state", "") or state,
                            "source": "google_maps",
                            "source_intent": "cold",
                            "estimated_employee_count": None,
                            "website_has_chat": None,
                            "website_has_calltracking": None,
                            "google_rating": rating if rating else None,
                            "google_review_count": reviews if reviews else None,
                            "yelp_response_indicator": None,
                            "full_address": address_info.get("full_address", ""),
                            "place_id": "",
                        }
                        leads.append(lead)
                        query_lead_count += 1

                    except Exception as e:
                        _log("google_maps_listing_error", None, "failure",
                             f"Error extracting listing: {str(e)}")
                        continue

            except Exception as e:
                _log("google_maps_page_error", None, "failure",
                     f"Error loading query page '{query_string}': {str(e)}")
            finally:
                page.close()

            _log("google_maps_query_complete", None, "success",
                 f"Query '{query_string}': {query_lead_count} results, "
                 f"{len(leads)} cumulative leads")

    except Exception as e:
        _log("google_maps_browser_error", None, "failure",
             f"Browser error: {str(e)}")
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw_instance:
            try:
                pw_instance.stop()
            except Exception:
                pass

    _log("google_maps_source_complete", None, "success",
         f"Google Maps source complete. {len(leads)} raw leads extracted.")
    return leads


if __name__ == "__main__":
    results = run_google_maps_source()
    print(json.dumps({"leads_found": len(results), "leads": results}, indent=2))
