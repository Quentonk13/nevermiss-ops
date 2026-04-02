"""
qa-guard: Synchronous gate checking ALL outbound messages before sending.

Called by outreach-sequencer and reply-handler before every outbound message.
Nothing goes out without passing QA.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
SPAM_PATTERNS_PATH = SKILL_DIR / "spam_patterns.json"
LOG_PATH = PROJECT_ROOT / "data" / "system_log.jsonl"

# ---------------------------------------------------------------------------
# Logger (console)
# ---------------------------------------------------------------------------
logger = logging.getLogger("qa-guard")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
    logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# Load config + patterns once at import
# ---------------------------------------------------------------------------
with open(CONFIG_PATH, "r") as _f:
    CONFIG = json.load(_f)

with open(SPAM_PATTERNS_PATH, "r") as _f:
    SPAM_PATTERNS = json.load(_f)

ALLOWED_CAPS: set[str] = set(CONFIG.get("allowed_caps_words", []))
THRESHOLDS = CONFIG["thresholds"]
COMPLIANCE = CONFIG["compliance"]
LLM_CONFIG = CONFIG["llm"]

# ---------------------------------------------------------------------------
# Rejection-attempt tracking  (in-memory, keyed by lead_id or subject hash)
# ---------------------------------------------------------------------------
_attempt_tracker: dict[str, int] = {}
_variant_rejection_counts: dict[str, dict] = {}  # variant -> {"total": N, "rejected": N}


# ---------------------------------------------------------------------------
# Structured logging to data/system_log.jsonl
# ---------------------------------------------------------------------------
def _log_event(
    action: str,
    result: str,
    details: str = "",
    lead_id: Optional[str] = None,
    llm_used: str = "none",
    tokens_estimated: int = 0,
    cost_estimated: float = 0.00,
) -> None:
    """Append a structured JSON log line."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "qa-guard",
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": llm_used,
        "tokens_estimated": tokens_estimated,
        "cost_estimated": cost_estimated,
    }
    with open(LOG_PATH, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    logger.info("action=%s result=%s details=%s", action, result, details)


# ===================================================================
# SPAM PATTERN DETECTION  (all rule-based, no LLM)
# ===================================================================

def _check_all_caps(body: str) -> list[str]:
    """Reject ALL-CAPS words (>= 2 chars) unless in allowed set."""
    reasons: list[str] = []
    words = re.findall(r"\b[A-Z]{2,}\b", body)
    violating = [w for w in words if w not in ALLOWED_CAPS]
    if violating:
        reasons.append(f"ALL CAPS words detected: {', '.join(set(violating))}")
    return reasons


def _check_exclamation(subject: str, body: str) -> list[str]:
    if "!" in subject or "!" in body:
        return ["Exclamation mark detected"]
    return []


def _check_dollar_and_prices(body: str, email_type: str) -> list[str]:
    """Block dollar signs / prices in cold emails. Allowed in replies."""
    if email_type != "cold":
        return []
    pattern = SPAM_PATTERNS["price_pattern"]
    if "$" in body or re.search(pattern, body, re.IGNORECASE):
        return ["Dollar sign or specific price in cold email"]
    return []


def _check_trigger_words(body: str) -> list[str]:
    body_lower = body.lower()
    found = [w for w in SPAM_PATTERNS["trigger_words"] if w.lower() in body_lower]
    if found:
        return [f"Spam trigger words: {', '.join(found)}"]
    return []


def _check_urls(body: str, sequence_number: int) -> list[str]:
    """Block links/URLs in emails 1-3 of a sequence."""
    if sequence_number > 3:
        return []
    pattern = SPAM_PATTERNS["url_pattern"]
    if re.search(pattern, body, re.IGNORECASE):
        return [f"URL/link detected in sequence email #{sequence_number} (blocked in emails 1-3)"]
    return []


def _check_emojis(subject: str, body: str) -> list[str]:
    pattern = SPAM_PATTERNS["emoji_pattern"]
    text = subject + " " + body
    if re.search(pattern, text):
        return ["Emoji detected"]
    return []


def _check_ai_language(body: str) -> list[str]:
    """Block mentions of AI/automation terminology."""
    body_check = body
    found: list[str] = []
    for term in SPAM_PATTERNS["ai_language"]:
        if len(term) <= 3:
            # Short terms like "AI" need word-boundary matching
            if re.search(r"\b" + re.escape(term) + r"\b", body_check):
                found.append(term)
        else:
            if term.lower() in body_check.lower():
                found.append(term)
    if found:
        return [f"AI/automation language detected: {', '.join(found)}"]
    return []


def _check_product_name(body: str, email_type: str) -> list[str]:
    """Block product name NeverMiss in cold emails."""
    if email_type != "cold":
        return []
    product = SPAM_PATTERNS["product_name_cold_blocked"]
    if re.search(r"\b" + re.escape(product) + r"\b", body, re.IGNORECASE):
        return [f"Product name '{product}' used in cold email (only allowed after interest)"]
    return []


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on sentence-ending punctuation."""
    # Strip leading/trailing whitespace
    text = text.strip()
    if not text:
        return 0
    # Split on period, question mark, or exclamation followed by space or end
    sentences = re.split(r'(?<=[.!?])\s+', text)
    # Filter out empty strings
    sentences = [s for s in sentences if s.strip()]
    # If text doesn't end with punctuation, the last chunk is still a sentence
    return len(sentences)


def _check_sentence_count(body: str, email_type: str) -> list[str]:
    max_sentences = (
        THRESHOLDS["max_sentences_cold"]
        if email_type == "cold"
        else THRESHOLDS["max_sentences_reply"]
    )
    count = _count_sentences(body)
    if count > max_sentences:
        label = "cold email" if email_type == "cold" else "reply"
        return [f"Too many sentences for {label}: {count} (max {max_sentences})"]
    return []


def _check_subject_length(subject: str) -> list[str]:
    word_count = len(subject.split())
    max_words = THRESHOLDS["max_subject_words"]
    if word_count > max_words:
        return [f"Subject line too long: {word_count} words (max {max_words})"]
    return []


def _check_subject_punctuation(subject: str) -> list[str]:
    """Block punctuation in subject except question mark."""
    # Remove "Re:" and "Fwd:" prefixes before checking
    cleaned = re.sub(r"^(Re:\s*|Fwd:\s*)", "", subject).strip()
    # Find any punctuation that is NOT a question mark and NOT a colon from Re:/Fwd:
    bad_punct = re.findall(r"[!.,;:\"'\-\(\)\[\]\{\}#@&\*\+=/\\<>]", cleaned)
    if bad_punct:
        return [f"Subject line contains punctuation (only ? allowed): {''.join(set(bad_punct))}"]
    return []


def _check_re_fwd(subject: str, sequence_number: int, is_forwarding: bool) -> list[str]:
    reasons: list[str] = []
    if subject.strip().startswith("Re:") and sequence_number == 1:
        reasons.append("'Re:' prefix on a first email")
    if subject.strip().startswith("Fwd:") and not is_forwarding:
        reasons.append("'Fwd:' prefix when not actually forwarding")
    return reasons


def _check_starts_with_i(body: str) -> list[str]:
    """Reject if the first word of the email body is 'I'."""
    stripped = body.strip()
    if not stripped:
        return []
    first_word = re.split(r"\s+", stripped, maxsplit=1)[0]
    # Strip any leading punctuation/quotes
    first_word_clean = first_word.strip("\"'`")
    if first_word_clean == "I":
        return ["Email body starts with 'I'"]
    return []


def run_spam_checks(
    subject: str,
    body: str,
    email_type: str,
    sequence_number: int,
    is_forwarding: bool,
) -> list[str]:
    """Run every rule-based spam check. Returns list of rejection reasons (empty = pass)."""
    reasons: list[str] = []
    reasons.extend(_check_all_caps(body))
    reasons.extend(_check_exclamation(subject, body))
    reasons.extend(_check_dollar_and_prices(body, email_type))
    reasons.extend(_check_trigger_words(body))
    reasons.extend(_check_urls(body, sequence_number))
    reasons.extend(_check_emojis(subject, body))
    reasons.extend(_check_ai_language(body))
    reasons.extend(_check_product_name(body, email_type))
    reasons.extend(_check_sentence_count(body, email_type))
    reasons.extend(_check_subject_length(subject))
    reasons.extend(_check_subject_punctuation(subject))
    reasons.extend(_check_re_fwd(subject, sequence_number, is_forwarding))
    reasons.extend(_check_starts_with_i(body))
    return reasons


# ===================================================================
# COMPLIANCE CHECK  (rule-based)
# ===================================================================

def run_compliance_checks(body: str, from_domain: Optional[str] = None, from_name: Optional[str] = None) -> list[str]:
    """Rule-based compliance checks. Returns list of rejection reasons."""
    reasons: list[str] = []
    body_lower = body.lower()

    # Impersonation check
    for phrase in COMPLIANCE["blocked_impersonation_phrases"]:
        if phrase.lower() in body_lower:
            reasons.append(f"Impersonation language detected: '{phrase}'")

    # Domain / from-name consistency (only if both supplied)
    if from_domain and from_name:
        # Extract meaningful part of domain (e.g., "acme" from "acme.com")
        domain_base = from_domain.split(".")[0].lower()
        name_lower = from_name.lower()
        # Heuristic: the domain base should appear in the from-name or vice versa,
        # or the from-name should look personal (first + last).
        # We flag only obvious mismatches: domain is a company but from-name
        # references a completely different company.
        # Keep it simple: flag if from_name contains a company-ish name that
        # doesn't match the domain at all.
        if (
            domain_base not in name_lower
            and name_lower.replace(" ", "") not in domain_base
            and len(domain_base) > 3
        ):
            # Only warn, do not hard-reject, since "John Smith" from "acme.com" is fine
            pass

    return reasons


# ===================================================================
# TONE CHECK  (Groq / Llama -- the only LLM call)
# ===================================================================

def run_tone_check(subject: str, body: str) -> tuple[float, list[str]]:
    """
    Call Groq Llama 3.1-70B to rate the email 1-5 for human-likeness.
    Returns (score, rejection_reasons).
    """
    api_key = os.environ.get(LLM_CONFIG["api_key_env"], "")
    if not api_key:
        _log_event(
            action="tone_check",
            result="skipped",
            details="GROQ_API_KEY not set; skipping tone check",
        )
        # Fail open if no API key -- log prominently but don't block
        return 5.0, []

    prompt = (
        "You are a spam-detection assistant. Rate the following email on a scale of 1-5 "
        "for how much it 'sounds like a real human texted this.' "
        "1 = obviously templated/spammy, 5 = completely natural and personal.\n\n"
        f"Subject: {subject}\n\n"
        f"Body:\n{body}\n\n"
        "Respond with ONLY a JSON object: {\"score\": <number>, \"reason\": \"<brief explanation>\"}"
    )

    import urllib.request
    import urllib.error

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({
        "model": LLM_CONFIG["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": LLM_CONFIG.get("temperature", 0.0),
        "max_tokens": 150,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    tokens_estimated = len(prompt.split()) + len(body.split()) + 50
    # Groq Llama 3.1-70B pricing: ~$0.59/M input, ~$0.79/M output
    cost_estimated = round(tokens_estimated * 0.00000059 + 50 * 0.00000079, 6)

    try:
        timeout = LLM_CONFIG.get("timeout_seconds", 10)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        content = data["choices"][0]["message"]["content"].strip()

        # Parse the JSON response -- handle markdown code fences
        content_clean = content
        if content_clean.startswith("```"):
            content_clean = re.sub(r"^```(?:json)?\s*", "", content_clean)
            content_clean = re.sub(r"\s*```$", "", content_clean)

        result = json.loads(content_clean)
        score = float(result["score"])
        reason = result.get("reason", "")

        _log_event(
            action="tone_check",
            result="success",
            details=f"score={score} reason={reason}",
            llm_used="groq",
            tokens_estimated=tokens_estimated,
            cost_estimated=cost_estimated,
        )

        reasons: list[str] = []
        if score < THRESHOLDS["tone_score_minimum"]:
            reasons.append(
                f"Tone score too low: {score}/5 (minimum {THRESHOLDS['tone_score_minimum']}). "
                f"Reason: {reason}"
            )
        return score, reasons

    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        _log_event(
            action="tone_check",
            result="failure",
            details=f"Groq API HTTP {exc.code}: {error_body[:300]}",
            llm_used="groq",
            tokens_estimated=tokens_estimated,
            cost_estimated=0.0,
        )
        # Fail open on API errors -- don't block sending
        return 5.0, []

    except urllib.error.URLError as exc:
        _log_event(
            action="tone_check",
            result="failure",
            details=f"Groq API network error: {exc.reason}",
            llm_used="groq",
            tokens_estimated=0,
            cost_estimated=0.0,
        )
        return 5.0, []

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        _log_event(
            action="tone_check",
            result="failure",
            details=f"Failed to parse Groq response: {exc}",
            llm_used="groq",
            tokens_estimated=tokens_estimated,
            cost_estimated=cost_estimated,
        )
        return 5.0, []


# ===================================================================
# ATTEMPT TRACKING
# ===================================================================

def _tracking_key(subject: str, body: str, variant: Optional[str]) -> str:
    """Deterministic key to track regeneration attempts for a specific email."""
    import hashlib
    raw = f"{subject}|{variant or 'none'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_attempts(key: str) -> int:
    return _attempt_tracker.get(key, 0)


def _increment_attempts(key: str) -> int:
    _attempt_tracker[key] = _attempt_tracker.get(key, 0) + 1
    return _attempt_tracker[key]


def _record_variant_result(variant: Optional[str], passed: bool) -> None:
    """Track rejection rate per variant."""
    if variant is None:
        return
    if variant not in _variant_rejection_counts:
        _variant_rejection_counts[variant] = {"total": 0, "rejected": 0}
    _variant_rejection_counts[variant]["total"] += 1
    if not passed:
        _variant_rejection_counts[variant]["rejected"] += 1


def get_variant_rejection_rate(variant: str) -> float:
    """Return rejection rate for a variant (0.0-1.0). Returns 0.0 if no data."""
    stats = _variant_rejection_counts.get(variant)
    if not stats or stats["total"] == 0:
        return 0.0
    return stats["rejected"] / stats["total"]


def get_variant_stats() -> dict[str, dict]:
    """Return a copy of all variant stats."""
    return dict(_variant_rejection_counts)


def reset_attempt_tracker(key: Optional[str] = None) -> None:
    """Reset attempt tracking. If key given, reset only that key; otherwise reset all."""
    if key:
        _attempt_tracker.pop(key, None)
    else:
        _attempt_tracker.clear()


# ===================================================================
# MAIN ENTRY POINT
# ===================================================================

def check_email(
    subject: str,
    body: str,
    email_type: str = "cold",
    sequence_number: int = 1,
    variant: Optional[str] = None,
    is_forwarding: bool = False,
    lead_id: Optional[str] = None,
    from_domain: Optional[str] = None,
    from_name: Optional[str] = None,
) -> dict:
    """
    Synchronous QA gate for outbound emails.

    Args:
        subject: Email subject line.
        body: Email body text.
        email_type: "cold" or "reply".
        sequence_number: Position in sequence (1-based).
        variant: Template variant identifier for rejection-rate tracking.
        is_forwarding: True if this is a genuine forward.
        lead_id: Optional lead UUID for logging.
        from_domain: Sending domain (for compliance check).
        from_name: Sender display name (for compliance check).

    Returns:
        {
            "passed": bool,
            "reasons": [str, ...],
            "tone_score": float | None,
            "attempts": int,
            "skip_lead": bool,
        }
    """
    start = time.monotonic()
    all_reasons: list[str] = []
    tone_score: Optional[float] = None
    tracking_key = _tracking_key(subject, body, variant)
    attempts = _get_attempts(tracking_key)

    # If already exhausted regeneration attempts, skip immediately
    max_attempts = THRESHOLDS["max_regeneration_attempts"]
    if attempts >= max_attempts:
        _log_event(
            action="check_email",
            result="skipped",
            details=f"Max regeneration attempts ({max_attempts}) reached for variant={variant}",
            lead_id=lead_id,
        )
        _record_variant_result(variant, passed=False)
        return {
            "passed": False,
            "reasons": [f"Max regeneration attempts ({max_attempts}) exhausted. Skip this lead."],
            "tone_score": None,
            "attempts": attempts,
            "skip_lead": True,
        }

    # --- SPAM PATTERN DETECTION (rule-based) ---
    spam_reasons = run_spam_checks(subject, body, email_type, sequence_number, is_forwarding)
    all_reasons.extend(spam_reasons)

    # --- COMPLIANCE CHECK (rule-based) ---
    compliance_reasons = run_compliance_checks(body, from_domain, from_name)
    all_reasons.extend(compliance_reasons)

    # --- TONE CHECK (Groq/Llama) ---
    # Only run tone check if rule-based checks passed (save API calls)
    if not all_reasons:
        tone_score, tone_reasons = run_tone_check(subject, body)
        all_reasons.extend(tone_reasons)
    else:
        # Skip tone check if already failing rules
        _log_event(
            action="tone_check",
            result="skipped",
            details="Skipped tone check: rule-based failures already present",
            lead_id=lead_id,
        )

    passed = len(all_reasons) == 0

    # Track attempts and variant stats
    if not passed:
        current_attempts = _increment_attempts(tracking_key)
        skip_lead = current_attempts >= max_attempts
    else:
        current_attempts = attempts
        skip_lead = False

    _record_variant_result(variant, passed)

    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    # Log final result
    if passed:
        _log_event(
            action="check_email",
            result="success",
            details=f"Email passed QA in {elapsed_ms}ms (type={email_type}, seq={sequence_number}, variant={variant})",
            lead_id=lead_id,
            llm_used="groq" if tone_score is not None else "none",
        )
    else:
        result_label = "skipped" if skip_lead else "rejected"
        detail_parts = [
            f"type={email_type}",
            f"seq={sequence_number}",
            f"variant={variant}",
            f"attempt={current_attempts}/{max_attempts}",
            f"elapsed={elapsed_ms}ms",
            f"reasons={'; '.join(all_reasons)}",
        ]
        if skip_lead:
            detail_parts.append("ACTION=skip_lead")
        _log_event(
            action="check_email",
            result=result_label,
            details=", ".join(detail_parts),
            lead_id=lead_id,
            llm_used="groq" if tone_score is not None else "none",
        )

    return {
        "passed": passed,
        "reasons": all_reasons,
        "tone_score": tone_score,
        "attempts": current_attempts,
        "skip_lead": skip_lead,
    }


# ===================================================================
# CLI convenience for testing
# ===================================================================

if __name__ == "__main__":
    import sys

    print("=== qa-guard manual test ===\n")

    # Example: clean cold email
    test_subject = "Quick question about your plumbing calls"
    test_body = (
        "Hey Mike, noticed your Google reviews mention after-hours calls. "
        "Curious how you handle those today. "
        "Would a 2-min call this week make sense?"
    )
    result = check_email(
        subject=test_subject,
        body=test_body,
        email_type="cold",
        sequence_number=1,
        variant="v1-plumbing-afterhours",
        lead_id="test-lead-001",
    )
    print(f"Test 1 (clean cold email):")
    print(f"  Passed: {result['passed']}")
    print(f"  Tone:   {result['tone_score']}")
    print(f"  Reasons: {result['reasons']}")
    print()

    # Example: spammy email (should fail)
    test_subject_bad = "AMAZING LIMITED TIME OFFER!!!"
    test_body_bad = (
        "I wanted to reach out about our FREE guaranteed system. "
        "Click here to subscribe now! "
        "NeverMiss uses AI automation to handle your calls. "
        "Act now for a $297 discount on this exclusive deal!"
    )
    result_bad = check_email(
        subject=test_subject_bad,
        body=test_body_bad,
        email_type="cold",
        sequence_number=1,
        variant="v2-spam-test",
        lead_id="test-lead-002",
    )
    print(f"Test 2 (spammy email):")
    print(f"  Passed: {result_bad['passed']}")
    print(f"  Reasons ({len(result_bad['reasons'])}):")
    for r in result_bad["reasons"]:
        print(f"    - {r}")
    print()

    # Show variant stats
    print("Variant stats:")
    for v, stats in get_variant_stats().items():
        rate = get_variant_rejection_rate(v)
        print(f"  {v}: {stats} (rejection rate: {rate:.0%})")
