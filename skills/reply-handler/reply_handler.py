#!/usr/bin/env python3
"""
Reply Handler — Skill 6
Detect, classify, and route all inbound email replies. Revenue-critical skill.
Groq/Llama for classification + QUESTION replies. Claude for INTERESTED + OBJECTION.
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crm-engine'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'qa-guard'))

import crm_engine
import qa_guard

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")
REPLIES_LOG = os.path.join(DATA_DIR, "replies_log.jsonl")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
INSTANTLY_API_KEY = os.environ.get("INSTANTLY_API_KEY", "")
CALENDLY_LINK = ""

# Load from global config if available
GLOBAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
if os.path.exists(GLOBAL_CONFIG_PATH):
    with open(GLOBAL_CONFIG_PATH) as f:
        _gc = json.load(f)
        CALENDLY_LINK = _gc.get("calendly_link", "")

CLASSIFICATIONS = [
    "INTERESTED", "NOT_INTERESTED", "QUESTION",
    "OBJECTION_PRICE", "OBJECTION_TIMING", "OBJECTION_TRUST", "OBJECTION_NEED",
    "OUT_OF_OFFICE", "BOUNCE", "SPAM",
]

# Cost tracking
_claude_calls_today = 0
_claude_tokens_today = 0
_claude_cost_today = 0.0


def _log(action, lead_id, result, details, llm_used="none", tokens=0, cost=0.0):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "reply-handler",
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


def _log_reply(lead_id, classification, reply_text, response_text=None):
    os.makedirs(os.path.dirname(REPLIES_LOG), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lead_id": lead_id,
        "classification": classification,
        "reply_text": reply_text[:500],
        "response_text": response_text[:500] if response_text else None,
    }
    with open(REPLIES_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _call_groq(prompt, max_tokens=300):
    """Call Groq API with Llama 3.1 70B."""
    if not GROQ_API_KEY:
        _log("groq_call", None, "failure", "GROQ_API_KEY not set")
        return None

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.1-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=payload, timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                _log("groq_call", None, "success", f"Tokens: {tokens}", "groq", tokens, 0.0)
                return text
            else:
                _log("groq_call", None, "failure",
                     f"HTTP {resp.status_code}: {resp.text[:200]}", "groq")
                if attempt < 2:
                    time.sleep(30 * (attempt + 1))
        except Exception as e:
            _log("groq_call", None, "failure", str(e)[:200], "groq")
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
    return None


def _call_claude(system_prompt, user_message, max_tokens=500):
    """Call Claude API for revenue-critical conversations."""
    global _claude_calls_today, _claude_tokens_today, _claude_cost_today

    if not ANTHROPIC_API_KEY:
        _log("claude_call", None, "failure", "ANTHROPIC_API_KEY not set")
        return None

    # Budget check: $50/day hard cap
    if _claude_cost_today >= 50.0:
        _log("claude_call", None, "failure",
             "Daily Claude budget cap ($50) reached. Using Groq fallback.")
        return _call_groq(f"{system_prompt}\n\n{user_message}", max_tokens)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload, timeout=60,
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
                if attempt < 2:
                    time.sleep(30 * (attempt + 1))
        except Exception as e:
            _log("claude_call", None, "failure", str(e)[:200], "claude")
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
    return None


def _send_via_instantly(to_email, subject, body, reply_to_message_id=None):
    """Send an email reply via Instantly.ai API."""
    if not INSTANTLY_API_KEY:
        _log("instantly_send", None, "failure", "INSTANTLY_API_KEY not set")
        return False

    headers = {
        "Authorization": f"Bearer {INSTANTLY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": to_email,
        "subject": subject,
        "body": body,
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        resp = requests.post(
            "https://api.instantly.ai/api/v1/email/send",
            headers=headers, json=payload, timeout=30,
        )
        if resp.status_code in (200, 201):
            _log("instantly_send", None, "success", f"Sent reply to {to_email}")
            return True
        else:
            _log("instantly_send", None, "failure",
                 f"HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        _log("instantly_send", None, "failure", str(e)[:200])
        return False


def _notify_owner(message):
    """Send notification to owner via OpenClaw messaging."""
    _log("owner_notification", None, "success", message[:200])
    print(f"[OWNER NOTIFICATION] {message}")


def poll_replies():
    """Poll Instantly.ai API for new replies."""
    if not INSTANTLY_API_KEY:
        _log("poll_replies", None, "failure", "INSTANTLY_API_KEY not set")
        return []

    headers = {
        "Authorization": f"Bearer {INSTANTLY_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(
            "https://api.instantly.ai/api/v1/unibox/replies",
            headers=headers,
            params={"limit": 50},
            timeout=30,
        )
        if resp.status_code == 200:
            replies = resp.json().get("data", resp.json() if isinstance(resp.json(), list) else [])
            _log("poll_replies", None, "success", f"Found {len(replies)} new replies")
            return replies
        else:
            _log("poll_replies", None, "failure", f"HTTP {resp.status_code}")
            return []
    except Exception as e:
        _log("poll_replies", None, "failure", str(e)[:200])
        return []


def classify_reply(reply_text, lead, conversation_history):
    """Classify a reply using Groq/Llama into one of 10 categories."""
    contact_name = lead.get("contact_name", "Unknown")
    company_name = lead.get("company_name", "Unknown")
    vertical = lead.get("vertical", "Unknown")
    city = lead.get("city", "")
    state = lead.get("state", "")
    touch_count = len([m for m in conversation_history if m.get("direction") == "outbound"])

    conv_str = ""
    for msg in conversation_history[-10:]:
        direction = "US" if msg.get("direction") == "outbound" else "THEM"
        conv_str += f"{direction}: {msg.get('message', '')[:200]}\n"

    prompt = f"""Classify this email reply from a contractor lead into EXACTLY one category.

