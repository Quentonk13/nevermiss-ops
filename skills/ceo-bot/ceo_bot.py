#!/usr/bin/env python3
"""
CEO-Bot — Master Orchestrator
Strategic command layer with authority over all skills.
Coordinates nightly reviews, morning briefs, weekly strategy, delegations, and memory.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CEO_MEMORY_DIR = os.path.join(DATA_DIR, "ceo_memory")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")

RESTRICTED_ACTIONS = frozenset([
    "override_security",
    "exceed_budget",
    "change_pricing",
    "financial_commitment",
    "post_publicly",
    "delete_data",
    "external_communication",
])


def load_config() -> dict:
    """Load CEO-bot configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """Persist CEO-bot configuration."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def log(action: str, result: str, details: str, lead_id: Optional[str] = None,
        llm_used: str = "none", tokens_estimated: int = 0, cost_estimated: float = 0.0) -> None:
    """Append structured log entry to system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "ceo-bot",
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": llm_used,
        "tokens_estimated": tokens_estimated,
        "cost_estimated": cost_estimated,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def ensure_directories() -> None:
    """Create all required data directories."""
    dirs = [
        os.path.join(CEO_MEMORY_DIR, "knowledge"),
        os.path.join(CEO_MEMORY_DIR, "daily_notes"),
        os.path.join(CEO_MEMORY_DIR, "tacit"),
        os.path.join(CEO_MEMORY_DIR, "strategic_reviews"),
        os.path.join(CEO_MEMORY_DIR, "morning_briefs"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def check_authority(action: str) -> bool:
    """Verify the requested action is within CEO-bot authority."""
    if action in RESTRICTED_ACTIONS:
        log("authority_check", "blocked", f"Attempted restricted action: {action}")
        return False
    config = load_config()
    authority = config.get("authority", {})
    if action == "trigger_skill" and not authority.get("can_trigger_skills", False):
        return False
    if action == "modify_config" and not authority.get("can_modify_configs", False):
        return False
    if action == "reallocate_resources" and not authority.get("can_reallocate_resources", False):
        return False
    return True


def get_weekly_claude_spend() -> float:
    """Calculate Claude spend for the current week from system_log.jsonl."""
    if not os.path.exists(LOG_PATH):
        return 0.0
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    with open(LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("skill") == "ceo-bot" and entry.get("llm_used") == "anthropic":
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts >= week_start:
                        total += entry.get("cost_estimated", 0.0)
            except (json.JSONDecodeError, KeyError):
                continue
    return total


def check_claude_budget() -> tuple[bool, float, float]:
    """Check if Claude budget is available. Returns (within_budget, spent, cap)."""
    config = load_config()
    cap = config["llm"]["strategic"]["weekly_budget_cap_usd"]
    spent = get_weekly_claude_spend()
    return spent < cap, spent, cap


def call_claude(prompt: str, system_prompt: str = "", max_tokens: int = 4096) -> tuple[str, float]:
    """Call Claude API for strategic reasoning. Returns (response_text, cost_estimate).

    Cost estimated at $3/1M input + $15/1M output tokens for Sonnet.
    """
    import anthropic

    within_budget, spent, cap = check_claude_budget()
    if not within_budget:
        log("claude_call", "blocked", f"Weekly budget exhausted: ${spent:.2f}/${cap:.2f}")
        raise RuntimeError(f"Claude weekly budget exhausted: ${spent:.2f}/${cap:.2f}")

    config = load_config()
    llm_config = config["llm"]["strategic"]
    api_key = os.environ.get(llm_config["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing environment variable: {llm_config['api_key_env']}")

    client = anthropic.Anthropic(api_key=api_key)

    messages = [{"role": "user", "content": prompt}]
    kwargs = {
        "model": llm_config["model"],
        "max_tokens": max_tokens,
        "temperature": llm_config["temperature"],
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    response = client.messages.create(**kwargs)
    text = response.content[0].text
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

    log("claude_call", "success",
        f"tokens_in={input_tokens} tokens_out={output_tokens} cost=${cost:.4f}",
        llm_used="anthropic", tokens_estimated=input_tokens + output_tokens,
        cost_estimated=cost)

    return text, cost


def call_groq(prompt: str, system_prompt: str = "", max_tokens: int = 4096) -> str:
    """Call Groq/Llama for data aggregation and formatting."""
    import httpx

    config = load_config()
    llm_config = config["llm"]["aggregation"]
    api_key = os.environ.get(llm_config["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing environment variable: {llm_config['api_key_env']}")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": llm_config["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": llm_config["temperature"],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=llm_config["timeout_seconds"],
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]

    log("groq_call", "success",
        f"model={llm_config['model']} tokens={data.get('usage', {}).get('total_tokens', 0)}",
        llm_used="groq",
        tokens_estimated=data.get("usage", {}).get("total_tokens", 0),
        cost_estimated=0.0)

    return text


def run_nightly_review() -> dict:
    """Execute the full nightly review cycle."""
    sys.path.insert(0, SKILL_DIR)
    from nightly_review import execute_nightly_review
    return execute_nightly_review()


def run_morning_brief() -> str:
    """Generate and store the morning brief."""
    sys.path.insert(0, SKILL_DIR)
    from morning_brief import execute_morning_brief
    return execute_morning_brief()


def run_weekly_strategic() -> dict:
    """Execute the weekly strategic review."""
    sys.path.insert(0, SKILL_DIR)
    from strategic_review import execute_strategic_review
    return execute_strategic_review()


def handle_critical_event(event_type: str, event_data: dict) -> dict:
    """Handle a real-time critical event."""
    log("critical_event", "received", f"type={event_type} data={json.dumps(event_data)}")

    ensure_directories()

    system_prompt = (
        "You are the CEO-bot for NeverMiss AI, a startup selling AI receptionist "
        "services to home service businesses. A critical event has occurred. "
        "Analyze it and provide: 1) Severity (critical/high/medium), "
        "2) Immediate actions needed, 3) Skills to delegate to, 4) Owner notification needed (yes/no)."
    )
    prompt = f"Critical event: {event_type}\nData: {json.dumps(event_data, indent=2)}"

    try:
        analysis, cost = call_claude(prompt, system_prompt, max_tokens=1024)
    except RuntimeError:
        analysis = (
            f"BUDGET EXHAUSTED - Critical event {event_type} needs manual review. "
            f"Data: {json.dumps(event_data)}"
        )
        cost = 0.0

    result = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis": analysis,
        "cost": cost,
    }

    log("critical_event", "handled", f"type={event_type} analysis_length={len(analysis)}")
    return result


def main(trigger: str = "nightly", event_type: str = "", event_data: Optional[dict] = None) -> None:
    """Main entry point for CEO-bot."""
    ensure_directories()
    log("run_start", "info", f"trigger={trigger}")

    try:
        if trigger == "nightly":
            result = run_nightly_review()
            log("nightly_review", "complete", json.dumps(result.get("summary", {})))

        elif trigger == "morning":
            brief = run_morning_brief()
            log("morning_brief", "complete", f"length={len(brief)}")

        elif trigger == "weekly":
            result = run_weekly_strategic()
            log("weekly_strategic", "complete", json.dumps(result.get("summary", {})))

        elif trigger == "critical":
            if not event_data:
                event_data = {}
            result = handle_critical_event(event_type, event_data)
            log("critical_event", "complete", json.dumps(result))

        else:
            log("run_start", "error", f"Unknown trigger: {trigger}")
            return

    except Exception as e:
        log("run_error", "failure", f"trigger={trigger} error={str(e)} trace={traceback.format_exc()}")
        raise

    log("run_end", "info", f"trigger={trigger}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CEO-Bot Master Orchestrator")
    parser.add_argument("--trigger", choices=["nightly", "morning", "weekly", "critical"],
                        default="nightly", help="Which cycle to run")
    parser.add_argument("--event-type", default="", help="Critical event type")
    parser.add_argument("--event-data", default="{}", help="Critical event data (JSON string)")

    args = parser.parse_args()
    event_data = json.loads(args.event_data) if args.event_data else {}
    main(trigger=args.trigger, event_type=args.event_type, event_data=event_data)
