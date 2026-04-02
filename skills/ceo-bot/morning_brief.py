#!/usr/bin/env python3
"""
Morning Brief — 6:30AM PT
Short, actionable summary in <10 lines.
Yesterday's stats, overnight actions, today's focus, demos scheduled, decisions needed, system status.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SKILL_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CEO_MEMORY_DIR = os.path.join(DATA_DIR, "ceo_memory")
BRIEFS_DIR = os.path.join(CEO_MEMORY_DIR, "morning_briefs")
DELEGATIONS_LOG = os.path.join(CEO_MEMORY_DIR, "delegations_log.jsonl")
IMPROVEMENTS_LOG = os.path.join(CEO_MEMORY_DIR, "improvements_log.jsonl")
SYSTEM_LOG = os.path.join(DATA_DIR, "system_log.jsonl")

import ceo_bot


def _read_json(path: str, default=None):
    """Safely read a JSON file."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default if default is not None else {}


def _read_jsonl_since(path: str, since: datetime) -> list[dict]:
    """Read JSONL entries since a given datetime."""
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
                if ts >= since:
                    entries.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue
    return entries


def _get_yesterday_stats() -> dict:
    """Get yesterday's key metrics from the last daily note or system log."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    daily_note_path = os.path.join(CEO_MEMORY_DIR, "daily_notes", f"{yesterday}.md")

    stats = {
        "date": yesterday,
        "emails_sent": 0,
        "replies": 0,
        "reply_rate_pct": 0.0,
        "demos_completed": 0,
        "deals_closed": 0,
        "errors": 0,
    }

    if os.path.exists(daily_note_path):
        with open(daily_note_path, "r") as f:
            content = f.read()
        for line in content.split("\n"):
            line_lower = line.lower().strip()
            if "emails sent" in line_lower:
                try:
                    stats["emails_sent"] = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                except ValueError:
                    pass
            elif "replies" in line_lower and "rate" not in line_lower:
                try:
                    stats["replies"] = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                except ValueError:
                    pass
            elif "reply rate" in line_lower:
                try:
                    val = line.split(":")[-1].strip().replace("%", "")
                    stats["reply_rate_pct"] = float(val)
                except ValueError:
                    pass
            elif "demos completed" in line_lower or "demos_completed" in line_lower:
                try:
                    stats["demos_completed"] = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                except ValueError:
                    pass
            elif "deals closed" in line_lower or "deals_closed" in line_lower:
                try:
                    stats["deals_closed"] = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                except ValueError:
                    pass
            elif "errors" in line_lower:
                try:
                    stats["errors"] = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                except ValueError:
                    pass
    else:
        # Fall back to counting system log entries
        yesterday_start = datetime.fromisoformat(f"{yesterday}T00:00:00+00:00")
        yesterday_end = yesterday_start + timedelta(days=1)
        if os.path.exists(SYSTEM_LOG):
            with open(SYSTEM_LOG, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
                        if ts < yesterday_start or ts >= yesterday_end:
                            continue
                        skill = entry.get("skill", "")
                        action = entry.get("action", "")
                        result = entry.get("result", "")
                        if skill == "outreach-sequencer" and action == "send_email" and result == "success":
                            stats["emails_sent"] += 1
                        elif skill == "reply-handler" and action in ("reply_processed", "handle_reply") and result == "success":
                            stats["replies"] += 1
                        elif result in ("failure", "error"):
                            stats["errors"] += 1
                    except (json.JSONDecodeError, ValueError):
                        continue
            if stats["emails_sent"] > 0:
                stats["reply_rate_pct"] = round(stats["replies"] / stats["emails_sent"] * 100, 2)

    return stats


def _get_overnight_actions() -> list[str]:
    """Get actions taken between 10PM yesterday and now."""
    now = datetime.now(timezone.utc)
    overnight_start = now - timedelta(hours=9)  # ~10PM PT the night before
    actions = []

    overnight_delegations = _read_jsonl_since(DELEGATIONS_LOG, overnight_start)
    for d in overnight_delegations:
        actions.append(f"Delegated to {d.get('skill', '?')}: {d.get('task', '?')[:60]}")

    overnight_improvements = _read_jsonl_since(IMPROVEMENTS_LOG, overnight_start)
    for imp in overnight_improvements:
        actions.append(f"1% improvement: {imp.get('description', '?')[:60]}")

    return actions[:5]  # Cap at 5 to keep brief short


def _get_demos_scheduled() -> list[dict]:
    """Get demos scheduled for today."""
    crm_data = _read_json(os.path.join(DATA_DIR, "crm.json"), [])
    demos = []
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(crm_data, list):
        for lead in crm_data:
            if lead.get("status") == "booked":
                demo_date = lead.get("demo_date", "")
                if demo_date.startswith(today_str) or not demo_date:
                    demos.append({
                        "company": lead.get("company", "Unknown"),
                        "contact": lead.get("contact_name", lead.get("email", "Unknown")),
                        "time": lead.get("demo_time", "TBD"),
                    })
    return demos


def _get_decisions_needed() -> list[str]:
    """Identify decisions that need owner input."""
    decisions = []

    config = ceo_bot.load_config()
    if config.get("improvement_system", {}).get("paused", False):
        decisions.append("1% improvement system paused (3 consecutive negatives) — resume or adjust?")

    within_budget, spent, cap = ceo_bot.check_claude_budget()
    if spent > cap * 0.8:
        decisions.append(f"Claude budget at {spent/cap*100:.0f}% (${spent:.2f}/${cap:.2f})")

    return decisions


def _get_system_status() -> str:
    """Quick system health check."""
    now = datetime.now(timezone.utc)
    last_hour = now - timedelta(hours=1)
    recent_errors = 0

    if os.path.exists(SYSTEM_LOG):
        with open(SYSTEM_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
                    if ts >= last_hour and entry.get("result") in ("failure", "error"):
                        recent_errors += 1
                except (json.JSONDecodeError, ValueError):
                    continue

    if recent_errors == 0:
        return "All systems green"
    elif recent_errors < 5:
        return f"Minor issues ({recent_errors} errors last hour)"
    else:
        return f"ATTENTION: {recent_errors} errors in last hour"


def generate_morning_brief() -> str:
    """Generate the morning brief using Groq for formatting."""
    yesterday = _get_yesterday_stats()
    overnight = _get_overnight_actions()
    demos = _get_demos_scheduled()
    decisions = _get_decisions_needed()
    system_status = _get_system_status()

    # Get the last nightly review's priority
    daily_note_path = os.path.join(
        CEO_MEMORY_DIR, "daily_notes",
        (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d") + ".md"
    )
    todays_focus = "Check nightly review for priorities"
    if os.path.exists(daily_note_path):
        with open(daily_note_path, "r") as f:
            for line in f:
                if "priority" in line.lower() and "tomorrow" in line.lower():
                    todays_focus = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
                    break

    # Build the brief directly — compact, no LLM needed for formatting
    lines = []
    lines.append(f"MORNING BRIEF — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"Yesterday: {yesterday['emails_sent']} sent, {yesterday['replies']} replies ({yesterday['reply_rate_pct']}%), {yesterday['demos_completed']} demos, {yesterday['deals_closed']} closed, {yesterday['errors']} errors")

    if overnight:
        lines.append(f"Overnight: {'; '.join(overnight[:3])}")
    else:
        lines.append("Overnight: No actions taken")

    lines.append(f"Focus: {todays_focus}")

    if demos:
        demo_strs = [f"{d['company']} ({d['time']})" for d in demos[:3]]
        lines.append(f"Demos today: {', '.join(demo_strs)}")
    else:
        lines.append("Demos today: None scheduled")

    if decisions:
        lines.append(f"Decisions needed: {'; '.join(decisions)}")

    lines.append(f"System: {system_status}")

    brief = "\n".join(lines)

    # Ensure it stays under 10 lines
    brief_lines = brief.split("\n")
    if len(brief_lines) > 10:
        brief = "\n".join(brief_lines[:10])

    return brief


def execute_morning_brief() -> str:
    """Execute the morning brief cycle: generate, save, log."""
    ceo_bot.ensure_directories()
    ceo_bot.log("morning_brief", "started", "Generating morning brief")

    brief = generate_morning_brief()

    # Save to file
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    brief_path = os.path.join(BRIEFS_DIR, f"{today_str}.md")
    os.makedirs(BRIEFS_DIR, exist_ok=True)
    with open(brief_path, "w") as f:
        f.write(brief + "\n")

    ceo_bot.log("morning_brief", "complete", f"Saved to {brief_path}, lines={len(brief.splitlines())}")
    return brief


if __name__ == "__main__":
    brief = execute_morning_brief()
    print(brief)