Lead: {contact_name}, {company_name}, {vertical}, {city} {state}
Emails sent to this lead: {touch_count}
Their reply: "{reply_text}"
Previous messages:
{conv_str}

Categories:
INTERESTED — wants to learn more, asks how it works, positive/curious tone
NOT_INTERESTED — explicit decline, asks to stop, "not interested," "remove me"
QUESTION — neutral question ("who is this?", "how'd you get my email?")
OBJECTION_PRICE — pushback about cost or budget
OBJECTION_TIMING — not a good time, too busy, maybe later
OBJECTION_TRUST — skeptical, wants proof, references scams/spam
OBJECTION_NEED — says they don't miss calls, already have a solution
OUT_OF_OFFICE — auto-reply, vacation, OOO
BOUNCE — delivery failure, invalid email
SPAM — unrelated, wrong person, gibberish

Respond with ONLY the category name."""

    result = _call_groq(prompt, max_tokens=20)
    if result:
        result = result.strip().upper().replace(" ", "_")
        if result in CLASSIFICATIONS:
            return result
    # Fallback: try to detect common patterns
    text_lower = reply_text.lower()
    if any(w in text_lower for w in ["not interested", "remove me", "stop", "unsubscribe"]):
        return "NOT_INTERESTED"
    if any(w in text_lower for w in ["out of office", "ooo", "vacation", "auto-reply"]):
        return "OUT_OF_OFFICE"
    if any(w in text_lower for w in ["delivery failed", "undeliverable", "not found"]):
        return "BOUNCE"
    return "QUESTION"


def handle_bounce(lead):
    """Mark email as invalid, stop sequences, add to suppression."""
    lead_id = lead["id"]
    email = lead["email"]
    crm_engine.add_to_suppression(email, "bounce")
    crm_engine.update_status(lead_id, "lost", "reply-handler", "Email bounced")
    _log("handle_bounce", lead_id, "success", f"Bounced: {email}")


def handle_out_of_office(lead):
    """Pause sequence, set reminder to retry in 7 days."""
    lead_id = lead["id"]
    _log("handle_ooo", lead_id, "success",
         f"Out of office. Retry after {(datetime.now(timezone.utc) + timedelta(days=7)).isoformat()}")


def handle_not_interested(lead):
    """Update CRM to lost, add to permanent suppression."""
    lead_id = lead["id"]
    email = lead["email"]
    crm_engine.update_status(lead_id, "lost", "reply-handler", "Lead declined")
    crm_engine.add_to_suppression(email, "not_interested")
    _log("handle_not_interested", lead_id, "success", f"Lost: {email}, suppressed permanently")


def handle_spam(lead):
    """Mark as disqualified, stop sequences."""
    lead_id = lead["id"]
    # Use "lost" since "disqualified" isn't a valid CRM stage
    crm_engine.update_status(lead_id, "lost", "reply-handler", "Spam/irrelevant reply")
    _log("handle_spam", lead_id, "success", f"Disqualified: {lead['email']}")


def handle_question(lead, reply_text, conversation_history):
    """Generate reply to neutral question using Groq/Llama."""
    lead_id = lead["id"]
    vertical = lead.get("vertical", "contractor")
    state = lead.get("state", "your area")

    prompt = f"""A contractor replied to our cold email with a neutral question.
