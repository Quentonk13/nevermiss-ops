#!/usr/bin/env python3
"""
Browser Agent — Core browsing engine for the NeverMiss system.
Provides navigate, screenshot, structured data extraction, and web search capabilities.
Uses Playwright for browser automation with rate limiting, caching, and robots.txt respect.
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, quote_plus

from browser_utils import (
    RateLimiter, CacheManager, RobotsTxtChecker,
    log_action, get_random_user_agent, validate_url,
    extract_domain, get_screenshot_path, _load_config,
    DATA_DIR, LOG_PATH
)

CONFIG = _load_config()
RATE_LIMITER = RateLimiter(
    max_per_hour=CONFIG["rate_limits"]["max_visits_per_hour"],
    max_per_day=CONFIG["rate_limits"]["max_visits_per_day"],
    min_delay_ms=CONFIG["rate_limits"]["min_delay_between_requests_ms"],
)
CACHE = CacheManager()
ROBOTS_CHECKER = RobotsTxtChecker()


class BrowserSession:
    """
    Manages a Playwright browser session with automatic lifecycle management.
    Use as an async context manager for safe resource cleanup.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=CONFIG["browser"]["headless"],
        )
        self._context = await self._browser.new_context(
            viewport={
                "width": CONFIG["browser"]["viewport_width"],
                "height": CONFIG["browser"]["viewport_height"],
            },
            user_agent=get_random_user_agent(),
            locale=CONFIG["browser"]["locale"],
            timezone_id=CONFIG["browser"]["timezone_id"],
        )
        self._context.set_default_timeout(CONFIG["browser"]["timeout_ms"])
        self._context.set_default_navigation_timeout(CONFIG["browser"]["navigation_timeout_ms"])
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self):
        """Create a new page within this browser context."""
        return await self._context.new_page()

    async def rotate_user_agent(self):
        """Create a new context with a fresh user agent (for multi-page sessions)."""
        if self._context:
            await self._context.close()
        self._context = await self._browser.new_context(
            viewport={
                "width": CONFIG["browser"]["viewport_width"],
                "height": CONFIG["browser"]["viewport_height"],
            },
            user_agent=get_random_user_agent(),
            locale=CONFIG["browser"]["locale"],
            timezone_id=CONFIG["browser"]["timezone_id"],
        )
        self._context.set_default_timeout(CONFIG["browser"]["timeout_ms"])
        self._context.set_default_navigation_timeout(CONFIG["browser"]["navigation_timeout_ms"])


