#!/usr/bin/env python3
"""
Outreach Sequencer — Skill 2
Generates and sends personalized cold email sequences via the Instantly.ai API.
Manages variant rotation, inbox warmup, follow-up cadence, bounce monitoring,
and daily send limits. All email copy is generated via Groq / Llama 3.1 70B.
"""

import argparse
import json
import logging
import os
import random
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
DATA_DIR = PROJECT_ROOT / "data"

# CRM engine & QA guard imports (sibling skills)
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "crm-engine"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "qa-guard"))

import crm_engine  # noqa: E402
import qa_guard    # noqa: E402

# ---------------------------------------------------------------------------
# Logger (console)
# ---------------------------------------------------------------------------
logger = logging.getLogger("outreach-sequencer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
    logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# Load config once at import
# ---------------------------------------------------------------------------
with open(CONFIG_PATH, "r") as _f:
    CONFIG = json.load(_f)

WARMUP_SCHEDULE = CONFIG["warmup_schedule"]
SEND_WINDOW = CONFIG["send_window"]
VARIANT_CFG = CONFIG["variant_rotation"]
FOLLOWUP_CFG = CONFIG["follow_up_sequence"]
INBOX_HEALTH = CONFIG["inbox_health"]
QA_GATE = CONFIG["qa_gate"]
LLM_CONFIG = CONFIG["llm"]
VERTICALS = CONFIG["verticals"]
DATA_PATHS = CONFIG["data_paths"]

LOG_PATH = PROJECT_ROOT / DATA_PATHS["system_log"]
SEND_LOG_PATH = PROJECT_ROOT / DATA_PATHS["send_log"]
WARMUP_TRACKER_PATH = PROJECT_ROOT / DATA_PATHS["warmup_tracker"]

# ---------------------------------------------------------------------------
# Variant prompt templates
# ---------------------------------------------------------------------------
VARIANT_PROMPTS = {
    "A": (
        "Write a casual, peer-to-peer cold email from one small business owner to another. "
        "Tone: friendly, conversational, like texting a colleague. Short sentences. "
        "No formal greetings. Reference their specific business naturally. "
        "Product is a call-answering system at $297/mo. Never say 'AI', 'bot', or 'automated' "
        "— use 'system' or 'tool' instead."
    ),
    "B": (
        "Write a direct, numbers-driven cold email. Lead with a specific stat about missed "
        "calls costing money in their vertical. Be blunt and confident. Include a concrete "
        "dollar figure for missed-call cost. Product is a call-answering system at $297/mo. "
        "Never say 'AI', 'bot', or 'automated' — use 'system' or 'tool' instead."
    ),
    "C": (
        "Write a curiosity-driven cold email that opens with a compelling question about "
        "their business. Make them think. Short, punchy. End with a low-friction CTA. "
        "Product is a call-answering system at $297/mo. Never say 'AI', 'bot', or 'automated' "
        "— use 'system' or 'tool' instead."
    ),
}

SEQUENCE_CONTEXT = {
    1: "This is the first cold email — introduce the value prop.",
    2: "This is follow-up #1 (sent +3 days). Reference the first email briefly. Add a new angle or proof point.",
    3: "This is follow-up #2 (sent +4 days after FU1). Shorter. Add urgency or a case study.",
    4: "This is the breakup email (final follow-up, +5 days after FU2). Keep it very short. "
       "Say something like 'I will not follow up again' and leave the door open.",
}

# ---------------------------------------------------------------------------
# Logging (structured, matches crm-engine pattern)
# ---------------------------------------------------------------------------

def _log(action: str, lead_id: Optional[str], result: str, details: str,
         tokens_estimated: int = 0, cost_estimated: float = 0.0):
    """Append a structured log entry to system_log.jsonl."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "outreach-sequencer",
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": f"{LLM_CONFIG['provider']}/{LLM_CONFIG['model']}" if tokens_estimated else "none",
        "tokens_estimated": tokens_estimated,
        "cost_estimated": cost_estimated,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Send log helpers
# ---------------------------------------------------------------------------

def _load_send_log() -> list:
    """Load the send log from disk."""
    if SEND_LOG_PATH.exists():
        with open(SEND_LOG_PATH, "r") as f:
            return json.load(f)
    return []


def _save_send_log(log: list):
    """Persist the send log to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEND_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def _load_warmup_tracker() -> dict:
    """Load warmup tracker (tracks first-send date per inbox)."""
    if WARMUP_TRACKER_PATH.exists():
        with open(WARMUP_TRACKER_PATH, "r") as f:
            return json.load(f)
    return {"first_send_date": None, "paused_inboxes": []}


def _save_warmup_tracker(tracker: dict):
    """Persist warmup tracker to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(WARMUP_TRACKER_PATH, "w") as f:
        json.dump(tracker, f, indent=2)


# ---------------------------------------------------------------------------
# Core helper functions
# ---------------------------------------------------------------------------

def _get_current_warmup_limit() -> int:
    """Return the daily send limit based on weeks since first send."""
    tracker = _load_warmup_tracker()
    first_send = tracker.get("first_send_date")
    if not first_send:
        return WARMUP_SCHEDULE["week_1"]

    first_dt = datetime.fromisoformat(first_send)
    now = datetime.now(timezone.utc)
    days_elapsed = (now - first_dt).days
    week = (days_elapsed // 7) + 1

    if week <= 1:
        return WARMUP_SCHEDULE["week_1"]
    elif week == 2:
        return WARMUP_SCHEDULE["week_2"]
    elif week == 3:
        return WARMUP_SCHEDULE["week_3"]
    elif week == 4:
        return WARMUP_SCHEDULE["week_4"]
    else:
        return WARMUP_SCHEDULE["week_5_plus"]


def _get_todays_send_count() -> int:
    """Count how many emails were sent today (UTC)."""
    log = _load_send_log()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for entry in log if entry.get("sent_at", "").startswith(today))


def _is_in_send_window() -> bool:
    """Check if the current hour (UTC fallback) is within the configured send window."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    return SEND_WINDOW["start_hour"] <= hour < SEND_WINDOW["end_hour"]


def _pick_variant(lead: dict) -> str:
    """Pick the next variant for a lead, rotating evenly and avoiding repeats within a sequence."""
    variants = VARIANT_CFG["variants"]
    # Check what variants have already been used for this lead
    send_log = _load_send_log()
    used_variants = [
        entry["variant"] for entry in send_log
        if entry.get("lead_id") == lead.get("id")
    ]
    # Filter out already-used variants
    available = [v for v in variants if v not in used_variants]
    if not available:
        # All used — pick the least-recently-used globally for balance
        available = variants

    # Count global usage for even rotation
    global_counts = {v: 0 for v in available}
    for entry in send_log:
        v = entry.get("variant")
        if v in global_counts:
            global_counts[v] += 1

    min_count = min(global_counts.values())
    least_used = [v for v, c in global_counts.items() if c == min_count]
    return random.choice(least_used)


def _get_sequence_number(lead: dict) -> int:
    """Determine which email in the sequence this lead should receive next (1-based)."""
    send_log = _load_send_log()
    prior_sends = [e for e in send_log if e.get("lead_id") == lead.get("id")]
    return len(prior_sends) + 1


def _get_vertical_costs(lead: dict) -> tuple:
    """Return (low, high) missed-call cost for a lead's vertical."""
    vertical = lead.get("vertical", "").lower().replace(" ", "_")
    if vertical in VERTICALS:
        v = VERTICALS[vertical]
        return v["missed_call_cost_low"], v["missed_call_cost_high"]
    # Default fallback
    return 500, 2500


# ---------------------------------------------------------------------------
# LLM: Groq / Llama email generation
# ---------------------------------------------------------------------------

def _generate_email_copy(lead: dict, variant: str, sequence_number: int) -> Optional[dict]:
    """
    Use Groq / Llama 3.1 70B to generate a personalized email subject + body.

    Returns {"subject": str, "body": str} or None on failure.
    """
    api_key = os.environ.get(LLM_CONFIG["api_key_env"])
    if not api_key:
        _log("generate_email", lead.get("id"), "failure",
             f"Missing env var {LLM_CONFIG['api_key_env']}")
        return None

    cost_low, cost_high = _get_vertical_costs(lead)
    variant_prompt = VARIANT_PROMPTS[variant]
    sequence_ctx = SEQUENCE_CONTEXT.get(sequence_number, SEQUENCE_CONTEXT[1])

    system_prompt = (
        "You are an expert cold-email copywriter for a call-answering system sold to "
        "home-service businesses. You write short, punchy emails that feel human. "
        "RULES: Never say 'AI', 'bot', or 'automated'. Always say 'system' or 'tool'. "
        "Price is $297/mo. Keep subject under 50 chars. Keep body under 100 words. "
        "No emojis. No exclamation marks in subject. Respond ONLY with valid JSON: "
        '{"subject": "...", "body": "..."}'
    )

    user_prompt = (
        f"Variant style: {variant_prompt}\n\n"
        f"Sequence context: {sequence_ctx}\n\n"
        f"Lead details:\n"
        f"- Name: {lead.get('first_name', '')} {lead.get('last_name', '')}\n"
        f"- Company: {lead.get('company', '')}\n"
        f"- Vertical: {lead.get('vertical', '')}\n"
        f"- City: {lead.get('city', '')}\n"
        f"- State: {lead.get('state', '')}\n"
        f"- Missed-call cost range: ${cost_low}–${cost_high} per missed call\n\n"
        f"Generate the email now. JSON only, no markdown."
    )

    payload = {
        "model": LLM_CONFIG["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LLM_CONFIG["temperature"],
        "max_tokens": 512,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    url = "https://api.groq.com/openai/v1/chat/completions"

    for attempt in range(LLM_CONFIG["max_retries"] + 1):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=LLM_CONFIG["timeout_seconds"]) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            content = result["choices"][0]["message"]["content"].strip()
            # Parse JSON from response (handle possible markdown wrapping)
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            email_data = json.loads(content)
            tokens_used = result.get("usage", {}).get("total_tokens", 0)
            _log("generate_email", lead.get("id"), "success",
                 f"Variant={variant} seq={sequence_number} tokens={tokens_used}",
                 tokens_estimated=tokens_used,
                 cost_estimated=0.0)
            return email_data

        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            if attempt < LLM_CONFIG["max_retries"]:
                time.sleep(2 ** attempt)
                continue
            _log("generate_email", lead.get("id"), "failure",
                 f"Groq API failed after {attempt + 1} attempts: {e}")
            return None


# ---------------------------------------------------------------------------
# Instantly.ai API
# ---------------------------------------------------------------------------

def _send_via_instantly(email: str, subject: str, body: str,
                        campaign_id: str, api_key: str) -> dict:
    """
    Add a lead to an Instantly.ai campaign, which triggers the email send.

    Returns {"success": bool, "error": str | None}.
    """
    url = f"{CONFIG['instantly']['base_url']}/lead/add?api_key={api_key}"
    payload = {
        "campaign_id": campaign_id,
        "email": email,
        "personalization": {
            "subject": subject,
            "body": body,
        },
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=CONFIG["instantly"]["timeout_seconds"]) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return {"success": True, "error": None, "response": result}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"HTTP {e.code}: {error_body}"}
    except urllib.error.URLError as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Follow-up scheduling
# ---------------------------------------------------------------------------

def _schedule_followups(lead: dict, sequence_number: int):
    """
    Queue follow-up emails at configured intervals.
    Writes scheduled entries to the send log with status 'scheduled'.
    """
    if sequence_number >= 4:
        # Already sent the breakup email, no more follow-ups
        return

    intervals = {
        1: FOLLOWUP_CFG["follow_up_1_days"],
        2: FOLLOWUP_CFG["follow_up_2_days"],
        3: FOLLOWUP_CFG["follow_up_3_days"],
    }

    next_seq = sequence_number + 1
    if next_seq > 4:
        return

    days_offset = intervals.get(sequence_number, 3)
    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=days_offset)).isoformat()

    send_log = _load_send_log()
    # Check if follow-up is already scheduled
    already_scheduled = any(
        e.get("lead_id") == lead.get("id")
        and e.get("sequence_number") == next_seq
        for e in send_log
    )
    if already_scheduled:
        return

    send_log.append({
        "lead_id": lead.get("id"),
        "email": lead.get("email"),
        "sequence_number": next_seq,
        "status": "scheduled",
        "scheduled_at": scheduled_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_send_log(send_log)

    _log("schedule_followup", lead.get("id"), "success",
         f"Follow-up #{next_seq} scheduled for {scheduled_at}")


def _get_due_followups() -> list:
    """Return scheduled follow-ups that are due now."""
    send_log = _load_send_log()
    now = datetime.now(timezone.utc).isoformat()
    due = []
    for entry in send_log:
        if (entry.get("status") == "scheduled"
                and entry.get("scheduled_at", "") <= now):
            due.append(entry)
    return due


# ---------------------------------------------------------------------------
# Bounce rate monitoring
# ---------------------------------------------------------------------------

def _check_bounce_rates() -> dict:
    """
    Analyze bounce rates from the send log.
    Returns {"rate_pct": float, "action": "ok" | "warning" | "pause"}.
    """
    send_log = _load_send_log()
    sent = [e for e in send_log if e.get("status") == "sent"]
    bounced = [e for e in send_log if e.get("status") == "bounced"]

    total_sent = len(sent) + len(bounced)
    if total_sent == 0:
        return {"rate_pct": 0.0, "action": "ok", "total_sent": 0, "total_bounced": 0}

    rate = (len(bounced) / total_sent) * 100

    if rate > INBOX_HEALTH["bounce_pause_threshold_pct"]:
        action = "pause"
        _log("bounce_check", None, "critical",
             f"Bounce rate {rate:.1f}% exceeds {INBOX_HEALTH['bounce_pause_threshold_pct']}% — PAUSING inbox")
        if INBOX_HEALTH["pause_on_exceed"]:
            tracker = _load_warmup_tracker()
            if "default" not in tracker.get("paused_inboxes", []):
                tracker.setdefault("paused_inboxes", []).append("default")
                _save_warmup_tracker(tracker)
    elif rate > INBOX_HEALTH["bounce_warning_threshold_pct"]:
        action = "warning"
        _log("bounce_check", None, "warning",
             f"Bounce rate {rate:.1f}% exceeds {INBOX_HEALTH['bounce_warning_threshold_pct']}% warning threshold")
    else:
        action = "ok"

    return {
        "rate_pct": round(rate, 2),
        "action": action,
        "total_sent": len(sent),
        "total_bounced": len(bounced),
    }


def _is_inbox_paused() -> bool:
    """Check if the inbox is currently paused due to bounce rate."""
    tracker = _load_warmup_tracker()
    return len(tracker.get("paused_inboxes", [])) > 0


# ---------------------------------------------------------------------------
# Main outreach cycle
# ---------------------------------------------------------------------------

def run_outreach_cycle():
    """
    Main entry point — called every 30 minutes by cron.

    1. Check inbox health (bounce rates, paused status)
    2. Get qualified leads from CRM
    3. Check warmup limits
    4. Generate, QA-check, and send emails
    5. Schedule follow-ups
    6. Update CRM status
    """
    _log("run_cycle", None, "start", "Outreach cycle starting")

    # --- Pre-flight checks ---
    if _is_inbox_paused():
        _log("run_cycle", None, "skipped", "Inbox is paused due to high bounce rate")
        logger.warning("Inbox paused — skipping outreach cycle")
        return {"status": "paused", "sent": 0, "reason": "inbox_paused"}

    bounce_status = _check_bounce_rates()
    if bounce_status["action"] == "pause":
        _log("run_cycle", None, "skipped", "Inbox paused after bounce check")
        return {"status": "paused", "sent": 0, "reason": "bounce_rate_exceeded"}

    daily_limit = _get_current_warmup_limit()
    todays_count = _get_todays_send_count()
    remaining = daily_limit - todays_count

    if remaining <= 0:
        _log("run_cycle", None, "skipped",
             f"Daily limit reached ({todays_count}/{daily_limit})")
        logger.info(f"Daily send limit reached: {todays_count}/{daily_limit}")
        return {"status": "limit_reached", "sent": 0, "daily_limit": daily_limit}

    # --- Gather leads ---
    # New leads for initial outreach
    new_leads = crm_engine.get_leads_for_outreach()
    # Due follow-ups
    due_followups = _get_due_followups()

    campaign_id = os.environ.get("INSTANTLY_CAMPAIGN_ID", "")
    instantly_key = os.environ.get(CONFIG["instantly"]["api_key_env"], "")

    if not instantly_key:
        _log("run_cycle", None, "failure",
             f"Missing env var {CONFIG['instantly']['api_key_env']}")
        return {"status": "error", "sent": 0, "reason": "missing_api_key"}

    sent_count = 0

    # --- Process due follow-ups first ---
    for followup in due_followups:
        if sent_count >= remaining:
            break

        lead_id = followup.get("lead_id")
        lead = crm_engine.get_lead(lead_id)
        if not lead:
            _log("send_followup", lead_id, "skipped", "Lead not found in CRM")
            continue

        # Stop on reply or bounce
        if lead.get("status") in ("replied", "qualified", "booked", "lost"):
            _mark_followup_cancelled(followup, "lead_status_changed")
            continue

        if crm_engine.is_suppressed(lead.get("email", "")):
            _mark_followup_cancelled(followup, "suppressed")
            continue

        seq_num = followup.get("sequence_number", 2)
        result = _generate_and_send(lead, seq_num, campaign_id, instantly_key)
        if result.get("sent"):
            sent_count += 1
            _mark_followup_sent(followup)
            _schedule_followups(lead, seq_num)

    # --- Process new leads ---
    for lead in new_leads:
        if sent_count >= remaining:
            break

        if crm_engine.is_suppressed(lead.get("email", "")):
            _log("send_initial", lead.get("id"), "skipped", "Lead is suppressed")
            continue

        seq_num = _get_sequence_number(lead)
        if seq_num > 1:
            # Already contacted; skip (follow-ups are handled above)
            continue

        result = _generate_and_send(lead, seq_num, campaign_id, instantly_key)
        if result.get("sent"):
            sent_count += 1
            # Update CRM status to contacted
            crm_engine.update_status(
                lead.get("id"), "contacted",
                changed_by="outreach-sequencer",
                reason=f"Initial outreach sent (variant {result.get('variant', '?')})"
            )
            crm_engine.add_conversation_message(
                lead.get("id"), "outbound",
                f"[Email seq={seq_num} variant={result.get('variant', '?')}] "
                f"Subject: {result.get('subject', '')}"
            )
            # Schedule follow-ups
            _schedule_followups(lead, seq_num)

            # Record first send date for warmup tracking
            tracker = _load_warmup_tracker()
            if not tracker.get("first_send_date"):
                tracker["first_send_date"] = datetime.now(timezone.utc).isoformat()
                _save_warmup_tracker(tracker)

    _log("run_cycle", None, "complete",
         f"Cycle complete: sent={sent_count}, limit={daily_limit}, "
         f"remaining={remaining - sent_count}")
    logger.info(f"Outreach cycle complete: {sent_count} sent, "
                f"{remaining - sent_count} remaining of {daily_limit} daily limit")

    return {"status": "complete", "sent": sent_count, "daily_limit": daily_limit}


def _generate_and_send(lead: dict, sequence_number: int,
                       campaign_id: str, api_key: str) -> dict:
    """
    Generate email copy, run QA gate, and send via Instantly.
    Returns {"sent": bool, "variant": str, "subject": str}.
    """
    lead_id = lead.get("id")
    variant = _pick_variant(lead)
    max_regen = QA_GATE.get("max_regeneration_attempts", 2)

    for attempt in range(max_regen + 1):
        # Generate copy
        email_data = _generate_email_copy(lead, variant, sequence_number)
        if not email_data:
            _log("generate_and_send", lead_id, "failure",
                 f"Email generation failed (attempt {attempt + 1})")
            continue

        subject = email_data.get("subject", "")
        body = email_data.get("body", "")

        # Run QA gate
        qa_result = qa_guard.check_email(
            subject=subject,
            body=body,
            email_type="cold",
            sequence_number=sequence_number,
            variant=variant,
            lead_id=lead_id,
        )

        if qa_result["passed"]:
            # QA passed — send via Instantly
            send_result = _send_via_instantly(
                email=lead.get("email", ""),
                subject=subject,
                body=body,
                campaign_id=campaign_id,
                api_key=api_key,
            )

            if send_result["success"]:
                # Log the send
                send_log = _load_send_log()
                # Add randomized jitter to avoid sending exactly on the hour
                send_log.append({
                    "lead_id": lead_id,
                    "email": lead.get("email"),
                    "subject": subject,
                    "variant": variant,
                    "sequence_number": sequence_number,
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                })
                _save_send_log(send_log)

                _log("send_email", lead_id, "success",
                     f"Sent variant={variant} seq={sequence_number} to {lead.get('email')}")
                return {"sent": True, "variant": variant, "subject": subject}
            else:
                _log("send_email", lead_id, "failure",
                     f"Instantly API error: {send_result['error']}")
                return {"sent": False, "variant": variant, "subject": subject}
        else:
            _log("qa_rejected", lead_id, "warning",
                 f"QA rejected (attempt {attempt + 1}/{max_regen + 1}): "
                 f"{qa_result['reasons']}")

            if qa_result.get("skip_lead"):
                _log("qa_skip_lead", lead_id, "warning",
                     "QA exhausted retries — skipping lead for this cycle")
                return {"sent": False, "variant": variant, "subject": subject}

    # All regeneration attempts failed
    if QA_GATE.get("skip_on_failure"):
        _log("generate_and_send", lead_id, "skipped",
             f"All {max_regen + 1} QA attempts failed — skipping lead")
    return {"sent": False, "variant": variant, "subject": ""}


def _mark_followup_sent(followup: dict):
    """Update a scheduled follow-up's status to 'sent' in the send log."""
    send_log = _load_send_log()
    for entry in send_log:
        if (entry.get("lead_id") == followup.get("lead_id")
                and entry.get("sequence_number") == followup.get("sequence_number")
                and entry.get("status") == "scheduled"):
            entry["status"] = "sent"
            entry["sent_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save_send_log(send_log)


def _mark_followup_cancelled(followup: dict, reason: str):
    """Cancel a scheduled follow-up."""
    send_log = _load_send_log()
    for entry in send_log:
        if (entry.get("lead_id") == followup.get("lead_id")
                and entry.get("sequence_number") == followup.get("sequence_number")
                and entry.get("status") == "scheduled"):
            entry["status"] = "cancelled"
            entry["cancelled_reason"] = reason
            entry["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save_send_log(send_log)
    _log("cancel_followup", followup.get("lead_id"), "info",
         f"Follow-up #{followup.get('sequence_number')} cancelled: {reason}")


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_check_warmup():
    """Print current warmup status."""
    limit = _get_current_warmup_limit()
    sent_today = _get_todays_send_count()
    tracker = _load_warmup_tracker()
    first_send = tracker.get("first_send_date", "not started")

    print(f"Warmup Status:")
    print(f"  First send date: {first_send}")
    print(f"  Daily limit:     {limit}")
    print(f"  Sent today:      {sent_today}")
    print(f"  Remaining:       {max(0, limit - sent_today)}")
    print(f"  Paused inboxes:  {tracker.get('paused_inboxes', [])}")


def cmd_inbox_health():
    """Print inbox health report."""
    bounce = _check_bounce_rates()
    paused = _is_inbox_paused()

    print(f"Inbox Health Report:")
    print(f"  Total sent:    {bounce['total_sent']}")
    print(f"  Total bounced: {bounce['total_bounced']}")
    print(f"  Bounce rate:   {bounce['rate_pct']}%")
    print(f"  Status:        {bounce['action'].upper()}")
    print(f"  Inbox paused:  {paused}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outreach Sequencer")
    parser.add_argument("--run", action="store_true",
                        help="Run the outreach cycle")
    parser.add_argument("--check-warmup", action="store_true",
                        help="Show warmup status")
    parser.add_argument("--inbox-health", action="store_true",
                        help="Show inbox health report")
    args = parser.parse_args()

    if args.run:
        result = run_outreach_cycle()
        print(json.dumps(result, indent=2))
    elif args.check_warmup:
        cmd_check_warmup()
    elif args.inbox_health:
        cmd_inbox_health()
    else:
        parser.print_help()
