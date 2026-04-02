"""
Direct Email Engine — SMTP + Instantly.ai API

Supports:
- SMTP direct sending (env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM)
- Instantly.ai REST API (env: INSTANTLY_API_KEY)
- Template variable substitution: {{first_name}}, {{company}}, {{trade}}, {{city}}
- Sending windows (8am-5pm recipient local time)
- Daily warmup limits based on account age
- Bounce tracking with auto-pause at >5% bounce rate
- JSON send log at /app/data/email_log.json
"""

import json
import os
import re
import smtplib
import time
import uuid
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # Fallback: Instantly features disabled without requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY", "")
INSTANTLY_BASE_URL = "https://api.instantly.ai/api/v1"

LOG_PATH = Path(os.getenv("EMAIL_LOG_PATH", "/app/data/email_log.json"))
ACCOUNT_CREATED = os.getenv("EMAIL_ACCOUNT_CREATED", "")  # ISO date, e.g. 2026-01-15

# Warmup schedule: account_age_days -> max_sends_per_day
WARMUP_SCHEDULE = [
    (0, 5),
    (3, 10),
    (7, 25),
    (14, 50),
    (21, 75),
    (30, 100),
    (45, 150),
    (60, 250),
    (90, 500),
]

BOUNCE_PAUSE_THRESHOLD = 0.05  # 5%

# Sending window (recipient local time)
SEND_WINDOW_START = 8   # 8 AM
SEND_WINDOW_END = 17    # 5 PM

# Template variable pattern
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def _ensure_log() -> list:
    """Load the send log or create an empty one."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_log(entries: list) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2, default=str)


def _append_log(entry: dict) -> None:
    log = _ensure_log()
    log.append(entry)
    _save_log(log)


# ---------------------------------------------------------------------------
# Warmup & rate limiting
# ---------------------------------------------------------------------------

def _account_age_days() -> int:
    if not ACCOUNT_CREATED:
        return 999  # No date set — treat as fully warmed
    try:
        created = datetime.fromisoformat(ACCOUNT_CREATED).replace(tzinfo=timezone.utc)
    except ValueError:
        return 999
    return max(0, (datetime.now(timezone.utc) - created).days)


def _daily_send_limit() -> int:
    age = _account_age_days()
    limit = WARMUP_SCHEDULE[0][1]
    for threshold_days, max_sends in WARMUP_SCHEDULE:
        if age >= threshold_days:
            limit = max_sends
    return limit


def _sends_today() -> int:
    log = _ensure_log()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for e in log if e.get("timestamp", "").startswith(today) and e.get("status") != "skipped")


def _check_warmup_budget() -> tuple[bool, int]:
    """Return (can_send, remaining) based on warmup limits."""
    limit = _daily_send_limit()
    used = _sends_today()
    remaining = max(0, limit - used)
    return remaining > 0, remaining


# ---------------------------------------------------------------------------
# Bounce tracking
# ---------------------------------------------------------------------------

def _bounce_rate() -> float:
    log = _ensure_log()
    recent = [e for e in log if e.get("status") in ("sent", "bounced")]
    if len(recent) < 20:
        return 0.0  # Not enough data
    last_100 = recent[-100:]
    bounces = sum(1 for e in last_100 if e.get("status") == "bounced")
    return bounces / len(last_100)


def _is_paused_for_bounces() -> bool:
    return _bounce_rate() > BOUNCE_PAUSE_THRESHOLD


def record_bounce(email_id: str) -> dict:
    """Mark a previously-sent email as bounced. Call this from webhook handlers."""
    log = _ensure_log()
    for entry in log:
        if entry.get("id") == email_id:
            entry["status"] = "bounced"
            entry["bounced_at"] = datetime.now(timezone.utc).isoformat()
            _save_log(log)
            return {"updated": True, "bounce_rate": round(_bounce_rate(), 4)}
    return {"updated": False, "error": "email_id not found"}


# ---------------------------------------------------------------------------
# Sending window
# ---------------------------------------------------------------------------

def _in_sending_window(utc_offset_hours: float = 0) -> bool:
    """Check whether it's currently within the sending window for the recipient."""
    now_utc = datetime.now(timezone.utc)
    recipient_time = now_utc + timedelta(hours=utc_offset_hours)
    return SEND_WINDOW_START <= recipient_time.hour < SEND_WINDOW_END


