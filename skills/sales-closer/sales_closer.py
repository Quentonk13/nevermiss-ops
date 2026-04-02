#!/usr/bin/env python3
"""
Sales Closer — Post-booking pipeline skill.
Pre-demo briefings, post-demo follow-up sequences, and win/loss tracking.
Groq/Llama for pre-demo briefs. Claude Sonnet for follow-up emails (revenue-critical).
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crm-engine'))
import crm_engine

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")
CLOSER_LOG = os.path.join(DATA_DIR, "closer_log.jsonl")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
GLOBAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Load skill config
_config = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        _config = json.load(f)

# Load global config for Calendly link etc.
CALENDLY_LINK = ""
if os.path.exists(GLOBAL_CONFIG_PATH):
    with open(GLOBAL_CONFIG_PATH) as f:
        _gc = json.load(f)
        CALENDLY_LINK = _gc.get("calendly_link", "")

# Config shortcuts
_pre_demo_cfg = _config.get("pre_demo", {})
_post_demo_cfg = _config.get("post_demo", {})
_pricing_cfg = _config.get("pricing", {})

BRIEF_MAX_WORDS = _pre_demo_cfg.get("brief_max_words", 150)
BRIEF_SEND_MINUTES_BEFORE = _pre_demo_cfg.get("brief_send_minutes_before", 30)
FOLLOWUP_DELAY_HOURS = _post_demo_cfg.get("followup_delay_hours", 24)
NUDGE_DELAY_DAYS = _post_demo_cfg.get("nudge_delay_days", 3)
MRR_PER_CLOSE = _pricing_cfg.get("mrr_per_close", 297)
SIGNUP_LINK = _post_demo_cfg.get("signup_link", "https://nevermiss.ai/signup")
FOUNDING_PRICE = _post_demo_cfg.get("founding_member_price", "$297/month")
FOUNDING_URGENCY = _post_demo_cfg.get("founding_member_urgency",
                                       "$297/month locked in, limited to first 50 founding members")

# Cost tracking
_claude_calls_today = 0
_claude_tokens_today = 0
_claude_cost_today = 0.0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(action, lead_id, result, details, llm_used="none", tokens=0, cost=0.0):
    """Append a structured log entry to system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "sales-closer",
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