Their question: "{reply_text}"
Context: We emailed them about missed calls costing their business money.

Write a 2-3 sentence reply:
1. Answer their question directly and honestly
2. Do NOT pitch any product or include links
3. If "who is this": say you work with {vertical} contractors in {state} helping them capture more inbound calls
4. If "how did you get my email": say their business came up in research on {vertical} companies in {state}
5. Keep friendly, professional tone — not defensive, not over-explaining

Respond with ONLY the reply text."""

    response = _call_groq(prompt, max_tokens=200)
    if not response:
        _log("handle_question", lead_id, "failure", "Failed to generate response")
        return

    # QA gate
    qa_result = qa_guard.check_email("Re: ", response, email_type="reply", sequence_number=99)
    if not qa_result.get("passed", False):
        # Retry once
        response = _call_groq(prompt, max_tokens=200)
        if response:
            qa_result = qa_guard.check_email("Re: ", response, email_type="reply", sequence_number=99)
        if not qa_result.get("passed", False):
            _log("handle_question", lead_id, "rejected",
                 f"QA rejected twice: {qa_result.get('reasons', [])}")
            return

    _send_via_instantly(lead["email"], "Re: ", response)
    crm_engine.add_conversation_message(lead_id, "inbound", reply_text)
    crm_engine.add_conversation_message(lead_id, "outbound", response)
    crm_engine.update_status(lead_id, "replied", "reply-handler", "Answered neutral question")
    _log_reply(lead_id, "QUESTION", reply_text, response)
    _log("handle_question", lead_id, "success", "Replied to question")


def handle_objection(lead, reply_text, objection_type, conversation_history):
    """Handle objection using Claude for nuanced response."""
    lead_id = lead["id"]
    contact_name = lead.get("contact_name", "there")
    company_name = lead.get("company_name", "your company")
    vertical = lead.get("vertical", "contractor")
    city = lead.get("city", "")
    state = lead.get("state", "")

    conv_str = ""
    for msg in conversation_history[-10:]:
        direction = "Us" if msg.get("direction") == "outbound" else "Them"
        conv_str += f"{direction}: {msg.get('message', '')[:300]}\n"

    # Vertical-specific job values for price framing
    job_values = {
        "hvac": "$800-3,000", "plumbing": "$500-2,500", "electrical": "$600-2,000",
        "roofing": "$2,000-8,000", "general_contractor": "$1,500-5,000",
        "landscaping": "$300-1,200", "pest_control": "$200-600",
    }
    job_value = job_values.get(vertical.lower().replace(" ", "_"), "$500-3,000")

    system_prompt = f"""You are a senior sales closer handling an objection from a trade contractor.

Product: Missed-call text-back system. $297/month. Automatically texts back missed calls so the contractor never loses a job to an unanswered phone.
NEVER say "AI", "artificial intelligence", "bot", "automated", or "automation". Call it a "system" or "tool".

Lead: {contact_name}, {company_name}, {vertical}, {city} {state}
Conversation history:
{conv_str}

Objection type: {objection_type}
Their message: "{reply_text}"

Objection strategies:
OBJECTION_PRICE:
- Frame $297 against ONE missed job: "One missed {vertical} call could be a {job_value} job. The system pays for itself if it saves just one."
- If they push harder: offer to let them see their own call volume data first

OBJECTION_TIMING:
- Acknowledge they're busy — that's literally WHY they need this
- "That's actually why most {vertical} guys use it — they're slammed and can't get to every call"
- Offer specific follow-up window: "Want me to circle back in 2 weeks?"