def _seconds_until_window_opens(utc_offset_hours: float = 0) -> int:
    """Seconds until the next sending window opens for the given offset."""
    now_utc = datetime.now(timezone.utc)
    recipient_time = now_utc + timedelta(hours=utc_offset_hours)
    if recipient_time.hour < SEND_WINDOW_START:
        target = recipient_time.replace(hour=SEND_WINDOW_START, minute=0, second=0, microsecond=0)
    else:
        # Window is past for today, next day
        target = (recipient_time + timedelta(days=1)).replace(hour=SEND_WINDOW_START, minute=0, second=0, microsecond=0)
    return int((target - recipient_time).total_seconds())


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _render_template(template: str, variables: dict) -> str:
    """Replace {{var_name}} placeholders with values from variables dict."""
    def replacer(match):
        key = match.group(1)
        return str(variables.get(key, match.group(0)))
    return _VAR_RE.sub(replacer, template)


# ---------------------------------------------------------------------------
# SMTP sending
# ---------------------------------------------------------------------------

def _send_smtp(to: str, subject: str, body: str, reply_to: Optional[str] = None) -> dict:
    if not SMTP_HOST or not SMTP_USER:
        return {"success": False, "error": "SMTP not configured (set SMTP_HOST, SMTP_USER, SMTP_PASS)"}

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    # Attach as HTML if it looks like HTML, otherwise plain text
    if "<html" in body.lower() or "<p>" in body.lower() or "<br" in body.lower():
        msg.attach(MIMEText(body, "html"))
    else:
        msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            if SMTP_PORT != 25:
                server.starttls()
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        return {"success": True, "method": "smtp"}
    except smtplib.SMTPException as exc:
        return {"success": False, "error": f"SMTP error: {exc}", "method": "smtp"}
    except OSError as exc:
        return {"success": False, "error": f"Connection error: {exc}", "method": "smtp"}


# ---------------------------------------------------------------------------
# Instantly.ai API
# ---------------------------------------------------------------------------

def _instantly_headers() -> dict:
    return {"Content-Type": "application/json"}


def _instantly_params() -> dict:
    return {"api_key": INSTANTLY_API_KEY}