def _strip_html_to_text(html: str) -> str:
    """Strip HTML tags and normalize whitespace to produce clean text."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    # Replace block-level tags with newlines
    text = re.sub(r"<(?:br|p|div|h[1-6]|li|tr|blockquote)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_page_structure(html: str) -> dict:
    """Extract structural elements from raw HTML: title, headings, links, meta."""
    structure = {
        "title": "",
        "meta_description": "",
        "headings": [],
        "links": [],
        "images_count": 0,
        "forms_count": 0,
    }

    # Title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if title_match:
        structure["title"] = _strip_html_to_text(title_match.group(1)).strip()

    # Meta description
    meta_match = re.search(
        r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']',
        html, re.IGNORECASE
    )
    if not meta_match:
        meta_match = re.search(
            r'<meta\s+[^>]*content=["\'](.*?)["\'][^>]*name=["\']description["\']',
            html, re.IGNORECASE
        )
    if meta_match:
        structure["meta_description"] = meta_match.group(1).strip()

    # Headings
    for level in range(1, 7):
        for m in re.finditer(rf"<h{level}[^>]*>(.*?)</h{level}>", html, re.DOTALL | re.IGNORECASE):
            text = _strip_html_to_text(m.group(1)).strip()
            if text:
                structure["headings"].append({"level": level, "text": text[:200]})

    # Links (first 50)
    link_count = 0
    for m in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        if link_count >= 50:
            break
        href = m.group(1).strip()
        text = _strip_html_to_text(m.group(2)).strip()
        if href and not href.startswith(("#", "javascript:", "mailto:")):
            structure["links"].append({"href": href, "text": text[:100]})
            link_count += 1

    # Counts
    structure["images_count"] = len(re.findall(r"<img\s", html, re.IGNORECASE))
    structure["forms_count"] = len(re.findall(r"<form\s", html, re.IGNORECASE))

    return structure


async def navigate_to(url: str, use_cache: bool = True, cache_type: str = "default") -> dict:
    """
    Visit a URL, extract text content and page structure.

    Args:
        url: The URL to visit.
        use_cache: Whether to check the cache first.
        cache_type: Cache TTL category ('competitor', 'static', 'audit', 'default').

    Returns:
        Dict with keys: success, url, domain, title, text_content, structure,
        page_load_time_ms, status_code, error.
    """
    # Validate URL
    validation = validate_url(url)
    if not validation["valid"]:
        log_action("browser-agent", "navigate_blocked", None, "failure",
                   f"Invalid URL: {url} — {validation['reason']}")
        return {
            "success": False, "url": url, "domain": "", "title": "",
            "text_content": "", "structure": {}, "page_load_time_ms": 0,
            "status_code": 0, "error": validation["reason"],
        }

    normalized_url = validation["normalized"]
    domain = extract_domain(normalized_url)

    # Check cache
    if use_cache:
        cached = CACHE.get(normalized_url, cache_type)
        if cached is not None:
            log_action("browser-agent", "navigate_cache_hit", None, "success",
                       f"Cache hit for {normalized_url}")
            cached["from_cache"] = True
            return cached

    # Check robots.txt
    if CONFIG["security"]["respect_robots_txt"]:
        if not ROBOTS_CHECKER.is_allowed(normalized_url):
            log_action("browser-agent", "navigate_blocked_robots", None, "blocked",
                       f"robots.txt disallows: {normalized_url}")
            return {
                "success": False, "url": normalized_url, "domain": domain, "title": "",
                "text_content": "", "structure": {}, "page_load_time_ms": 0,
                "status_code": 0, "error": "Blocked by robots.txt",
            }

    # Rate limit
    RATE_LIMITER.wait_if_needed()

    start_time = time.time()
    result = {
        "success": False, "url": normalized_url, "domain": domain, "title": "",
        "text_content": "", "structure": {}, "page_load_time_ms": 0,
        "status_code": 0, "error": "", "from_cache": False,
    }

    try:
        async with BrowserSession() as session:
            page = await session.new_page()
            response = await page.goto(normalized_url, wait_until="domcontentloaded")
            # Wait for network to mostly settle
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # networkidle is best-effort

            elapsed_ms = int((time.time() - start_time) * 1000)
            RATE_LIMITER.record_request()

            status_code = response.status if response else 0
            html = await page.content()

            text_content = _strip_html_to_text(html)
            structure = _extract_page_structure(html)

            result.update({
                "success": status_code < 400,
                "title": structure["title"],
                "text_content": text_content[:50000],  # Cap at 50k chars
                "html_raw": html[:200000],  # Cap raw HTML for downstream parsing
                "structure": structure,
                "page_load_time_ms": elapsed_ms,
                "status_code": status_code,
            })

            # Cache successful responses
            if result["success"] and use_cache:
                cache_data = {k: v for k, v in result.items() if k != "html_raw"}
                CACHE.set(normalized_url, cache_data, cache_type)

            log_action("browser-agent", "navigate", None, "success",
                       f"Visited {normalized_url} — {status_code} in {elapsed_ms}ms, "
                       f"{len(text_content)} chars extracted")

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        RATE_LIMITER.record_request()
        result["error"] = str(e)
        result["page_load_time_ms"] = elapsed_ms
        log_action("browser-agent", "navigate_error", None, "failure",
                   f"Error visiting {normalized_url}: {e}")

    return result


async def take_screenshot(url: str, save_path: Optional[str] = None,
                          full_page: bool = True) -> dict:
    """
    Take a screenshot of a web page.

    Args:
        url: The URL to screenshot.
        save_path: Optional explicit save path. Auto-generated if not provided.
        full_page: Whether to capture the full scrollable page.

    Returns:
        Dict with keys: success, url, screenshot_path, page_load_time_ms, error.
    """
    validation = validate_url(url)
    if not validation["valid"]:
        return {
            "success": False, "url": url, "screenshot_path": "",
            "page_load_time_ms": 0, "error": validation["reason"],
        }

    normalized_url = validation["normalized"]

    if CONFIG["security"]["respect_robots_txt"]:
        if not ROBOTS_CHECKER.is_allowed(normalized_url):
            return {
                "success": False, "url": normalized_url, "screenshot_path": "",
                "page_load_time_ms": 0, "error": "Blocked by robots.txt",
            }

    RATE_LIMITER.wait_if_needed()

    if not save_path:
        save_path = get_screenshot_path(normalized_url)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    start_time = time.time()

    try:
        async with BrowserSession() as session:
            page = await session.new_page()
            await page.goto(normalized_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            await page.screenshot(path=save_path, full_page=full_page)
            elapsed_ms = int((time.time() - start_time) * 1000)
            RATE_LIMITER.record_request()

            log_action("browser-agent", "screenshot", None, "success",
                       f"Screenshot of {normalized_url} saved to {save_path}")

            return {
                "success": True, "url": normalized_url,
                "screenshot_path": save_path,
                "page_load_time_ms": elapsed_ms, "error": "",
            }

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        RATE_LIMITER.record_request()
        log_action("browser-agent", "screenshot_error", None, "failure",
                   f"Screenshot failed for {normalized_url}: {e}")
        return {
            "success": False, "url": normalized_url, "screenshot_path": "",
            "page_load_time_ms": elapsed_ms, "error": str(e),
        }


async def extract_structured_data(url: str, schema: dict,
                                  use_cache: bool = True) -> dict:
    """
    Navigate to a URL and extract structured data according to a provided schema.
    Uses Groq/Llama for page analysis, falling back to Claude for complex cases.

    Args:
        url: The URL to extract data from.
        schema: A dict describing the fields to extract, e.g.:
                {"company_name": "string", "phone": "string", "services": "list"}

    Returns:
        Dict with keys: success, url, extracted_data, confidence, llm_used, error.
    """
    # First navigate to get page content
    page_data = await navigate_to(url, use_cache=use_cache, cache_type="audit")
    if not page_data["success"]:
        return {
            "success": False, "url": url, "extracted_data": {},
            "confidence": 0.0, "llm_used": "none", "error": page_data["error"],
        }

    text_content = page_data["text_content"]
    structure = page_data["structure"]

    # Build extraction prompt
    schema_desc = json.dumps(schema, indent=2)
    prompt = (
        f"Extract the following structured data from this web page content.\n\n"
        f"Schema (field name -> expected type):\n{schema_desc}\n\n"
        f"Page title: {structure.get('title', 'N/A')}\n"
        f"Meta description: {structure.get('meta_description', 'N/A')}\n\n"
        f"Page content (truncated):\n{text_content[:8000]}\n\n"
        f"Return a JSON object matching the schema. For fields you cannot find, "
        f"use null. Add a '_confidence' field (0.0-1.0) indicating overall extraction confidence."
    )

    # Try Groq/Llama first
    llm_used = "none"
    extracted_data = {}
    confidence = 0.0

    try:
        import httpx
        groq_config = CONFIG["llm"]["page_analysis"]
        api_key = os.environ.get(groq_config["api_key_env"], "")

        if api_key:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": groq_config["model"],
                        "messages": [
                            {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 2000,
                    },
                )

                if resp.status_code == 200:
                    response_text = resp.json()["choices"][0]["message"]["content"]
                    # Parse JSON from response (handle markdown code blocks)
                    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
                    json_str = json_match.group(1) if json_match else response_text
                    extracted_data = json.loads(json_str.strip())
                    confidence = extracted_data.pop("_confidence", 0.7)
                    llm_used = f"groq/{groq_config['model']}"

                    tokens = resp.json().get("usage", {}).get("total_tokens", 0)
                    log_action("browser-agent", "extract_structured_llm", None, "success",
                               f"Groq extraction from {url}: {len(extracted_data)} fields",
                               llm_used=llm_used, tokens=tokens)
    except (json.JSONDecodeError, KeyError, Exception) as groq_err:
        log_action("browser-agent", "extract_structured_groq_fail", None, "failure",
                   f"Groq extraction failed for {url}: {groq_err}")

    # Fall back to Claude for complex cases or low confidence
    if confidence < 0.5 and not extracted_data:
        try:
            import httpx
            claude_config = CONFIG["llm"]["complex_reasoning"]
            api_key = os.environ.get(claude_config["api_key_env"], "")

            if api_key:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": claude_config["model"],
                            "max_tokens": 2000,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )

                    if resp.status_code == 200:
                        response_text = resp.json()["content"][0]["text"]
                        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
                        json_str = json_match.group(1) if json_match else response_text
                        extracted_data = json.loads(json_str.strip())
                        confidence = extracted_data.pop("_confidence", 0.8)
                        llm_used = f"anthropic/{claude_config['model']}"

                        input_tokens = resp.json().get("usage", {}).get("input_tokens", 0)
                        output_tokens = resp.json().get("usage", {}).get("output_tokens", 0)
                        cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)
                        log_action("browser-agent", "extract_structured_llm", None, "success",
                                   f"Claude extraction from {url}: {len(extracted_data)} fields",
                                   llm_used=llm_used, tokens=input_tokens + output_tokens, cost=cost)
        except (json.JSONDecodeError, KeyError, Exception) as claude_err:
            log_action("browser-agent", "extract_structured_claude_fail", None, "failure",
                       f"Claude extraction failed for {url}: {claude_err}")

    # Regex fallback for common fields when LLM is unavailable
    if not extracted_data:
        extracted_data = _regex_extract(text_content, page_data.get("html_raw", ""), schema)
        confidence = 0.3 if extracted_data else 0.0
        llm_used = "regex-fallback"
        log_action("browser-agent", "extract_structured_regex", None,
                   "success" if extracted_data else "failure",
                   f"Regex fallback for {url}: {len(extracted_data)} fields extracted")

    return {
        "success": bool(extracted_data),
        "url": url,
        "extracted_data": extracted_data,
        "confidence": confidence,
        "llm_used": llm_used,
        "error": "" if extracted_data else "No data could be extracted",
    }


def _regex_extract(text: str, html: str, schema: dict) -> dict:
    """Fallback regex extraction for common field types when LLM is unavailable."""
    data = {}

    for field_name, field_type in schema.items():
        field_lower = field_name.lower()

        if "phone" in field_lower:
            phone_match = re.search(
                r'(?:tel:|phone[:\s]*|call[:\s]*)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}',
                text
            )
            if phone_match:
                data[field_name] = phone_match.group(0).strip()
            else:
                data[field_name] = None

        elif "email" in field_lower:
            email_match = re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
            data[field_name] = email_match.group(0) if email_match else None

        elif "address" in field_lower:
            addr_match = re.search(
                r'\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Rd|Road|Ln|Lane|Way|Ct|Court)[.,]?\s*[\w\s]*,?\s*[A-Z]{2}\s*\d{5}',
                text, re.IGNORECASE
            )
            data[field_name] = addr_match.group(0).strip() if addr_match else None

        elif "year" in field_lower and "business" in field_lower:
            year_match = re.search(r'(?:since|established|founded|serving since)\s*(\d{4})', text, re.IGNORECASE)
            if year_match:
                founded_year = int(year_match.group(1))
                current_year = datetime.now().year
                data[field_name] = current_year - founded_year
            else:
                data[field_name] = None

        elif field_type == "list":
            data[field_name] = []

        elif field_type == "bool" or field_type == "boolean":
            data[field_name] = None

        else:
            data[field_name] = None

    return data


async def web_search(query: str, num_results: int = 5) -> dict:
    """
    Perform a web search using SerpAPI.

    Args:
        query: Search query string.
        num_results: Number of results to return (max 20).

    Returns:
        Dict with keys: success, query, results (list of {title, url, snippet}),
        total_results, error.
    """
    num_results = min(num_results, CONFIG["search"]["max_num_results"])

    # Check cache
    cache_key = f"search:{query}:{num_results}"
    cached = CACHE.get(cache_key, "search")
    if cached is not None:
        log_action("browser-agent", "web_search_cache_hit", None, "success",
                   f"Cache hit for search: {query}")
        cached["from_cache"] = True
        return cached

    api_key = os.environ.get(CONFIG["search"]["api_key_env"], "")
    if not api_key:
        log_action("browser-agent", "web_search_no_key", None, "failure",
                   "SERPAPI_API_KEY not set")
        return {
            "success": False, "query": query, "results": [],
            "total_results": 0, "error": "SERPAPI_API_KEY not configured",
        }

    RATE_LIMITER.wait_if_needed()

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google",
                    "q": query,
                    "api_key": api_key,
                    "num": num_results,
                    "hl": "en",
                    "gl": "us",
                },
            )
            RATE_LIMITER.record_request()

            if resp.status_code != 200:
                log_action("browser-agent", "web_search_error", None, "failure",
                           f"SerpAPI returned {resp.status_code} for query: {query}")
                return {
                    "success": False, "query": query, "results": [],
                    "total_results": 0, "error": f"SerpAPI HTTP {resp.status_code}",
                }

            data = resp.json()
            organic = data.get("organic_results", [])

            results = []
            for item in organic[:num_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "position": item.get("position", 0),
                })

            total_info = data.get("search_information", {})
            total_results = total_info.get("total_results", len(results))

            search_result = {
                "success": True,
                "query": query,
                "results": results,
                "total_results": total_results,
                "error": "",
                "from_cache": False,
            }

            # Cache the results
            CACHE.set(cache_key, search_result, "search")

            log_action("browser-agent", "web_search", None, "success",
                       f"Search '{query}': {len(results)} results returned")

            return search_result

    except Exception as e:
        RATE_LIMITER.record_request()
        log_action("browser-agent", "web_search_exception", None, "failure",
                   f"Search failed for '{query}': {e}")
        return {
            "success": False, "query": query, "results": [],
            "total_results": 0, "error": str(e),
        }


async def batch_navigate(urls: list, cache_type: str = "default") -> list:
    """
    Navigate to multiple URLs sequentially with rate limiting.
    Returns a list of results from navigate_to.
    """
    results = []
    for url in urls:
        result = await navigate_to(url, cache_type=cache_type)
        results.append(result)
    return results


async def check_element_exists(url: str, selector: str) -> dict:
    """
    Check if a specific CSS selector exists on a page.
    Used for detecting chat widgets, booking forms, etc.

    Returns:
        Dict with keys: success, url, selector, exists, element_count, error.
    """
    validation = validate_url(url)
    if not validation["valid"]:
        return {
            "success": False, "url": url, "selector": selector,
            "exists": False, "element_count": 0, "error": validation["reason"],
        }

    normalized_url = validation["normalized"]

    if CONFIG["security"]["respect_robots_txt"]:
        if not ROBOTS_CHECKER.is_allowed(normalized_url):
            return {
                "success": False, "url": normalized_url, "selector": selector,
                "exists": False, "element_count": 0, "error": "Blocked by robots.txt",
            }

    RATE_LIMITER.wait_if_needed()

    try:
        async with BrowserSession() as session:
            page = await session.new_page()
            await page.goto(normalized_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            RATE_LIMITER.record_request()
            elements = await page.query_selector_all(selector)
            count = len(elements)

            return {
                "success": True, "url": normalized_url, "selector": selector,
                "exists": count > 0, "element_count": count, "error": "",
            }

    except Exception as e:
        RATE_LIMITER.record_request()
        return {
            "success": False, "url": normalized_url, "selector": selector,
            "exists": False, "element_count": 0, "error": str(e),
        }


async def get_page_html(url: str) -> dict:
    """
    Get the full rendered HTML of a page (useful when other modules need raw HTML).

    Returns:
        Dict with keys: success, url, html, page_load_time_ms, error.
    """
    validation = validate_url(url)
    if not validation["valid"]:
        return {
            "success": False, "url": url, "html": "",
            "page_load_time_ms": 0, "error": validation["reason"],
        }

    normalized_url = validation["normalized"]

    if CONFIG["security"]["respect_robots_txt"]:
        if not ROBOTS_CHECKER.is_allowed(normalized_url):
            return {
                "success": False, "url": normalized_url, "html": "",
                "page_load_time_ms": 0, "error": "Blocked by robots.txt",
            }

    RATE_LIMITER.wait_if_needed()
    start_time = time.time()

    try:
        async with BrowserSession() as session:
            page = await session.new_page()
            await page.goto(normalized_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            RATE_LIMITER.record_request()
            html = await page.content()
            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True, "url": normalized_url, "html": html,
                "page_load_time_ms": elapsed_ms, "error": "",
            }

    except Exception as e:
        RATE_LIMITER.record_request()
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False, "url": normalized_url, "html": "",
            "page_load_time_ms": elapsed_ms, "error": str(e),
        }


def get_rate_limit_status() -> dict:
    """Return current rate limit usage for monitoring."""
    return RATE_LIMITER.get_usage()


def clear_expired_cache() -> int:
    """Clear expired cache entries. Returns number of entries removed."""
    removed = CACHE.clear_expired()
    log_action("browser-agent", "cache_cleanup", None, "success",
               f"Cleared {removed} expired cache entries")
    return removed


if __name__ == "__main__":
    import sys

    async def _main():
        if len(sys.argv) < 2:
            print("Browser Agent ready. Usage:")
            print("  python browser_agent.py navigate <url>")
            print("  python browser_agent.py screenshot <url>")
            print("  python browser_agent.py search <query>")
            print("  python browser_agent.py status")
            print("  python browser_agent.py cleanup")
            return

        cmd = sys.argv[1]

        if cmd == "navigate" and len(sys.argv) > 2:
            result = await navigate_to(sys.argv[2])
            print(json.dumps({k: v for k, v in result.items() if k != "html_raw"}, indent=2))

        elif cmd == "screenshot" and len(sys.argv) > 2:
            result = await take_screenshot(sys.argv[2])
            print(json.dumps(result, indent=2))

        elif cmd == "search" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            result = await web_search(query)
            print(json.dumps(result, indent=2))

        elif cmd == "status":
            print(json.dumps(get_rate_limit_status(), indent=2))

        elif cmd == "cleanup":
            removed = clear_expired_cache()
            print(f"Removed {removed} expired cache entries")

        else:
            print(f"Unknown command: {cmd}")

    asyncio.run(_main())