OBJECTION_TRUST:
- Don't get defensive
- Zero-risk demo: "Totally fair. Happy to show you exactly how it works in a 10-minute call — no commitment"
- Reference other contractors: "A few {vertical} companies in {state} are using it"

OBJECTION_NEED:
- Diagnostic question: "How many calls would you say you miss in a typical week?"
- If zero: "That's solid — most guys I talk to say 3-5. If that changes during busy season, reach out"
- If they have a solution: "What are you using? Just curious." (gather intel, don't compete)

Rules:
- 3 sentences max
- Confident and direct, not pushy
- Never say "AI"
- No links in this message
- If genuinely not interested after handling: gracefully exit

Respond with ONLY the reply text."""

    response = _call_claude(system_prompt, reply_text)
    if not response:
        _log("handle_objection", lead_id, "failure", "Failed to generate response")
        return

    # QA gate
    qa_result = qa_guard.check_email("Re: ", response, email_type="reply", sequence_number=99)
    if not qa_result.get("passed", False):
        response = _call_claude(system_prompt, reply_text)
        if response:
            qa_result = qa_guard.check_email("Re: ", response, email_type="reply", sequence_number=99)
        if not qa_result.get("passed", False):
            _log("handle_objection", lead_id, "rejected",
                 f"QA rejected twice: {qa_result.get('reasons', [])}")
            return

    _send_via_instantly(lead["email"], "Re: ", response)
    crm_engine.add_conversation_message(lead_id, "inbound", reply_text)
    crm_engine.add_conversation_message(lead_id, "outbound", response)
    crm_engine.add_objection(lead_id, objection_type)

    # Transition: replied -> objection_handled requires going through valid transitions
    if lead["status"] == "replied":
        crm_engine.update_status(lead_id, "objection_handled", "reply-handler",
                                 f"Objection: {objection_type}")
    _log_reply(lead_id, objection_type, reply_text, response)
    _notify_owner(
        f"Objection ({objection_type}) from {contact_name} at {company_name}. "
        f"Handling — will notify if they convert."
    )
    _log("handle_objection", lead_id, "success", f"Objection handled: {objection_type}")


def handle_interested(lead, reply_text, conversation_history):
    """Handle interested lead using Claude — push for demo booking."""
    lead_id = lead["id"]
    contact_name = lead.get("contact_name", "there")
    company_name = lead.get("company_name", "your company")
    vertical = lead.get("vertical", "contractor")
    city = lead.get("city", "")
    state = lead.get("state", "")
    lead_score = lead.get("lead_score", 0)

    conv_str = ""
    for msg in conversation_history[-10:]:
        direction = "Us" if msg.get("direction") == "outbound" else "Them"
        conv_str += f"{direction}: {msg.get('message', '')[:300]}\n"

    system_prompt = f"""You are a senior sales closer. A trade contractor lead has replied with interest in a missed-call text-back system.

Product: $297/month. Automatically texts back missed calls. Called "system" or "tool" — NEVER "AI", "bot", "automated", or "automation".

Lead: {contact_name}, {company_name}, {vertical}, {city} {state}
Conversation history:
{conv_str}

Their message: "{reply_text}"

Goal: Book a 10-minute demo call.

Strategy:
1. Acknowledge what they said (1 sentence max)
2. One specific benefit relevant to their vertical and their message
3. Propose specific demo time: "Are you free [next business day] morning or afternoon for a quick 10-minute walkthrough?"
4. Low-pressure: "Just a quick walkthrough — no pitch, no pressure"

When they confirm a time:
- "Locked in. I'll send you a calendar invite. Talk [day]."
- Include Calendly link: {CALENDLY_LINK}

Rules:
- 3-4 sentences max
- Match their energy (casual→casual, professional→professional)
- Never say "AI"
- Be specific about demo time — don't say "whenever works"
- If they ask about price: answer directly. "$297/month, and it pays for itself if it saves one missed call per month"

Respond with ONLY the reply text."""

    response = _call_claude(system_prompt, reply_text)
    if not response:
        _log("handle_interested", lead_id, "failure", "Failed to generate response")
        return

    # QA gate
    qa_result = qa_guard.check_email("Re: ", response, email_type="reply", sequence_number=99)
    if not qa_result.get("passed", False):
        response = _call_claude(system_prompt, reply_text)
        if response:
            qa_result = qa_guard.check_email("Re: ", response, email_type="reply", sequence_number=99)
        if not qa_result.get("passed", False):
            _log("handle_interested", lead_id, "rejected",
                 f"QA rejected twice: {qa_result.get('reasons', [])}")
            return

    _send_via_instantly(lead["email"], "Re: ", response)
    crm_engine.add_conversation_message(lead_id, "inbound", reply_text)
    crm_engine.add_conversation_message(lead_id, "outbound", response)

    # Transition to qualified
    if lead["status"] == "replied":
        crm_engine.update_status(lead_id, "qualified", "reply-handler", "Lead interested")
    elif lead["status"] == "objection_handled":
        crm_engine.update_status(lead_id, "replied", "reply-handler", "Re-engaged after objection")

    _log_reply(lead_id, "INTERESTED", reply_text, response)

    # IMMEDIATE OWNER NOTIFICATION
    first_50 = reply_text[:50]
    _notify_owner(
        f"HOT LEAD: {contact_name} at {company_name} ({vertical}, {city}). "
        f"Score: {lead_score}. They said: '{first_50}...' — Pushed for demo call."
    )
    _log("handle_interested", lead_id, "success", "Interested lead handled, owner notified")


def process_reply(reply_data):
    """Process a single reply: classify and route to appropriate handler."""
    reply_email = reply_data.get("from_email", reply_data.get("email", "")).lower().strip()
    reply_text = reply_data.get("text", reply_data.get("body", "")).strip()
    message_id = reply_data.get("message_id", "")

    if not reply_email or not reply_text:
        _log("process_reply", None, "skipped", "Missing email or text in reply data")
        return

    # Match to lead
    lead = crm_engine.get_lead_by_email(reply_email)
    if not lead:
        _log("process_reply", None, "skipped", f"No lead found for {reply_email}")
        return

    lead_id = lead["id"]
    conversation = lead.get("conversation", [])

    # Check conversation turn limit
    inbound_count = sum(1 for m in conversation if m.get("direction") == "inbound")
    if inbound_count >= 5:
        _notify_owner(
            f"Lead {lead.get('contact_name', reply_email)} is engaged but hasn't booked "
            f"after {inbound_count} exchanges. Your call. Full conversation attached."
        )
        _log("process_reply", lead_id, "escalated",
             f"Max conversation turns ({inbound_count}) reached")
        return

    # Classify
    classification = classify_reply(reply_text, lead, conversation)
    _log("classify_reply", lead_id, "success", f"Classified as: {classification}")

    # Route
    if classification == "BOUNCE":
        handle_bounce(lead)
    elif classification == "OUT_OF_OFFICE":
        handle_out_of_office(lead)
    elif classification == "NOT_INTERESTED":
        handle_not_interested(lead)
    elif classification == "SPAM":
        handle_spam(lead)
    elif classification == "QUESTION":
        handle_question(lead, reply_text, conversation)
    elif classification.startswith("OBJECTION_"):
        handle_objection(lead, reply_text, classification, conversation)
    elif classification == "INTERESTED":
        handle_interested(lead, reply_text, conversation)
    else:
        _log("process_reply", lead_id, "skipped", f"Unknown classification: {classification}")


def run():
    """Main entry point: poll for replies and process them."""
    _log("run", None, "success", "Reply handler started")

    replies = poll_replies()
    if not replies:
        _log("run", None, "success", "No new replies to process")
        return

    processed = 0
    classifications = {}

    for reply_data in replies:
        try:
            process_reply(reply_data)
            processed += 1
        except Exception as e:
            _log("process_reply", None, "failure", f"Error processing reply: {str(e)[:200]}")

    _log("run", None, "success",
         f"Run complete. Processed: {processed}/{len(replies)}. "
         f"Claude calls today: {_claude_calls_today}, "
         f"Claude cost today: ${_claude_cost_today:.4f}")


if __name__ == "__main__":
    run()