def _log_closer_event(lead_id, event_type, data):
    """Append a closer-specific event to closer_log.jsonl."""
    os.makedirs(os.path.dirname(CLOSER_LOG), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lead_id": lead_id,
        "event": event_type,
        "data": data,
    }
    with open(CLOSER_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# LLM Calls
# ---------------------------------------------------------------------------

def _call_groq(prompt, max_tokens=300, temperature=0.4):
    """Call Groq API with Llama 3.1 70B for pre-demo briefs."""
    if not GROQ_API_KEY:
        _log("groq_call", None, "failure", "GROQ_API_KEY not set")
        return None

    groq_cfg = _pre_demo_cfg.get("llm", {})
    model = groq_cfg.get("model", "llama-3.1-70b-versatile")
    timeout = groq_cfg.get("timeout_seconds", 15)
    max_retries = groq_cfg.get("max_retries", 2)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=payload, timeout=timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                _log("groq_call", None, "success",
                     f"Tokens: {tokens}", "groq", tokens, 0.0)
                return text
            else:
                _log("groq_call", None, "failure",
                     f"HTTP {resp.status_code}: {resp.text[:200]}", "groq")
                if attempt < max_retries:
                    time.sleep(30 * (attempt + 1))
        except Exception as e:
            _log("groq_call", None, "failure", str(e)[:200], "groq")
            if attempt < max_retries:
                time.sleep(30 * (attempt + 1))
    return None


def _call_claude(system_prompt, user_message, max_tokens=500):
    """Call Claude API for revenue-critical follow-up emails."""
    global _claude_calls_today, _claude_tokens_today, _claude_cost_today

    if not ANTHROPIC_API_KEY:
        _log("claude_call", None, "failure", "ANTHROPIC_API_KEY not set")
        return None

    # Budget check: $50/day hard cap
    if _claude_cost_today >= 50.0:
        _log("claude_call", None, "failure",
             "Daily Claude budget cap ($50) reached. Using Groq fallback.")
        return _call_groq(f"{system_prompt}\n\n{user_message}", max_tokens)

    claude_cfg = _post_demo_cfg.get("llm", {})
    model = claude_cfg.get("model", "claude-sonnet-4-20250514")
    timeout = claude_cfg.get("timeout_seconds", 30)
    max_retries = claude_cfg.get("max_retries", 2)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload, timeout=timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["content"][0]["text"].strip()
                input_tokens = data.get("usage", {}).get("input_tokens", 0)
                output_tokens = data.get("usage", {}).get("output_tokens", 0)
                total_tokens = input_tokens + output_tokens
                # Estimate cost: ~$3/M input, ~$15/M output for Sonnet
                cost = (input_tokens * 3 / 1_000_000) + (output_tokens * 15 / 1_000_000)
                _claude_calls_today += 1
                _claude_tokens_today += total_tokens
                _claude_cost_today += cost
                _log("claude_call", None, "success",
                     f"Tokens: {total_tokens}, Cost: ${cost:.4f}, "
                     f"Day total: ${_claude_cost_today:.4f}",
                     "claude", total_tokens, cost)
                return text
            else:
                _log("claude_call", None, "failure",
                     f"HTTP {resp.status_code}: {resp.text[:200]}", "claude")
                if attempt < max_retries:
                    time.sleep(30 * (attempt + 1))
        except Exception as e:
            _log("claude_call", None, "failure", str(e)[:200], "claude")
            if attempt < max_retries:
                time.sleep(30 * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Pre-Demo Brief
# ---------------------------------------------------------------------------

def _generate_pre_demo_brief(lead):
    """Generate a pre-demo briefing using Groq/Llama. Max 150 words."""
    lead_id = lead.get("id", "unknown")
    name = lead.get("contact_name", lead.get("name", "the prospect"))
    company = lead.get("company", "their company")
    vertical = lead.get("vertical", "trade contractor")
    email = lead.get("email", "")
    objections = lead.get("objections_raised", [])
    conversation = lead.get("conversation", [])

    # Build context from conversation history
    convo_summary = ""
    if conversation:
        recent = conversation[-5:]
        convo_lines = []
        for msg in recent:
            direction = msg.get("direction", "unknown")
            text = msg.get("message", "")[:200]
            convo_lines.append(f"[{direction}] {text}")
        convo_summary = "\n".join(convo_lines)

    objection_list = ", ".join(
        o.get("type", "unknown") for o in objections
    ) if objections else "none yet"

    prompt = f"""You are preparing a concise pre-demo briefing for a sales call.
The product is NeverMiss, a $297/month missed-call text-back service for trade contractors.

Lead info:
- Name: {name}
- Company: {company}
- Vertical: {vertical}
- Email: {email}
- Objections raised so far: {objection_list}

Recent conversation:
{convo_summary if convo_summary else "No prior conversation."}

Write a briefing paragraph (UNDER {BRIEF_MAX_WORDS} words) covering:
1. What this lead likely cares about based on their vertical
2. Expected objections and how to handle them
3. Recommended close approach

Be direct and actionable. Do not use the word "AI" anywhere. Do not use filler."""

    brief = _call_groq(prompt, max_tokens=300, temperature=0.4)
    if brief:
        # Enforce word limit
        words = brief.split()
        if len(words) > BRIEF_MAX_WORDS:
            brief = " ".join(words[:BRIEF_MAX_WORDS])

        _log("pre_demo_brief", lead_id, "success",
             f"Generated {len(brief.split())} word brief")
        _log_closer_event(lead_id, "pre_demo_brief_generated", {
            "brief": brief,
            "word_count": len(brief.split()),
        })
        return brief
    else:
        _log("pre_demo_brief", lead_id, "failure", "Groq returned no content")
        return None


# ---------------------------------------------------------------------------
# Follow-Up Emails
# ---------------------------------------------------------------------------

def _generate_follow_up_email(lead, follow_up_number):
    """
    Generate a post-demo follow-up email using Claude Sonnet.
    follow_up_number: 1 = 24h personalized, 2 = 3-day nudge
    """
    lead_id = lead.get("id", "unknown")
    name = lead.get("contact_name", lead.get("name", ""))
    first_name = name.split()[0] if name else "there"
    company = lead.get("company", "your company")
    vertical = lead.get("vertical", "trade contractor")
    objections = lead.get("objections_raised", [])
    conversation = lead.get("conversation", [])

    objection_list = ", ".join(
        o.get("type", "unknown") for o in objections
    ) if objections else "none"

    # Recent conversation for context
    convo_summary = ""
    if conversation:
        recent = conversation[-5:]
        convo_lines = []
        for msg in recent:
            direction = msg.get("direction", "unknown")
            text = msg.get("message", "")[:200]
            convo_lines.append(f"[{direction}] {text}")
        convo_summary = "\n".join(convo_lines)

    system_prompt = f"""You write follow-up emails for NeverMiss, a $297/month missed-call text-back service for trade contractors.

Rules:
- Maximum 4-5 sentences
- Never say "AI" or "artificial intelligence"
- Be warm, direct, no fluff
- Relaxed QA rules: you may include links, the product name NeverMiss, and dollar amounts
- Signup link: {SIGNUP_LINK}
- Pricing: {FOUNDING_PRICE} (founding member rate, {FOUNDING_URGENCY})
- Sign off as the sender, not as NeverMiss"""

    if follow_up_number == 1:
        user_message = f"""Write a personalized 24-hour post-demo follow-up email.

Lead: {first_name} at {company} ({vertical})
Objections raised: {objection_list}

Recent conversation:
{convo_summary if convo_summary else "Demo completed, no notes."}

This should reference something specific from their demo or situation, address any objection softly, and include a clear CTA to sign up. 4-5 sentences max."""
    else:
        user_message = f"""Write a short 3-day nudge follow-up email.

Lead: {first_name} at {company} ({vertical})
Objections raised: {objection_list}

This should be shorter than the first follow-up (2-3 sentences). Light urgency around founding member spots. Include signup link. Do not repeat the same points from a typical first follow-up."""

    max_tokens = _post_demo_cfg.get("llm", {}).get("max_tokens", 500)
    email_text = _call_claude(system_prompt, user_message, max_tokens=max_tokens)

    if email_text:
        _log("follow_up_email", lead_id, "success",
             f"Generated follow-up #{follow_up_number}")
        _log_closer_event(lead_id, f"follow_up_{follow_up_number}_generated", {
            "email_text": email_text,
            "follow_up_number": follow_up_number,
        })
        return email_text
    else:
        _log("follow_up_email", lead_id, "failure",
             f"Claude returned no content for follow-up #{follow_up_number}")
        return None


# ---------------------------------------------------------------------------
# Win / Loss Tracking
# ---------------------------------------------------------------------------

def _track_win(lead):
    """Record a closed-won deal to CRM and log."""
    lead_id = lead.get("id", "unknown")
    now = datetime.now(timezone.utc)

    # Calculate days to close from first contact
    status_history = lead.get("status_history", [])
    first_contact_ts = None
    for entry in status_history:
        if entry.get("status") == "contacted":
            first_contact_ts = entry.get("timestamp")
            break

    days_to_close = 0
    if first_contact_ts:
        try:
            first_contact_dt = datetime.fromisoformat(first_contact_ts)
            days_to_close = (now - first_contact_dt).days
        except (ValueError, TypeError):
            days_to_close = 0

    objections_overcome = [
        o.get("type", "unknown")
        for o in lead.get("objections_raised", [])
    ]

    variant = lead.get("variant", "unknown")

    win_data = {
        "close_date": now.isoformat(),
        "mrr": MRR_PER_CLOSE,
        "days_to_close": days_to_close,
        "objections_overcome": objections_overcome,
        "opening_variant": variant,
        "vertical": lead.get("vertical", "unknown"),
        "company": lead.get("company", "unknown"),
    }

    # Update CRM status to closed
    crm_engine.update_status(lead_id, "closed", "sales-closer", "Deal won")

    _log("track_win", lead_id, "success",
         f"MRR: ${MRR_PER_CLOSE}, Days: {days_to_close}, "
         f"Objections: {objections_overcome}")
    _log_closer_event(lead_id, "win", win_data)

    return win_data


def _track_loss(lead, reason):
    """Record a closed-lost deal with reason."""
    lead_id = lead.get("id", "unknown")
    now = datetime.now(timezone.utc)

    # Determine stage lost at
    status_history = lead.get("status_history", [])
    stage_lost_at = lead.get("status", "unknown")

    loss_data = {
        "loss_date": now.isoformat(),
        "reason": reason,
        "stage_lost_at": stage_lost_at,
        "vertical": lead.get("vertical", "unknown"),
        "company": lead.get("company", "unknown"),
        "objections_raised": [
            o.get("type", "unknown")
            for o in lead.get("objections_raised", [])
        ],
    }

    # Update CRM status to lost
    crm_engine.update_status(lead_id, "lost", "sales-closer", f"Lost: {reason}")

    _log("track_loss", lead_id, "success",
         f"Reason: {reason}, Stage: {stage_lost_at}")
    _log_closer_event(lead_id, "loss", loss_data)

    return loss_data


# ---------------------------------------------------------------------------
# Stale Demo Detection
# ---------------------------------------------------------------------------

def _check_stale_demos():
    """Flag demos with no follow-up action for 3+ days."""
    stale_leads = []
    demo_completed_leads = crm_engine.get_leads_by_status("demo_completed")
    now = datetime.now(timezone.utc)

    for lead in demo_completed_leads:
        lead_id = lead.get("id", "unknown")
        updated_at = lead.get("updated_at", "")

        if not updated_at:
            continue

        try:
            updated_dt = datetime.fromisoformat(updated_at)
        except (ValueError, TypeError):
            continue

        days_since_update = (now - updated_dt).days
        if days_since_update >= NUDGE_DELAY_DAYS:
            stale_leads.append({
                "lead_id": lead_id,
                "company": lead.get("company", "unknown"),
                "contact_name": lead.get("contact_name", lead.get("name", "unknown")),
                "days_stale": days_since_update,
                "last_updated": updated_at,
            })

            # Mark as stalled in CRM
            stall_after = _config.get("post_demo", {}).get("stall_after_nudge", True)
            if stall_after and days_since_update >= NUDGE_DELAY_DAYS + 1:
                crm_engine.update_status(
                    lead_id, "stalled", "sales-closer",
                    f"No follow-up action for {days_since_update} days post-demo"
                )

            _log("stale_demo_check", lead_id, "flagged",
                 f"Stale for {days_since_update} days since last update")

    if stale_leads:
        _log("stale_demo_check", None, "summary",
             f"Found {len(stale_leads)} stale demo(s)")
        _log_closer_event(None, "stale_demos_detected", {
            "count": len(stale_leads),
            "leads": stale_leads,
        })
    else:
        _log("stale_demo_check", None, "success", "No stale demos found")

    return stale_leads


# ---------------------------------------------------------------------------
# Main Daily Cycle
# ---------------------------------------------------------------------------

def run_sales_closer_cycle():
    """
    Main entry point. Runs daily at 9AM PT.
    Processes booked leads (pre-demo briefs) and demo_completed leads (follow-ups).
    """
    _log("daily_cycle", None, "start", "Sales closer daily cycle starting")
    now = datetime.now(timezone.utc)

    results = {
        "briefs_generated": 0,
        "followups_sent": 0,
        "nudges_sent": 0,
        "stale_flagged": 0,
        "errors": 0,
    }

    # --- Phase 1: Pre-demo briefs for "booked" leads ---
    booked_leads = crm_engine.get_leads_by_status("booked")
    for lead in booked_leads:
        lead_id = lead.get("id", "unknown")
        demo_time_str = lead.get("demo_time", lead.get("booked_at", ""))

        if demo_time_str:
            try:
                demo_time = datetime.fromisoformat(demo_time_str)
                minutes_until = (demo_time - now).total_seconds() / 60

                # Generate brief if demo is within 30 minutes (but not past)
                if 0 <= minutes_until <= BRIEF_SEND_MINUTES_BEFORE:
                    brief = _generate_pre_demo_brief(lead)
                    if brief:
                        results["briefs_generated"] += 1
                    else:
                        results["errors"] += 1
                    continue
            except (ValueError, TypeError):
                pass

        # If no demo time set, generate brief anyway (event-driven trigger)
        # Only generate if lead was recently booked (within 24h)
        booked_at = lead.get("booked_at", lead.get("updated_at", ""))
        if booked_at:
            try:
                booked_dt = datetime.fromisoformat(booked_at)
                hours_since_booked = (now - booked_dt).total_seconds() / 3600
                if hours_since_booked <= 24:
                    brief = _generate_pre_demo_brief(lead)
                    if brief:
                        results["briefs_generated"] += 1
                    else:
                        results["errors"] += 1
            except (ValueError, TypeError):
                _log("daily_cycle", lead_id, "warning",
                     "Could not parse booked_at timestamp")

    # --- Phase 2: Follow-ups for "demo_completed" leads ---
    demo_leads = crm_engine.get_leads_by_status("demo_completed")
    for lead in demo_leads:
        lead_id = lead.get("id", "unknown")

        # Determine when demo was completed
        demo_completed_at = None
        for entry in reversed(lead.get("status_history", [])):
            if entry.get("status") == "demo_completed":
                demo_completed_at = entry.get("timestamp")
                break

        if not demo_completed_at:
            demo_completed_at = lead.get("updated_at", "")

        if not demo_completed_at:
            continue

        try:
            demo_dt = datetime.fromisoformat(demo_completed_at)
        except (ValueError, TypeError):
            _log("daily_cycle", lead_id, "warning",
                 "Could not parse demo_completed timestamp")
            continue

        hours_since_demo = (now - demo_dt).total_seconds() / 3600
        days_since_demo = hours_since_demo / 24

        # Check what follow-ups have already been sent
        followups_sent = lead.get("followups_sent", 0)

        # +24h personalized follow-up
        if hours_since_demo >= FOLLOWUP_DELAY_HOURS and followups_sent < 1:
            email = _generate_follow_up_email(lead, follow_up_number=1)
            if email:
                crm_engine.add_conversation_message(
                    lead_id, "outbound", email, channel="email"
                )
                # Track follow-up count on lead (update CRM directly)
                _update_lead_field(lead_id, "followups_sent", 1)
                results["followups_sent"] += 1
                _log("daily_cycle", lead_id, "success",
                     "24h follow-up email generated")
            else:
                results["errors"] += 1

        # +3 days shorter nudge
        elif days_since_demo >= NUDGE_DELAY_DAYS and followups_sent < 2:
            email = _generate_follow_up_email(lead, follow_up_number=2)
            if email:
                crm_engine.add_conversation_message(
                    lead_id, "outbound", email, channel="email"
                )
                _update_lead_field(lead_id, "followups_sent", 2)
                results["nudges_sent"] += 1
                _log("daily_cycle", lead_id, "success",
                     "3-day nudge email generated")
            else:
                results["errors"] += 1

    # --- Phase 3: Check for stale demos ---
    stale = _check_stale_demos()
    results["stale_flagged"] = len(stale)

    _log("daily_cycle", None, "complete",
         f"Briefs: {results['briefs_generated']}, "
         f"Follow-ups: {results['followups_sent']}, "
         f"Nudges: {results['nudges_sent']}, "
         f"Stale: {results['stale_flagged']}, "
         f"Errors: {results['errors']}")

    return results


def _update_lead_field(lead_id, field, value):
    """Update an arbitrary field on a lead in the CRM."""
    crm = crm_engine._load_crm()
    if lead_id in crm["leads"]:
        crm["leads"][lead_id][field] = value
        crm["leads"][lead_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        crm_engine._save_crm(crm)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sales Closer — post-booking pipeline")
    parser.add_argument("--run-daily", action="store_true",
                        help="Run the full daily sales closer cycle")
    parser.add_argument("--brief", action="store_true",
                        help="Generate a pre-demo brief for a specific lead")
    parser.add_argument("--follow-up", action="store_true",
                        help="Generate a follow-up email for a specific lead")
    parser.add_argument("--log-outcome", action="store_true",
                        help="Log a win or loss outcome for a lead")
    parser.add_argument("--lead-id", type=str, default=None,
                        help="Lead ID to operate on")
    parser.add_argument("--result", type=str, choices=["won", "lost"],
                        help="Outcome result (won/lost)")
    parser.add_argument("--mrr", type=int, default=MRR_PER_CLOSE,
                        help="MRR amount for won deals")
    parser.add_argument("--reason", type=str, default="",
                        help="Loss reason")
    parser.add_argument("--follow-up-number", type=int, default=1,
                        choices=[1, 2],
                        help="Follow-up number (1=24h, 2=3-day nudge)")
    args = parser.parse_args()

    if args.run_daily:
        results = run_sales_closer_cycle()
        print(json.dumps(results, indent=2))

    elif args.brief:
        if not args.lead_id:
            print("Error: --lead-id required for --brief")
            sys.exit(1)
        lead = crm_engine.get_lead(args.lead_id)
        if not lead:
            print(f"Error: Lead {args.lead_id} not found")
            sys.exit(1)
        brief = _generate_pre_demo_brief(lead)
        if brief:
            print(brief)
        else:
            print("Error: Failed to generate brief")
            sys.exit(1)

    elif args.follow_up:
        if not args.lead_id:
            print("Error: --lead-id required for --follow-up")
            sys.exit(1)
        lead = crm_engine.get_lead(args.lead_id)
        if not lead:
            print(f"Error: Lead {args.lead_id} not found")
            sys.exit(1)
        email = _generate_follow_up_email(lead, args.follow_up_number)
        if email:
            print(email)
        else:
            print("Error: Failed to generate follow-up email")
            sys.exit(1)

    elif args.log_outcome:
        if not args.lead_id:
            print("Error: --lead-id required for --log-outcome")
            sys.exit(1)
        if not args.result:
            print("Error: --result (won/lost) required for --log-outcome")
            sys.exit(1)
        lead = crm_engine.get_lead(args.lead_id)
        if not lead:
            print(f"Error: Lead {args.lead_id} not found")
            sys.exit(1)

        if args.result == "won":
            data = _track_win(lead)
            print(json.dumps(data, indent=2))
        else:
            reason = args.reason or "no reason provided"
            data = _track_loss(lead, reason)
            print(json.dumps(data, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
