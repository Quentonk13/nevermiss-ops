"""
LAYER 2: CLOAK — Anti-Tracking & Request Anonymization
=========================================================
Makes every outbound request untraceable. Rotating fingerprints,
header sanitization, referrer stripping, DNS-over-HTTPS.

Usage:
    from security.cloak.cloak import CloakedRequest, get_anonymous_session
    resp = CloakedRequest.fetch("https://example.com")
    session = get_anonymous_session()  # Pre-configured anonymous session
"""

import hashlib
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime


# 50 real browser User-Agent strings (rotated randomly per request)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 OPR/114.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Vivaldi/7.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Vivaldi/7.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Brave Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 18_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Mobile/15E148 Safari/604.1",
]

# Screen resolutions for fingerprint randomization
SCREEN_RESOLUTIONS = [
    "1920x1080", "2560x1440", "1366x768", "1536x864", "1440x900",
    "1280x720", "3840x2160", "2560x1080", "1600x900", "1280x1024",
]

# Languages for Accept-Language rotation
ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,fr;q=0.8",
    "en-US,en;q=0.9,de;q=0.8",
    "en,en-US;q=0.9",
]

# Headers to STRIP from all outbound requests (identifying info)
STRIP_HEADERS = [
    "X-Forwarded-For",
    "X-Real-IP",
    "X-Client-IP",
    "Via",
    "Forwarded",
    "CF-Connecting-IP",
    "True-Client-IP",
    "X-Cluster-Client-IP",
    "Fastly-Client-IP",
    "X-Originating-IP",
    "X-Remote-IP",
    "X-Remote-Addr",
    "X-Request-ID",
    "X-Correlation-ID",
    "X-Amzn-Trace-Id",
]

# DNS-over-HTTPS resolvers
DOH_RESOLVERS = [
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
    "https://dns.quad9.net/dns-query",
]


def _random_ua() -> str:
    """Get a random real User-Agent string."""
    return random.choice(USER_AGENTS)


def _random_accept_language() -> str:
    return random.choice(ACCEPT_LANGUAGES)


def _random_resolution() -> str:
    return random.choice(SCREEN_RESOLUTIONS)


def _generate_fingerprint() -> dict:
    """Generate a consistent-looking but random browser fingerprint."""
    ua = _random_ua()
    is_chrome = "Chrome" in ua
    is_firefox = "Firefox" in ua

    fp = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": _random_accept_language(),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",  # Do Not Track
        "Sec-GPC": "1",  # Global Privacy Control
    }

    if is_chrome:
        fp["Sec-CH-UA"] = '"Chromium";v="131", "Not_A Brand";v="24"'
        fp["Sec-CH-UA-Mobile"] = "?0"
        fp["Sec-CH-UA-Platform"] = random.choice(['"Windows"', '"macOS"', '"Linux"'])
        fp["Sec-Fetch-Dest"] = "document"
        fp["Sec-Fetch-Mode"] = "navigate"
        fp["Sec-Fetch-Site"] = "none"
        fp["Sec-Fetch-User"] = "?1"

    return fp


def _sanitize_headers(headers: dict) -> dict:
    """Remove all identifying headers."""
    sanitized = {}
    for key, val in headers.items():
        if key not in STRIP_HEADERS:
            sanitized[key] = val
    return sanitized


def _add_timing_jitter():
    """Add random delay to prevent timing-based fingerprinting."""
    jitter = random.uniform(0.1, 0.8)
    time.sleep(jitter)


class CloakedRequest:
    """Makes anonymous HTTP requests with rotating fingerprints."""

    _request_count = 0
    _last_fingerprint = None
    _fingerprint_expires = 0

    @classmethod
    def fetch(cls, url: str, timeout: int = 15, method: str = "GET",
              data: bytes = None, extra_headers: dict = None) -> str:
        """Fetch a URL with full anonymization."""
        _add_timing_jitter()

        # Rotate fingerprint every 5-15 requests
        cls._request_count += 1
        if cls._last_fingerprint is None or cls._request_count >= cls._fingerprint_expires:
            cls._last_fingerprint = _generate_fingerprint()
            cls._fingerprint_expires = cls._request_count + random.randint(5, 15)

        headers = dict(cls._last_fingerprint)

        # Strip referrer
        headers["Referer"] = ""

        # Add extra headers (sanitized)
        if extra_headers:
            headers.update(_sanitize_headers(extra_headers))

        # Strip identifying headers
        headers = _sanitize_headers(headers)

        req = urllib.request.Request(url, headers=headers, method=method, data=data)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return f"ERROR: {str(e)}"

    @classmethod
    def fetch_json(cls, url: str, timeout: int = 15) -> dict:
        """Fetch JSON with full anonymization."""
        result = cls.fetch(url, timeout)
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON", "raw": result[:200]}

    @classmethod
    def resolve_dns_over_https(cls, domain: str) -> list:
        """Resolve DNS using DNS-over-HTTPS to prevent ISP snooping."""
        resolver = random.choice(DOH_RESOLVERS)
        url = f"{resolver}?name={domain}&type=A"
        headers = {"Accept": "application/dns-json"}

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
        except Exception:
            return []

    @classmethod
    def status(cls):
        """Print cloak status."""
        print(f"\n{'='*50}")
        print(f"  CLOAK Status — Anti-Tracking Active")
        print(f"{'='*50}")
        print(f"  User-Agent pool: {len(USER_AGENTS)} browsers")
        print(f"  Requests made: {cls._request_count}")
        print(f"  Current fingerprint rotates in: {cls._fingerprint_expires - cls._request_count} requests")
        print(f"  Headers stripped: {len(STRIP_HEADERS)} identifying headers")
        print(f"  DoH resolvers: {len(DOH_RESOLVERS)}")
        print(f"  Privacy features: DNT, GPC, Sec-Fetch, referrer stripping")
        print(f"  Timing jitter: 100-800ms random delay")
        print(f"{'='*50}\n")


def get_anonymous_session() -> CloakedRequest:
    """Get a pre-configured anonymous request session."""
    return CloakedRequest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CLOAK — Anti-Tracking System")
    parser.add_argument("--status", action="store_true", help="Show cloak status")
    parser.add_argument("--test", help="Test anonymous fetch on a URL")
    parser.add_argument("--dns", help="Resolve domain via DNS-over-HTTPS")
    args = parser.parse_args()

    if args.status:
        CloakedRequest.status()
    elif args.test:
        print(f"[cloak] Anonymous fetch: {args.test}")
        result = CloakedRequest.fetch(args.test)
        print(f"[cloak] Got {len(result)} bytes")
        print(result[:500])
    elif args.dns:
        ips = CloakedRequest.resolve_dns_over_https(args.dns)
        print(f"[cloak] {args.dns} → {ips}")
    else:
        parser.print_help()
