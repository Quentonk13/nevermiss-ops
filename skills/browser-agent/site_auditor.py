#!/usr/bin/env python3
"""
Site Auditor — Lead website auditing for the NeverMiss lead-pipeline skill.
Audits contractor websites for quality signals, tech stack, contact info,
and competitive intelligence.
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from browser_utils import (
    log_action, CacheManager, extract_domain, validate_url,
    _load_config, DATA_DIR
)
from browser_agent import (
    navigate_to, take_screenshot, get_page_html,
    BrowserSession, RATE_LIMITER, ROBOTS_CHECKER,
)

CONFIG = _load_config()
CACHE = CacheManager()
AUDIT_DIR = os.path.join(DATA_DIR, "website_audits")

# Chat widget selectors and script patterns
CHAT_WIDGET_SIGNATURES = {
    "Podium": {
        "scripts": ["podium.com/widget", "connect.podium.com"],
        "selectors": ["#podium-widget", "#podium-bubble", "[data-podium]", ".podium-widget"],
        "text_patterns": [r"podium"],
    },
    "ServiceTitan": {
        "scripts": ["servicetitan.com", "st-chat-widget"],
        "selectors": ["#st-chat-widget", "[data-servicetitan]", ".servicetitan-chat"],
        "text_patterns": [r"servicetitan"],
    },
    "Intercom": {
        "scripts": ["widget.intercom.io", "intercomcdn.com", "intercom.js"],
        "selectors": ["#intercom-container", "#intercom-frame", ".intercom-messenger",
                       "[data-intercom]", "#intercom-lightweight-app"],
        "text_patterns": [r"intercom"],
    },
    "Drift": {
        "scripts": ["js.driftt.com", "drift.com/api"],
        "selectors": ["#drift-widget", "#drift-frame", "[data-drift]", ".drift-frame-controller"],
        "text_patterns": [r"driftt?\.com"],
    },
    "LiveChat": {
        "scripts": ["cdn.livechatinc.com", "livechatinc.com"],
        "selectors": ["#livechat-compact-container", "#chat-widget-container",
                       "[data-livechat]", "#livechat-eye-catcher"],
        "text_patterns": [r"livechatinc"],
    },
    "Zendesk": {
        "scripts": ["static.zdassets.com", "zopim.com"],
        "selectors": ["#launcher", "[data-zendesk]", "#webWidget", ".zopim"],
        "text_patterns": [r"zdassets|zopim|zendesk"],
    },
    "HubSpot Chat": {
        "scripts": ["js.hs-scripts.com", "hubspot.com/conversations"],
        "selectors": ["#hubspot-messages-iframe-container", "[data-hubspot]"],
        "text_patterns": [r"hs-scripts|hubspot"],
    },
    "Tidio": {
        "scripts": ["code.tidio.co", "tidio.com"],
        "selectors": ["#tidio-chat", "[data-tidio]"],
        "text_patterns": [r"tidio"],
    },
}

# Call tracking signatures
CALL_TRACKING_SIGNATURES = {
    "CallRail": {
        "scripts": ["cdn.callrail.com", "callrail.com/companies"],
        "text_patterns": [r"callrail", r"swap_session_cookie"],
    },
    "CallTrackingMetrics": {
        "scripts": ["tctm.co", "calltrackingmetrics.com"],
        "text_patterns": [r"calltrackingmetrics|tctm\.co"],
    },
    "CallFire": {
        "scripts": ["callfire.com"],
        "text_patterns": [r"callfire"],
    },
    "Marchex": {
        "scripts": ["marchex.io"],
        "text_patterns": [r"marchex"],
    },
    "DialogTech": {
        "scripts": ["dialogtech.com", "invoca.net"],
        "text_patterns": [r"dialogtech|invoca"],
    },
}

# Online booking system signatures
BOOKING_SYSTEM_SIGNATURES = {
    "Housecall Pro": {
        "scripts": ["housecallpro.com", "hcp-book"],
        "selectors": ["[data-hcp]", ".hcp-booking"],
        "text_patterns": [r"housecallpro"],
    },
    "ServiceTitan": {
        "scripts": ["servicetitan.com", "st-book"],
        "selectors": ["[data-st-booking]"],
        "text_patterns": [r"servicetitan.*book"],
    },
    "Jobber": {
        "scripts": ["jobber.com"],
        "selectors": ["[data-jobber]", ".jobber-booking"],
        "text_patterns": [r"jobber"],
    },
    "Calendly": {
        "scripts": ["assets.calendly.com", "calendly.com/widget"],
        "selectors": [".calendly-inline-widget", ".calendly-badge-widget",
                       "[data-calendly]"],
        "text_patterns": [r"calendly"],
    },
    "Acuity Scheduling": {
        "scripts": ["acuityscheduling.com"],
        "selectors": [".acuity-embed-button", "[data-acuity]"],
        "text_patterns": [r"acuityscheduling"],
    },
    "ScheduleEngine": {
        "scripts": ["scheduleengine.net"],
        "selectors": ["[data-se-widget]"],
        "text_patterns": [r"scheduleengine"],
    },
}

# Social media platform patterns
SOCIAL_PATTERNS = {
    "facebook": r'(?:facebook\.com|fb\.com)/[\w.\-]+',
    "instagram": r'instagram\.com/[\w.\-]+',
    "twitter": r'(?:twitter\.com|x\.com)/[\w.\-]+',
    "linkedin": r'linkedin\.com/(?:company|in)/[\w.\-]+',
    "youtube": r'youtube\.com/(?:channel|@|user)/[\w.\-]+',
    "tiktok": r'tiktok\.com/@[\w.\-]+',
    "nextdoor": r'nextdoor\.com/[\w.\-]+',
    "yelp": r'yelp\.com/biz/[\w.\-]+',
    "google_business": r'(?:google\.com/maps|g\.page)/[\w.\-/]+',
}


def _detect_in_html(html: str, signatures: dict) -> list:
    """
    Detect tools/widgets by scanning HTML for script sources and text patterns.
    Returns a list of detected tool names.
    """
    html_lower = html.lower()
    detected = []

    for tool_name, sigs in signatures.items():
        found = False

        # Check script sources
        for script_pattern in sigs.get("scripts", []):
            if script_pattern.lower() in html_lower:
                found = True
                break

        # Check text patterns
        if not found:
            for pattern in sigs.get("text_patterns", []):
                if re.search(pattern, html_lower):
                    found = True
                    break

        if found:
            detected.append(tool_name)

    return detected


async def _detect_selectors_on_page(page, signatures: dict) -> list:
    """
    Detect tools/widgets by checking CSS selectors on a live page.
    Returns a list of detected tool names.
    """
    detected = []
    for tool_name, sigs in signatures.items():
        for selector in sigs.get("selectors", []):
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    detected.append(tool_name)
                    break
            except Exception:
                continue
    return detected


def _extract_phone_numbers(text: str) -> list:
    """Extract US phone numbers from text."""
    patterns = [
        r'\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}',
        r'1[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}',
    ]
    phones = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            phone = re.sub(r'[^\d]', '', match.group(0))
            if len(phone) == 10 or (len(phone) == 11 and phone.startswith("1")):
                if phone not in phones:
                    phones.append(phone)
    return phones


def _extract_social_links(html: str) -> dict:
    """Extract social media profile URLs from page HTML."""
    social_links = {}
    for platform, pattern in SOCIAL_PATTERNS.items():
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            # Take the first unique match, reconstruct as full URL
            url = matches[0]
            if not url.startswith("http"):
                url = "https://" + url
            social_links[platform] = url
    return social_links


def _estimate_team_size(text: str) -> Optional[str]:
    """
    Estimate team size from page content.
    Returns a string like "5-10", "20+", or None.
    """
    text_lower = text.lower()

    # Look for explicit team size mentions
    team_patterns = [
        (r'(\d+)\+?\s*(?:team members|employees|technicians|techs|professionals|experts|specialists)', None),
        (r'team of\s*(\d+)', None),
        (r'(\d+)\s*(?:trucks|vehicles|vans|service vehicles)', "vehicles"),
    ]

    for pattern, context in team_patterns:
        match = re.search(pattern, text_lower)
        if match:
            count = int(match.group(1))
            if context == "vehicles":
                return f"{count}-{count * 2} (based on {count} vehicles)"
            if count <= 5:
                return "1-5"
            elif count <= 10:
                return "5-10"
            elif count <= 25:
                return "10-25"
            elif count <= 50:
                return "25-50"
            else:
                return "50+"

    # Check for team page links or "meet the team" sections
    if re.search(r'meet (?:the|our) team', text_lower):
        # Count names on a team page (heuristic)
        name_pattern = r'(?:^|\n)\s*([A-Z][a-z]+ [A-Z][a-z]+)\s*(?:\n|,)'
        names = re.findall(name_pattern, text)
        if names:
            count = len(set(names))
            if count >= 3:
                if count <= 5:
                    return "1-5"
                elif count <= 10:
                    return "5-10"
                elif count <= 25:
                    return "10-25"
                else:
                    return f"{count}+"

    return None


def _extract_years_in_business(text: str) -> Optional[int]:
    """Extract years in business from page content."""
    text_lower = text.lower()
    current_year = datetime.now().year

    # Direct year mentions
    patterns = [
        r'(?:since|established|founded|serving since|in business since)\s*(\d{4})',
        r'(\d{4})\s*(?:-|to)\s*(?:present|today|now)',
        r'over\s*(\d+)\s*years?\s*(?:of experience|in business|serving)',
        r'(\d+)\+?\s*years?\s*(?:of experience|in business|serving)',
        r'more than\s*(\d+)\s*years',
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            value = int(match.group(1))
            if value > 1900:  # It's a year
                return current_year - value
            elif value < 200:  # It's a number of years
                return value

    return None


def _extract_certifications(text: str) -> list:
    """Extract certifications and licenses from page content."""
    text_lower = text.lower()
    certs = []

    cert_patterns = [
        (r'epa\s*(?:section\s*)?608', "EPA 608"),
        (r'nate\s*certified', "NATE Certified"),
        (r'bbb\s*(?:a\+?|accredited)', "BBB Accredited"),
        (r'licensed\s*(?:and|&)\s*(?:insured|bonded)', "Licensed & Insured"),
        (r'home\s*advisor\s*(?:screened|approved|elite)', "HomeAdvisor Approved"),
        (r'angi\s*(?:certified|listed)', "Angi Listed"),
        (r'energy\s*star\s*(?:partner|certified)', "Energy Star Partner"),
        (r'diamond\s*(?:contractor|dealer)', "Diamond Contractor"),
        (r'lennox\s*(?:premier|dealer)', "Lennox Dealer"),
        (r'carrier\s*(?:factory|authorized|dealer)', "Carrier Dealer"),
        (r'trane\s*(?:comfort|dealer)', "Trane Dealer"),
        (r'rheem\s*(?:pro|dealer)', "Rheem Dealer"),
        (r'master\s*(?:plumber|electrician)', "Master Tradesperson"),
        (r'journeyman', "Journeyman"),
    ]

    for pattern, cert_name in cert_patterns:
        if re.search(pattern, text_lower):
            if cert_name not in certs:
                certs.append(cert_name)

    return certs


def _extract_services(text: str) -> list:
    """Extract listed services from page content."""
    text_lower = text.lower()
    common_services = [
        "air conditioning", "ac repair", "ac installation", "heating", "furnace repair",
        "heat pump", "hvac maintenance", "duct cleaning", "ductwork",
        "plumbing", "drain cleaning", "water heater", "sewer",
        "electrical", "wiring", "panel upgrade", "generator",
        "roofing", "roof repair", "roof replacement",
        "pest control", "termite", "rodent",
        "landscaping", "lawn care", "tree service", "irrigation",
        "painting", "interior painting", "exterior painting",
        "remodeling", "renovation", "bathroom remodel", "kitchen remodel",
        "garage door", "fencing", "concrete", "paving",
        "carpet cleaning", "pressure washing", "window cleaning",
        "fire restoration", "water damage", "mold remediation",
        "commercial services", "residential services", "emergency service",
        "24/7 service", "same day service", "free estimates",
    ]

    found_services = []
    for service in common_services:
        if service in text_lower:
            found_services.append(service.title())

    return found_services


def _extract_service_areas(text: str) -> list:
    """Extract service areas/cities from page content."""
    text_lower = text.lower()
    areas = []

    # Look for "serving [city/area]" patterns
    area_patterns = [
        r'serv(?:ing|ice areas?|ices?)\s*:?\s*((?:[A-Z][\w\s]+,?\s*)+)',
        r'(?:we serve|areas? served|service areas?)\s*:?\s*((?:[A-Z][\w\s]+,?\s*)+)',
        r'proudly serving\s*((?:[A-Z][\w\s]+,?\s*)+)',
    ]

    for pattern in area_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Split on commas or "and"
            parts = re.split(r',|\band\b', match)
            for part in parts:
                cleaned = part.strip().strip(",").strip()
                if cleaned and len(cleaned) > 2 and len(cleaned) < 50:
                    if cleaned not in areas:
                        areas.append(cleaned)

    return areas[:20]  # Cap at 20


def _detect_last_blog_date(html: str, text: str) -> Optional[str]:
    """Try to find the most recent blog post date."""
    # Look for common date patterns near blog/article content
    date_patterns = [
        r'(?:published|posted|date)[:\s]*(\w+ \d{1,2},? \d{4})',
        r'(?:published|posted|date)[:\s]*(\d{4}-\d{2}-\d{2})',
        r'<time[^>]*datetime=["\'](\d{4}-\d{2}-\d{2})["\']',
        r'<time[^>]*>(\w+ \d{1,2},? \d{4})</time>',
    ]

    dates = []
    for pattern in date_patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            date_str = match.group(1)
            # Try to parse the date
            for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    dates.append(parsed)
                    break
                except ValueError:
                    continue

    if dates:
        most_recent = max(dates)
        return most_recent.strftime("%Y-%m-%d")

    return None


def _assess_website_quality(page_data: dict, audit_results: dict) -> str:
    """
    Score website quality as 'high', 'medium', or 'low' based on multiple signals.
    """
    score = 0
    max_score = 20

    # Has proper title and meta description
    structure = page_data.get("structure", {})
    if structure.get("title"):
        score += 2
    if structure.get("meta_description"):
        score += 1

    # Has multiple headings (structured content)
    heading_count = len(structure.get("headings", []))
    if heading_count >= 5:
        score += 2
    elif heading_count >= 2:
        score += 1

    # Has images
    if structure.get("images_count", 0) >= 3:
        score += 1

    # Has contact form
    if audit_results.get("has_contact_form"):
        score += 2

    # Phone visible
    if audit_results.get("phone_visible"):
        score += 1

    # Services listed
    if len(audit_results.get("services_listed", [])) >= 3:
        score += 2

    # Certifications
    if audit_results.get("certifications"):
        score += 1

    # Social links
    if len(audit_results.get("social_links", {})) >= 2:
        score += 1

    # Fast page load
    load_time = page_data.get("page_load_time_ms", 10000)
    if load_time < 3000:
        score += 2
    elif load_time < 5000:
        score += 1

    # Has chat widget
    if audit_results.get("has_live_chat"):
        score += 1

    # Has online booking
    if audit_results.get("has_online_booking"):
        score += 1

    # Has blog
    if audit_results.get("last_blog_post_date"):
        score += 2

    ratio = score / max_score
    if ratio >= 0.6:
        return "high"
    elif ratio >= 0.35:
        return "medium"
    else:
        return "low"


async def audit_contractor_website(url: str, lead_id: Optional[str] = None) -> dict:
    """
    Perform a comprehensive audit of a contractor's website.
    Called by the lead-pipeline skill to enrich lead data.

    Args:
        url: The contractor's website URL.
        lead_id: Optional lead ID for filing the audit report.

    Returns:
        Comprehensive audit dict with all website quality signals.
    """
    audit_start = time.time()

    # Check cache first
    cached = CACHE.get(url, "audit")
    if cached is not None:
        log_action("browser-agent", "site_audit_cache_hit", lead_id, "success",
                   f"Cache hit for audit: {url}")
        return cached

    # Initialize result with defaults
    result = {
        "url": url,
        "domain": extract_domain(url) if url else "",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "has_website": False,
        "website_quality": "none",
        "has_live_chat": False,
        "chat_widget_detected": [],
        "has_call_tracking": False,
        "call_tracking_detected": [],
        "has_online_booking": False,
        "booking_system_detected": [],
        "has_contact_form": False,
        "phone_visible": False,
        "phone_number": None,
        "services_listed": [],
        "service_areas": [],
        "team_size_indicators": None,
        "years_in_business": None,
        "certifications": [],
        "social_links": {},
        "competitor_tools_detected": [],
        "page_load_time": 0,
        "last_blog_post_date": None,
        "screenshot_path": None,
        "error": None,
    }

    # Validate URL
    validation = validate_url(url)
    if not validation["valid"]:
        result["error"] = validation["reason"]
        result["has_website"] = False
        log_action("browser-agent", "site_audit_invalid_url", lead_id, "failure",
                   f"Invalid URL for audit: {url} — {validation['reason']}")
        _save_audit(result, lead_id)
        return result

    normalized_url = validation["normalized"]
    result["url"] = normalized_url
    result["domain"] = extract_domain(normalized_url)

    # Navigate to the page
    page_data = await navigate_to(normalized_url, use_cache=False, cache_type="audit")

    if not page_data["success"]:
        result["has_website"] = False
        result["error"] = page_data.get("error", "Failed to load page")
        result["page_load_time"] = page_data.get("page_load_time_ms", 0)
        log_action("browser-agent", "site_audit_page_fail", lead_id, "failure",
                   f"Could not load {normalized_url}: {result['error']}")
        _save_audit(result, lead_id)
        return result

    # Website exists and loads
    result["has_website"] = True
    result["page_load_time"] = page_data.get("page_load_time_ms", 0)

    html = page_data.get("html_raw", "")
    text = page_data.get("text_content", "")

    # Detect chat widgets from HTML
    chat_widgets_html = _detect_in_html(html, CHAT_WIDGET_SIGNATURES)

    # Detect chat widgets from selectors (live page check)
    chat_widgets_selectors = []
    try:
        async with BrowserSession() as session:
            page = await session.new_page()
            await page.goto(normalized_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            RATE_LIMITER.record_request()

            # Selector-based detection
            chat_widgets_selectors = await _detect_selectors_on_page(page, CHAT_WIDGET_SIGNATURES)
            booking_selectors = await _detect_selectors_on_page(page, BOOKING_SYSTEM_SIGNATURES)

            # Contact form detection
            forms = await page.query_selector_all("form")
            for form in forms:
                form_html = await form.inner_html()
                form_lower = form_html.lower()
                # Look for contact-form signals
                if any(kw in form_lower for kw in
                       ["name", "email", "phone", "message", "contact", "inquiry", "request"]):
                    result["has_contact_form"] = True
                    break

            # Take screenshot
            screenshot_path = get_screenshot_path(normalized_url, suffix="_audit")
            try:
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                await page.screenshot(path=screenshot_path, full_page=True)
                result["screenshot_path"] = screenshot_path
            except Exception as ss_err:
                log_action("browser-agent", "site_audit_screenshot_fail", lead_id, "failure",
                           f"Screenshot failed during audit of {normalized_url}: {ss_err}")

    except Exception as browser_err:
        log_action("browser-agent", "site_audit_browser_fail", lead_id, "failure",
                   f"Browser session failed during audit of {normalized_url}: {browser_err}")

    # Merge chat widget detections (union of HTML and selector checks)
    all_chat_widgets = list(set(chat_widgets_html + chat_widgets_selectors))
    result["chat_widget_detected"] = all_chat_widgets
    result["has_live_chat"] = len(all_chat_widgets) > 0

    # Detect call tracking
    call_tracking = _detect_in_html(html, CALL_TRACKING_SIGNATURES)
    result["call_tracking_detected"] = call_tracking
    result["has_call_tracking"] = len(call_tracking) > 0

    # Detect booking systems (HTML + selectors)
    booking_html = _detect_in_html(html, BOOKING_SYSTEM_SIGNATURES)
    all_booking = list(set(booking_html + booking_selectors if 'booking_selectors' in dir() else booking_html))
    result["booking_system_detected"] = all_booking
    result["has_online_booking"] = len(all_booking) > 0

    # Extract phone numbers
    phones = _extract_phone_numbers(text)
    if not phones:
        # Also check HTML for tel: links
        tel_matches = re.findall(r'href=["\']tel:([^"\']+)["\']', html)
        for tel in tel_matches:
            phone = re.sub(r'[^\d]', '', tel)
            if len(phone) >= 10 and phone not in phones:
                phones.append(phone)

    result["phone_visible"] = len(phones) > 0
    result["phone_number"] = phones[0] if phones else None

    # Extract services
    result["services_listed"] = _extract_services(text)

    # Extract service areas
    result["service_areas"] = _extract_service_areas(text)

    # Team size
    result["team_size_indicators"] = _estimate_team_size(text)

    # Years in business
    result["years_in_business"] = _extract_years_in_business(text)

    # Certifications
    result["certifications"] = _extract_certifications(text)

    # Social links
    result["social_links"] = _extract_social_links(html)

    # Competitor tools detected (combine chat, call tracking, booking that are competitors)
    competitor_tools = []
    competitor_names = ["ServiceTitan", "Housecall Pro", "Jobber", "Podium"]
    for tool in all_chat_widgets + call_tracking + all_booking:
        for comp in competitor_names:
            if comp.lower() in tool.lower() and tool not in competitor_tools:
                competitor_tools.append(tool)
    result["competitor_tools_detected"] = competitor_tools

    # Blog post date
    result["last_blog_post_date"] = _detect_last_blog_date(html, text)

    # Assess overall quality
    result["website_quality"] = _assess_website_quality(page_data, result)

    # Log and save
    audit_duration_ms = int((time.time() - audit_start) * 1000)
    log_action("browser-agent", "site_audit_complete", lead_id, "success",
               f"Audit of {normalized_url}: quality={result['website_quality']}, "
               f"chat={result['has_live_chat']}, tracking={result['has_call_tracking']}, "
               f"booking={result['has_online_booking']}, "
               f"duration={audit_duration_ms}ms")

    # Cache the result
    CACHE.set(normalized_url, result, "audit")

    # Save audit to disk
    _save_audit(result, lead_id)

    return result


def _save_audit(audit: dict, lead_id: Optional[str]):
    """Save audit result to disk, keyed by lead_id or domain."""
    os.makedirs(AUDIT_DIR, exist_ok=True)
    filename = f"{lead_id}.json" if lead_id else f"{audit.get('domain', 'unknown')}.json"
    filepath = os.path.join(AUDIT_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(audit, f, indent=2)


def load_audit(lead_id: str) -> Optional[dict]:
    """Load a previously saved audit by lead_id."""
    filepath = os.path.join(AUDIT_DIR, f"{lead_id}.json")
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return None


async def quick_check(url: str) -> dict:
    """
    Lightweight check: just test if the website loads and grab basic signals.
    Much faster than full audit (single page visit).
    Returns: has_website, page_load_time, phone_visible, has_contact_form.
    """
    validation = validate_url(url)
    if not validation["valid"]:
        return {
            "has_website": False,
            "page_load_time": 0,
            "phone_visible": False,
            "has_contact_form": False,
            "error": validation["reason"],
        }

    page_data = await navigate_to(validation["normalized"], cache_type="audit")

    if not page_data["success"]:
        return {
            "has_website": False,
            "page_load_time": page_data.get("page_load_time_ms", 0),
            "phone_visible": False,
            "has_contact_form": False,
            "error": page_data.get("error", ""),
        }

    text = page_data.get("text_content", "")
    structure = page_data.get("structure", {})
    phones = _extract_phone_numbers(text)

    return {
        "has_website": True,
        "page_load_time": page_data.get("page_load_time_ms", 0),
        "phone_visible": len(phones) > 0,
        "has_contact_form": structure.get("forms_count", 0) > 0,
        "error": "",
    }


def get_screenshot_path(url: str, suffix: str = "") -> str:
    """Generate screenshot path for audits."""
    from browser_utils import get_screenshot_path as _get_path
    return _get_path(url, suffix)


if __name__ == "__main__":
    import sys

    async def _main():
        if len(sys.argv) < 2:
            print("Site Auditor ready. Usage:")
            print("  python site_auditor.py audit <url> [lead_id]")
            print("  python site_auditor.py quick <url>")
            return

        cmd = sys.argv[1]

        if cmd == "audit" and len(sys.argv) > 2:
            url = sys.argv[2]
            lead_id = sys.argv[3] if len(sys.argv) > 3 else None
            result = await audit_contractor_website(url, lead_id)
            print(json.dumps(result, indent=2))

        elif cmd == "quick" and len(sys.argv) > 2:
            result = await quick_check(sys.argv[2])
            print(json.dumps(result, indent=2))

        else:
            print(f"Unknown command: {cmd}")

    asyncio.run(_main())
