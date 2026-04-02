#!/usr/bin/env python3
"""
Browser Utilities — Shared helpers for the browser-agent skill.
Rate limiter, cache manager, user agent rotation, robots.txt checker.
"""

import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
CACHE_DIR = os.path.join(DATA_DIR, "browser_cache")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
]


def _load_config() -> dict:
    """Load skill configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def log_action(skill: str, action: str, lead_id: Optional[str], result: str,
               details: str, llm_used: str = "none", tokens: int = 0, cost: float = 0.0):
    """Append a structured log entry to system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
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


def get_random_user_agent() -> str:
    """Return a randomly selected user agent string."""
    return random.choice(USER_AGENTS)


class RateLimiter:
    """
    Token-bucket rate limiter tracking hourly and daily request counts.
    Persists state to disk so limits survive process restarts.
    """

    def __init__(self, max_per_hour: int = 100, max_per_day: int = 500,
                 min_delay_ms: int = 1500):
        self.max_per_hour = max_per_hour
        self.max_per_day = max_per_day
        self.min_delay_ms = min_delay_ms
        self._state_path = os.path.join(CACHE_DIR, "_rate_limiter_state.json")
        self._state = self._load_state()
        self._last_request_time = 0.0

    def _load_state(self) -> dict:
        """Load rate limiter state from disk."""
        os.makedirs(CACHE_DIR, exist_ok=True)
        if os.path.exists(self._state_path):
            try:
                with open(self._state_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return self._fresh_state()

    def _fresh_state(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "hour_key": now.strftime("%Y-%m-%d-%H"),
            "day_key": now.strftime("%Y-%m-%d"),
            "hour_count": 0,
            "day_count": 0,
        }

    def _save_state(self):
        """Persist rate limiter state to disk."""
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(self._state_path, "w") as f:
            json.dump(self._state, f)

    def _rotate_windows(self):
        """Reset counters if the hour or day has changed."""
        now = datetime.now(timezone.utc)
        current_hour = now.strftime("%Y-%m-%d-%H")
        current_day = now.strftime("%Y-%m-%d")

        if self._state["hour_key"] != current_hour:
            self._state["hour_key"] = current_hour
            self._state["hour_count"] = 0

        if self._state["day_key"] != current_day:
            self._state["day_key"] = current_day
            self._state["day_count"] = 0

    def can_request(self) -> bool:
        """Check whether a request is allowed under current rate limits."""
        self._rotate_windows()
        if self._state["hour_count"] >= self.max_per_hour:
            return False
        if self._state["day_count"] >= self.max_per_day:
            return False
        return True

    def wait_if_needed(self):
        """Block until a request is allowed, enforcing min delay between requests."""
        while not self.can_request():
            log_action("browser-agent", "rate_limit_wait", None, "waiting",
                       f"Hour: {self._state['hour_count']}/{self.max_per_hour}, "
                       f"Day: {self._state['day_count']}/{self.max_per_day}")
            time.sleep(5)
            self._rotate_windows()

        # Enforce minimum delay between requests
        elapsed_ms = (time.time() - self._last_request_time) * 1000
        if elapsed_ms < self.min_delay_ms and self._last_request_time > 0:
            sleep_s = (self.min_delay_ms - elapsed_ms) / 1000.0
            time.sleep(sleep_s)

    def record_request(self):
        """Record that a request was made."""
        self._rotate_windows()
        self._state["hour_count"] += 1
        self._state["day_count"] += 1
        self._last_request_time = time.time()
        self._save_state()

    def get_usage(self) -> dict:
        """Return current usage stats."""
        self._rotate_windows()
        return {
            "hour_count": self._state["hour_count"],
            "hour_limit": self.max_per_hour,
            "day_count": self._state["day_count"],
            "day_limit": self.max_per_day,
            "hour_remaining": self.max_per_hour - self._state["hour_count"],
            "day_remaining": self.max_per_day - self._state["day_count"],
        }


class CacheManager:
    """
    File-based cache with configurable TTLs per content type.
    Keys are SHA-256 hashes of the URL + content type.
    """

    DEFAULT_TTLS = {
        "competitor": 24,
        "static": 168,
        "review": 48,
        "audit": 72,
        "search": 12,
        "default": 24,
    }

    def __init__(self, cache_dir: str = CACHE_DIR, ttls: Optional[dict] = None):
        self.cache_dir = cache_dir
        self.ttls = ttls or self.DEFAULT_TTLS
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_key(self, url: str, content_type: str = "default") -> str:
        """Generate a deterministic cache key from URL and content type."""
        raw = f"{url}::{content_type}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, key: str) -> str:
        """Return the file path for a cache entry."""
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, url: str, content_type: str = "default") -> Optional[dict]:
        """
        Retrieve a cached entry if it exists and hasn't expired.
        Returns the cached data dict or None.
        """
        key = self._cache_key(url, content_type)
        path = self._cache_path(key)

        if not os.path.exists(path):
            return None

        try:
            with open(path, "r") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

        # Check TTL
        cached_at = datetime.fromisoformat(entry["cached_at"])
        ttl_hours = self.ttls.get(content_type, self.ttls["default"])
        if datetime.now(timezone.utc) - cached_at > timedelta(hours=ttl_hours):
            # Expired, remove the file
            try:
                os.remove(path)
            except OSError:
                pass
            return None

        return entry["data"]

    def set(self, url: str, data: dict, content_type: str = "default"):
        """Store data in the cache."""
        key = self._cache_key(url, content_type)
        path = self._cache_path(key)

        entry = {
            "url": url,
            "content_type": content_type,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

        os.makedirs(self.cache_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump(entry, f, indent=2)

    def invalidate(self, url: str, content_type: str = "default"):
        """Remove a specific cache entry."""
        key = self._cache_key(url, content_type)
        path = self._cache_path(key)
        if os.path.exists(path):
            os.remove(path)

    def clear_expired(self) -> int:
        """Remove all expired cache entries. Returns count of removed entries."""
        removed = 0
        if not os.path.exists(self.cache_dir):
            return 0

        for filename in os.listdir(self.cache_dir):
            if not filename.endswith(".json") or filename.startswith("_"):
                continue
            path = os.path.join(self.cache_dir, filename)
            try:
                with open(path, "r") as f:
                    entry = json.load(f)
                cached_at = datetime.fromisoformat(entry["cached_at"])
                content_type = entry.get("content_type", "default")
                ttl_hours = self.ttls.get(content_type, self.ttls["default"])
                if datetime.now(timezone.utc) - cached_at > timedelta(hours=ttl_hours):
                    os.remove(path)
                    removed += 1
            except (json.JSONDecodeError, IOError, KeyError):
                # Corrupt entry, remove it
                try:
                    os.remove(path)
                    removed += 1
                except OSError:
                    pass

        return removed


class RobotsTxtChecker:
    """
    Checks robots.txt compliance before visiting any page.
    Caches parsed robots.txt files in memory for the session
    and on disk with a 24-hour TTL.
    """

    def __init__(self, user_agent: str = "NeverMissBot"):
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._cache = CacheManager(ttls={"robots": 24, "default": 24})

    def _get_robots_url(self, url: str) -> str:
        """Extract the robots.txt URL for a given page URL."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _get_domain_key(self, url: str) -> str:
        """Extract the domain from a URL for use as a cache key."""
        parsed = urlparse(url)
        return parsed.netloc

    def is_allowed(self, url: str) -> bool:
        """
        Check if the given URL is allowed by the site's robots.txt.
        Returns True if allowed or if robots.txt cannot be fetched (permissive fallback).
        """
        domain = self._get_domain_key(url)

        # Check in-memory cache first
        if domain in self._parsers:
            return self._parsers[domain].can_fetch(self.user_agent, url)

        # Check disk cache
        robots_url = self._get_robots_url(url)
        cached = self._cache.get(robots_url, "robots")
        if cached is not None:
            parser = RobotFileParser()
            parser.parse(cached.get("lines", []))
            self._parsers[domain] = parser
            return parser.can_fetch(self.user_agent, url)

        # Fetch robots.txt fresh
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
            # Cache the raw lines for disk persistence
            raw_lines = []
            if hasattr(parser, "entries"):
                # Re-fetch as text for caching
                import urllib.request
                req = urllib.request.Request(robots_url, headers={
                    "User-Agent": get_random_user_agent()
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw_text = resp.read().decode("utf-8", errors="replace")
                    raw_lines = raw_text.splitlines()
            self._cache.set(robots_url, {"lines": raw_lines}, "robots")
        except Exception:
            # If we can't fetch robots.txt, assume everything is allowed
            # but still cache the failure to avoid repeated attempts
            self._cache.set(robots_url, {"lines": []}, "robots")

        self._parsers[domain] = parser
        return parser.can_fetch(self.user_agent, url)

    def is_allowed_wildcard(self, url: str) -> bool:
        """
        Check robots.txt for both our custom user agent and the wildcard (*).
        Returns True only if both checks pass.
        """
        domain = self._get_domain_key(url)
        if domain not in self._parsers:
            # Trigger a fetch
            self.is_allowed(url)
        if domain in self._parsers:
            parser = self._parsers[domain]
            return parser.can_fetch(self.user_agent, url) and parser.can_fetch("*", url)
        return True


def validate_url(url: str) -> dict:
    """
    Validate a URL for safety and correctness.
    Returns {"valid": bool, "reason": str, "normalized": str}.
    """
    config = _load_config()
    allowed_schemes = config.get("security", {}).get("allowed_schemes", ["http", "https"])
    blocked_domains = config.get("security", {}).get("blocked_domains", [])

    if not url or not isinstance(url, str):
        return {"valid": False, "reason": "Empty or non-string URL", "normalized": ""}

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return {"valid": False, "reason": "Unparseable URL", "normalized": ""}

    if parsed.scheme not in allowed_schemes:
        return {"valid": False, "reason": f"Scheme '{parsed.scheme}' not allowed", "normalized": ""}

    if not parsed.netloc:
        return {"valid": False, "reason": "No domain found in URL", "normalized": ""}

    domain = parsed.netloc.lower().split(":")[0]
    for blocked in blocked_domains:
        if domain == blocked or domain.endswith("." + blocked):
            return {"valid": False, "reason": f"Domain '{domain}' is blocked", "normalized": ""}

    # Block private/internal IPs
    if domain in ("localhost", "127.0.0.1", "0.0.0.0") or domain.startswith("192.168.") or domain.startswith("10."):
        return {"valid": False, "reason": "Internal/private addresses not allowed", "normalized": ""}

    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"

    return {"valid": True, "reason": "OK", "normalized": normalized}


def extract_domain(url: str) -> str:
    """Extract the domain name from a URL, stripping www prefix."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    domain = parsed.netloc.lower().split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def get_screenshot_path(url: str, suffix: str = "") -> str:
    """
    Generate an organized screenshot file path.
    Format: data/browser_screenshots/{date}/{domain}/{timestamp}{suffix}.png
    """
    config = _load_config()
    base_dir = os.path.join(DATA_DIR, "..",
                            config.get("data_paths", {}).get("screenshots", "data/browser_screenshots"))
    # Simplify to use DATA_DIR directly
    base_dir = os.path.join(DATA_DIR, "browser_screenshots")
    domain = extract_domain(url)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    timestamp = datetime.now(timezone.utc).strftime("%H%M%S")

    dir_path = os.path.join(base_dir, date_str, domain)
    os.makedirs(dir_path, exist_ok=True)

    filename = f"{timestamp}{suffix}.png"
    return os.path.join(dir_path, filename)