def _send_instantly(to: str, subject: str, body: str, reply_to: Optional[str] = None) -> dict:
    if not requests:
        return {"success": False, "error": "requests library not installed — pip install requests"}
    if not INSTANTLY_API_KEY:
        return {"success": False, "error": "INSTANTLY_API_KEY not set"}

    payload = {
        "to": to,
        "subject": subject,
        "body": body,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        resp = requests.post(
            f"{INSTANTLY_BASE_URL}/unibox/emails/send",
            headers=_instantly_headers(),
            params=_instantly_params(),
            json=payload,
            timeout=30,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code in (200, 201):
            return {
                "success": True,
                "method": "instantly",
                "instantly_id": data.get("id"),
                "response": data,
            }
        return {
            "success": False,
            "method": "instantly",
            "error": f"HTTP {resp.status_code}: {data}",
        }
    except Exception as exc:
        return {"success": False, "method": "instantly", "error": str(exc)}


# ---------------------------------------------------------------------------
# Method resolution
# ---------------------------------------------------------------------------

def _resolve_method(method: str) -> str:
    """Resolve 'auto' to a concrete method based on what's configured."""
    if method == "auto":
        if INSTANTLY_API_KEY:
            return "instantly"
        if SMTP_HOST:
            return "smtp"
        return "none"
    return method


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None,
    method: str = "auto",
    variables: Optional[dict] = None,
    utc_offset: float = 0,
) -> dict:
    """
    Send a single email.

    Args:
        to: Recipient email address.
        subject: Email subject (supports {{var}} placeholders).
        body: Email body (supports {{var}} placeholders).
        reply_to: Optional reply-to address.
        method: "smtp", "instantly", or "auto" (picks first available).
        variables: Dict for template substitution, e.g. {"first_name": "Mike"}.
        utc_offset: Recipient's UTC offset in hours (for sending window check).

    Returns:
        dict with keys: id, success, method, error (if any), timestamp.
    """
    email_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Pre-flight checks
    if _is_paused_for_bounces():
        result = {
            "id": email_id,
            "success": False,
            "error": "Sending paused: bounce rate exceeds 5%",
            "bounce_rate": round(_bounce_rate(), 4),
            "status": "paused",
            "timestamp": now,
        }
        _append_log({**result, "to": to, "subject": subject})
        return result

    can_send, remaining = _check_warmup_budget()
    if not can_send:
        result = {
            "id": email_id,
            "success": False,
            "error": f"Daily warmup limit reached ({_daily_send_limit()}/day, account age {_account_age_days()}d)",
            "status": "skipped",
            "timestamp": now,
        }
        _append_log({**result, "to": to, "subject": subject})
        return result

    if not _in_sending_window(utc_offset):
        wait = _seconds_until_window_opens(utc_offset)
        result = {
            "id": email_id,
            "success": False,
            "error": f"Outside sending window (8am-5pm recipient time). Retry in {wait}s.",
            "status": "deferred",
            "retry_after_seconds": wait,
            "timestamp": now,
        }
        _append_log({**result, "to": to, "subject": subject})
        return result

    # Template rendering
    if variables:
        subject = _render_template(subject, variables)
        body = _render_template(body, variables)

    resolved = _resolve_method(method)

    if resolved == "smtp":
        send_result = _send_smtp(to, subject, body, reply_to)
    elif resolved == "instantly":
        send_result = _send_instantly(to, subject, body, reply_to)
    else:
        send_result = {"success": False, "error": "No sending method configured (set SMTP or Instantly env vars)"}

    entry = {
        "id": email_id,
        "to": to,
        "subject": subject,
        "method": send_result.get("method", resolved),
        "success": send_result.get("success", False),
        "status": "sent" if send_result.get("success") else "failed",
        "error": send_result.get("error"),
        "instantly_id": send_result.get("instantly_id"),
        "timestamp": now,
    }
    _append_log(entry)

    return {
        "id": email_id,
        "success": send_result.get("success", False),
        "method": send_result.get("method", resolved),
        "error": send_result.get("error"),
        "instantly_id": send_result.get("instantly_id"),
        "remaining_today": remaining - 1 if send_result.get("success") else remaining,
        "timestamp": now,
    }


def send_bulk(
    recipients_list: list[dict],
    subject_template: str,
    body_template: str,
    method: str = "auto",
    reply_to: Optional[str] = None,
    delay_seconds: float = 2.0,
) -> list[dict]:
    """
    Send emails to a list of recipients with per-recipient template variables.

    Args:
        recipients_list: List of dicts, each must have "email" and optionally
                         "first_name", "company", "trade", "city", "utc_offset".
        subject_template: Subject with {{var}} placeholders.
        body_template: Body with {{var}} placeholders.
        method: "smtp", "instantly", or "auto".
        reply_to: Optional reply-to address.
        delay_seconds: Pause between sends to avoid triggering rate limits.

    Returns:
        List of result dicts from send_email().
    """
    results = []

    for recipient in recipients_list:
        email = recipient.get("email")
        if not email:
            results.append({"success": False, "error": "Missing 'email' in recipient dict"})
            continue

        variables = {k: v for k, v in recipient.items() if k != "email"}
        utc_offset = float(recipient.get("utc_offset", 0))

        result = send_email(
            to=email,
            subject=subject_template,
            body=body_template,
            reply_to=reply_to,
            method=method,
            variables=variables,
            utc_offset=utc_offset,
        )
        results.append(result)

        # Bail early if we hit a hard stop
        if result.get("status") == "paused":
            # Bounce rate too high — stop all sending
            remaining = [{"email": r.get("email"), "status": "skipped", "error": "Bulk aborted: bounce pause"}
                         for r in recipients_list[len(results):]]
            results.extend(remaining)
            break

        if result.get("success") and delay_seconds > 0:
            time.sleep(delay_seconds)

    return results


def check_email_status(email_id: str) -> dict:
    """
    Check the status of a sent email.

    For Instantly-sent emails, queries the Instantly API for live status.
    For SMTP-sent emails, returns the local log entry.

    Args:
        email_id: The UUID returned by send_email().

    Returns:
        dict with status info.
    """
    log = _ensure_log()
    entry = next((e for e in log if e.get("id") == email_id), None)

    if not entry:
        return {"found": False, "error": "Email ID not found in log"}

    result = {
        "found": True,
        "id": email_id,
        "to": entry.get("to"),
        "status": entry.get("status"),
        "method": entry.get("method"),
        "timestamp": entry.get("timestamp"),
    }

    # If sent via Instantly, try to get live status
    instantly_id = entry.get("instantly_id")
    if instantly_id and INSTANTLY_API_KEY and requests:
        try:
            resp = requests.get(
                f"{INSTANTLY_BASE_URL}/unibox/emails/{instantly_id}",
                params=_instantly_params(),
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                result["instantly_status"] = data.get("status")
                result["opens"] = data.get("opens", 0)
                result["clicks"] = data.get("clicks", 0)
                result["replied"] = data.get("replied", False)
        except Exception:
            result["instantly_status"] = "lookup_failed"

    return result


def get_send_stats() -> dict:
    """
    Aggregate sending statistics from the log.

    Returns:
        dict with counts, bounce rate, daily usage, warmup info.
    """
    log = _ensure_log()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    total = len(log)
    sent = sum(1 for e in log if e.get("status") == "sent")
    failed = sum(1 for e in log if e.get("status") == "failed")
    bounced = sum(1 for e in log if e.get("status") == "bounced")
    deferred = sum(1 for e in log if e.get("status") == "deferred")
    skipped = sum(1 for e in log if e.get("status") == "skipped")
    paused = sum(1 for e in log if e.get("status") == "paused")

    today_sent = sum(1 for e in log if e.get("timestamp", "").startswith(today) and e.get("status") == "sent")

    daily_limit = _daily_send_limit()
    age = _account_age_days()
    br = _bounce_rate()

    return {
        "total_logged": total,
        "sent": sent,
        "failed": failed,
        "bounced": bounced,
        "deferred": deferred,
        "skipped": skipped,
        "paused": paused,
        "bounce_rate": round(br, 4),
        "bounce_paused": br > BOUNCE_PAUSE_THRESHOLD,
        "today": {
            "date": today,
            "sent": today_sent,
            "daily_limit": daily_limit,
            "remaining": max(0, daily_limit - today_sent),
        },
        "warmup": {
            "account_age_days": age,
            "current_daily_limit": daily_limit,
        },
        "smtp_configured": bool(SMTP_HOST and SMTP_USER),
        "instantly_configured": bool(INSTANTLY_API_KEY),
    }


# ---------------------------------------------------------------------------
# CLI quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Email Engine Status ===")
    stats = get_send_stats()
    print(json.dumps(stats, indent=2))

    # Example template rendering test
    tpl = "Hey {{first_name}}, we do {{trade}} work in {{city}} for {{company}}."
    rendered = _render_template(tpl, {
        "first_name": "Mike",
        "trade": "roofing",
        "city": "Denver",
        "company": "Acme Roofing",
    })
    print(f"\nTemplate test: {rendered}")
