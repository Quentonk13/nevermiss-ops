#!/usr/bin/env python3
"""
Nightly Review — 10PM PT
Complete nightly review cycle:
1. Aggregate all skill data
2. Analyze vs targets using Claude
3. Execute delegations to specific skills
4. Update 3-layer memory
5. 1% improvement identification and implementation
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SKILL_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CEO_MEMORY_DIR = os.path.join(DATA_DIR, "ceo_memory")
IMPROVEMENTS_LOG = os.path.join(CEO_MEMORY_DIR, "improvements_log.jsonl")
DELEGATIONS_LOG = os.path.join(CEO_MEMORY_DIR, "delegations_log.jsonl")
SYSTEM_LOG = os.path.join(DATA_DIR, "system_log.jsonl")

import ceo_bot


# ---------------------------------------------------------------------------
# Step 1: Aggregate all skill data
# ---------------------------------------------------------------------------

def _read_json(path: str, default: Any = None) -> Any:
    """Safely read a JSON file."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default if default is not None else {}


def _read_jsonl_today(path: str) -> list[dict]:
    """Read JSONL entries from today (UTC)."""
    if not os.path.exists(path):
        return []
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp", "")
                if ts.startswith(today_str):
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def _count_log_entries(skill: str, action: str = "", result: str = "") -> int:
    """Count system log entries matching criteria for today."""
    entries = _read_jsonl_today(SYSTEM_LOG)
    count = 0
    for e in entries:
        if e.get("skill") != skill:
            continue
        if action and e.get("action") != action:
            continue
        if result and e.get("result") != result:
            continue
        count += 1
    return count


def aggregate_skill_data() -> dict:
    """Aggregate data from all skills into a unified snapshot."""
    crm_data = _read_json(os.path.join(DATA_DIR, "crm.json"), [])
    send_log = _read_json(os.path.join(DATA_DIR, "outreach_send_log.json"), [])
    daily_report = _read_json(os.path.join(DATA_DIR, "outreach_daily_report.json"), {})
    conversations = _read_json(os.path.join(DATA_DIR, "conversations", "active.json"), [])
    optimization_data = _read_json(os.path.join(DATA_DIR, "optimization", "current.json"), {})
    competitive_data = _read_json(os.path.join(DATA_DIR, "competitive_edge", "latest.json"), {})

    today_logs = _read_jsonl_today(SYSTEM_LOG)

    # Count emails sent today
    emails_sent_today = 0
    for entry in today_logs:
        if entry.get("skill") == "outreach-sequencer" and entry.get("action") == "send_email" and entry.get("result") == "success":
            emails_sent_today += 1
    if emails_sent_today == 0:
        emails_sent_today = daily_report.get("emails_sent_today", 0)

    # Count replies today
    replies_today = 0
    for entry in today_logs:
        if entry.get("skill") == "reply-handler" and entry.get("action") in ("reply_processed", "handle_reply") and entry.get("result") == "success":
            replies_today += 1

    # Count conversations
    active_conversations = len(conversations) if isinstance(conversations, list) else 0

    # Count demos
    demos_today = 0
    demos_scheduled = 0
    if isinstance(crm_data, list):
        for lead in crm_data:
            status = lead.get("status", "")
            if status == "demo_completed":
                demos_today += 1
            elif status == "booked":
                demos_scheduled += 1

    # Count deals
    deals_closed = 0
    if isinstance(crm_data, list):
        for lead in crm_data:
            if lead.get("status") == "closed":
                deals_closed += 1

    # Pipeline breakdown
    pipeline = {}
    if isinstance(crm_data, list):
        for lead in crm_data:
            status = lead.get("status", "unknown")
            pipeline[status] = pipeline.get(status, 0) + 1

    # Total leads
    total_leads = len(crm_data) if isinstance(crm_data, list) else 0

    # Errors today
    errors_today = 0
    for entry in today_logs:
        if entry.get("result") in ("failure", "error"):
            errors_today += 1

    # API costs today
    api_costs_today = 0.0
    for entry in today_logs:
        api_costs_today += entry.get("cost_estimated", 0.0)

    # Browser activity
    browser_actions = 0
    for entry in today_logs:
        if entry.get("skill") == "browser-agent":
            browser_actions += 1

    # QA rejections
    qa_rejections = 0
    for entry in today_logs:
        if entry.get("skill") == "qa-guard" and entry.get("result") == "rejected":
            qa_rejections += 1

    snapshot = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "emails_sent": emails_sent_today,
        "replies": replies_today,
        "reply_rate_pct": round((replies_today / emails_sent_today * 100), 2) if emails_sent_today > 0 else 0.0,
        "active_conversations": active_conversations,
        "demos_scheduled": demos_scheduled,
        "demos_completed": demos_today,
        "deals_closed": deals_closed,
        "total_leads": total_leads,
        "pipeline": pipeline,
        "errors": errors_today,
        "api_costs_usd": round(api_costs_today, 4),
        "browser_actions": browser_actions,
        "qa_rejections": qa_rejections,
        "optimization_data": optimization_data,
        "competitive_intel": competitive_data,
    }

    ceo_bot.log("aggregate_data", "success", f"snapshot: {json.dumps({k: v for k, v in snapshot.items() if k not in ('pipeline', 'optimization_data', 'competitive_intel')})}")
    return snapshot


# ---------------------------------------------------------------------------
# Step 2: Analyze vs targets
# ---------------------------------------------------------------------------

def analyze_performance(snapshot: dict) -> dict:
    """Use Claude to analyze performance against targets."""
    config = ceo_bot.load_config()
    targets = config["targets"]

    # Calculate derived rates
    qualified_count = snapshot["pipeline"].get("qualified", 0) + snapshot["pipeline"].get("booked", 0) + snapshot["pipeline"].get("demo_completed", 0) + snapshot["pipeline"].get("closed", 0)
    qualified_of_replies = round((qualified_count / snapshot["replies"] * 100), 2) if snapshot["replies"] > 0 else 0.0
    booking_of_qualified = round((snapshot["demos_scheduled"] + snapshot["demos_completed"]) / qualified_count * 100, 2) if qualified_count > 0 else 0.0
    close_of_demos = round(snapshot["deals_closed"] / snapshot["demos_completed"] * 100, 2) if snapshot["demos_completed"] > 0 else 0.0

    metrics = {
        "reply_rate_pct": snapshot["reply_rate_pct"],
        "reply_target": targets["reply_rate_pct"],
        "qualified_of_replies_pct": qualified_of_replies,
        "qualified_target": targets["qualified_rate_of_replies_pct"],
        "booking_of_qualified_pct": booking_of_qualified,
        "booking_target": targets["booking_rate_of_qualified_pct"],
        "close_of_demos_pct": close_of_demos,
        "close_target": targets["close_rate_of_demos_pct"],
    }

    system_prompt = (
        "You are the CEO-bot for NeverMiss AI, a startup selling AI receptionist services "
        "to home service businesses (HVAC, plumbing, electrical, roofing, etc.). "
        "You are conducting the nightly performance review. Be brutally honest, data-driven, "
        "and action-oriented. No fluff."
    )

    prompt = f"""NIGHTLY PERFORMANCE REVIEW — {snapshot['date']}

TODAY'S DATA:
- Emails sent: {snapshot['emails_sent']}
- Replies: {snapshot['replies']} ({snapshot['reply_rate_pct']}% rate, target: >{targets['reply_rate_pct']}%)
- Qualified of replies: {qualified_of_replies}% (target: >{targets['qualified_rate_of_replies_pct']}%)
- Booking of qualified: {booking_of_qualified}% (target: >{targets['booking_rate_of_qualified_pct']}%)
- Close of demos: {close_of_demos}% (target: >{targets['close_rate_of_demos_pct']}%)
- Demos scheduled: {snapshot['demos_scheduled']}
- Demos completed: {snapshot['demos_completed']}
- Deals closed: {snapshot['deals_closed']}
- Total leads: {snapshot['total_leads']}
- Active conversations: {snapshot['active_conversations']}
- Errors: {snapshot['errors']}
- API costs: ${snapshot['api_costs_usd']}
- QA rejections: {snapshot['qa_rejections']}
- Browser actions: {snapshot['browser_actions']}

PIPELINE BREAKDOWN:
{json.dumps(snapshot['pipeline'], indent=2)}

Respond in EXACTLY this JSON format:
{{
  "wins": ["win1", "win2"],
  "issues": ["issue1", "issue2"],
  "bottleneck": "The single biggest bottleneck right now",
  "tomorrows_priority": "The ONE thing to focus on tomorrow",
  "delegations": [
    {{"skill": "skill-name", "task": "specific task description", "priority": "high|medium|low", "parameters": {{}}}}
  ]
}}"""

    try:
        response_text, cost = ceo_bot.call_claude(prompt, system_prompt, max_tokens=2048)
        # Parse JSON from response (handle markdown code blocks)
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        analysis = json.loads(text)
    except json.JSONDecodeError:
        analysis = {
            "wins": [],
            "issues": [f"Failed to parse Claude analysis: {response_text[:200]}"],
            "bottleneck": "Analysis parsing error",
            "tomorrows_priority": "Fix analysis pipeline",
            "delegations": [],
        }
    except RuntimeError as e:
        # Budget exhausted — fall back to rule-based analysis
        analysis = _rule_based_analysis(snapshot, metrics)
        ceo_bot.log("analyze_performance", "fallback", f"Claude unavailable ({e}), using rule-based analysis")

    analysis["metrics"] = metrics
    ceo_bot.log("analyze_performance", "success",
                f"wins={len(analysis.get('wins', []))} issues={len(analysis.get('issues', []))} "
                f"delegations={len(analysis.get('delegations', []))}")
    return analysis


def _rule_based_analysis(snapshot: dict, metrics: dict) -> dict:
    """Fallback rule-based analysis when Claude is unavailable."""
    wins = []
    issues = []
    delegations = []

    if metrics["reply_rate_pct"] >= metrics["reply_target"]:
        wins.append(f"Reply rate {metrics['reply_rate_pct']}% exceeds {metrics['reply_target']}% target")
    else:
        issues.append(f"Reply rate {metrics['reply_rate_pct']}% below {metrics['reply_target']}% target")
        delegations.append({
            "skill": "email-optimizer",
            "task": "Analyze and optimize underperforming email variants",
            "priority": "high",
            "parameters": {},
        })

    if metrics["qualified_of_replies_pct"] >= metrics["qualified_target"]:
        wins.append(f"Qualification rate {metrics['qualified_of_replies_pct']}% on target")
    else:
        issues.append(f"Qualification rate {metrics['qualified_of_replies_pct']}% below {metrics['qualified_target']}% target")
        delegations.append({
            "skill": "reply-handler",
            "task": "Review qualification criteria — too many replies not converting to qualified",
            "priority": "high",
            "parameters": {},
        })

    if snapshot["errors"] > 10:
        issues.append(f"High error count: {snapshot['errors']} errors today")
        delegations.append({
            "skill": "qa-guard",
            "task": f"Investigate {snapshot['errors']} errors from today",
            "priority": "medium",
            "parameters": {},
        })

    if snapshot["emails_sent"] == 0:
        issues.append("Zero emails sent today — outreach pipeline stalled")
        delegations.append({
            "skill": "outreach-sequencer",
            "task": "Diagnose why no emails were sent today",
            "priority": "high",
            "parameters": {},
        })

    bottleneck = "Unknown"
    if metrics["reply_rate_pct"] < metrics["reply_target"]:
        bottleneck = "Reply rate — emails not generating enough responses"
    elif metrics["qualified_of_replies_pct"] < metrics["qualified_target"]:
        bottleneck = "Qualification — replies not converting to qualified leads"
    elif metrics["booking_of_qualified_pct"] < metrics["booking_target"]:
        bottleneck = "Booking — qualified leads not booking demos"
    elif metrics["close_of_demos_pct"] < metrics["close_target"]:
        bottleneck = "Closing — demos not converting to deals"

    priority = "Improve reply rate" if metrics["reply_rate_pct"] < metrics["reply_target"] else "Maintain momentum and push qualified leads to demos"

    return {
        "wins": wins,
        "issues": issues,
        "bottleneck": bottleneck,
        "tomorrows_priority": priority,
        "delegations": delegations,
    }


# ---------------------------------------------------------------------------
# Step 3: Execute delegations
# ---------------------------------------------------------------------------

def execute_delegations(delegations: list[dict]) -> list[dict]:
    """Delegate tasks to specific skills via the delegator module."""
    sys.path.insert(0, SKILL_DIR)
    from delegator import delegate_task

    results = []
    for delegation in delegations:
        skill = delegation.get("skill", "")
        task = delegation.get("task", "")
        priority = delegation.get("priority", "medium")
        parameters = delegation.get("parameters", {})

        result = delegate_task(skill, task, priority, parameters)
        results.append(result)

        # Log to delegations log
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skill": skill,
            "task": task,
            "priority": priority,
            "parameters": parameters,
            "result": result.get("status", "unknown"),
            "details": result.get("details", ""),
        }
        os.makedirs(os.path.dirname(DELEGATIONS_LOG), exist_ok=True)
        with open(DELEGATIONS_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")

    ceo_bot.log("execute_delegations", "success", f"delegated={len(delegations)} results={len(results)}")
    return results


# ---------------------------------------------------------------------------
# Step 4: Update 3-layer memory
# ---------------------------------------------------------------------------

def update_memory(snapshot: dict, analysis: dict) -> None:
    """Update the 3-layer memory system."""
    sys.path.insert(0, SKILL_DIR)
    from memory_manager import update_daily_note, update_knowledge_graph, update_tacit_knowledge

    # Layer 2: Daily note
    update_daily_note(snapshot, analysis)

    # Layer 1: Knowledge graph — update pipeline facts
    knowledge_updates = {
        "total_leads": snapshot["total_leads"],
        "pipeline": snapshot["pipeline"],
        "deals_closed": snapshot["deals_closed"],
        "last_updated": snapshot["date"],
    }
    update_knowledge_graph("pipeline_status", knowledge_updates)

    # Layer 3: Tacit knowledge — extract lessons from issues
    if analysis.get("issues"):
        for issue in analysis["issues"]:
            update_tacit_knowledge(
                category="nightly_review_issue",
                lesson=issue,
                date=snapshot["date"],
            )

    ceo_bot.log("update_memory", "success", "All 3 memory layers updated")


# ---------------------------------------------------------------------------
# Step 5: 1% Improvement
# ---------------------------------------------------------------------------

def _load_recent_improvements(days: int = 7) -> list[dict]:
    """Load recent improvement entries."""
    if not os.path.exists(IMPROVEMENTS_LOG):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []
    with open(IMPROVEMENTS_LOG, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
                if ts >= cutoff:
                    entries.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue
    return entries


def _check_negative_trend() -> bool:
    """Check if last 3 improvements had negative outcomes. If so, auto-pause."""
    recent = _load_recent_improvements(days=14)
    measured = [e for e in recent if e.get("outcome") in ("positive", "negative", "neutral")]
    if len(measured) < 3:
        return False
    last_three = measured[-3:]
    if all(e["outcome"] == "negative" for e in last_three):
        config = ceo_bot.load_config()
        config["improvement_system"]["paused"] = True
        ceo_bot.save_config(config)
        ceo_bot.log("improvement_system", "auto_paused",
                     "3 consecutive negative improvements detected — system paused, owner notified")
        return True
    return False


def _measure_previous_improvement() -> None:
    """Measure the outcome of the most recent improvement by comparing its metric."""
    if not os.path.exists(IMPROVEMENTS_LOG):
        return
    lines = []
    with open(IMPROVEMENTS_LOG, "r") as f:
        lines = f.readlines()
    if not lines:
        return

    # Find last entry that has no outcome yet
    updated = False
    new_lines = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            new_lines.append(line)
            continue
        try:
            entry = json.loads(line_stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        if not updated and entry.get("outcome") == "pending":
            metric_name = entry.get("metric_name", "")
            baseline = entry.get("baseline_value")
            if metric_name and baseline is not None:
                current = _get_current_metric_value(metric_name)
                if current is not None:
                    if current > baseline:
                        entry["outcome"] = "positive"
                    elif current < baseline:
                        entry["outcome"] = "negative"
                    else:
                        entry["outcome"] = "neutral"
                    entry["measured_value"] = current
                    entry["measured_at"] = datetime.now(timezone.utc).isoformat()
                    updated = True
            new_lines.append(json.dumps(entry) + "\n")
        else:
            new_lines.append(line)

    with open(IMPROVEMENTS_LOG, "w") as f:
        f.writelines(new_lines)


def _get_current_metric_value(metric_name: str) -> float | None:
    """Get the current value of a metric by name."""
    snapshot = aggregate_skill_data()
    metric_map = {
        "reply_rate_pct": snapshot.get("reply_rate_pct"),
        "emails_sent": snapshot.get("emails_sent"),
        "errors": snapshot.get("errors"),
        "qa_rejections": snapshot.get("qa_rejections"),
        "api_costs_usd": snapshot.get("api_costs_usd"),
        "demos_scheduled": snapshot.get("demos_scheduled"),
        "deals_closed": snapshot.get("deals_closed"),
    }
    return metric_map.get(metric_name)


def identify_and_implement_improvement(snapshot: dict, analysis: dict) -> dict | None:
    """Identify ONE small, low-risk, measurable, reversible improvement and implement it."""
    config = ceo_bot.load_config()

    # Check if improvement system is paused
    if config.get("improvement_system", {}).get("paused", False):
        ceo_bot.log("improvement_system", "skipped", "System is paused due to consecutive negative outcomes")
        return None

    # Measure previous improvement first
    _measure_previous_improvement()

    # Check for negative trend
    if _check_negative_trend():
        return None

    system_prompt = (
        "You are the CEO-bot improvement engine for NeverMiss AI. "
        "Your job: identify exactly ONE small improvement that is: "
        "1) Low-risk — will not break anything, 2) Measurable — has a clear before/after metric, "
        "3) Reversible — can be undone easily. "
        "You can adjust config parameters of any skill within guardrails. "
        "Focus on the biggest bottleneck."
    )

    recent_improvements = _load_recent_improvements(days=7)
    recent_summary = ""
    if recent_improvements:
        recent_summary = "\nRecent improvements (avoid repeating):\n"
        for imp in recent_improvements[-5:]:
            recent_summary += f"- {imp.get('description', 'N/A')} -> {imp.get('outcome', 'pending')}\n"

    prompt = f"""Today's data:
{json.dumps({k: v for k, v in snapshot.items() if k not in ('optimization_data', 'competitive_intel')}, indent=2)}

Analysis:
- Bottleneck: {analysis.get('bottleneck', 'unknown')}
- Issues: {json.dumps(analysis.get('issues', []))}
{recent_summary}

Available config changes (guardrails: max 20% send volume change, no budget increases, no security/pricing/API key changes):
- outreach-sequencer: send_window, follow_up_sequence timing, variant_rotation strategy
- email-optimizer: variant thresholds
- lead-pipeline: scoring weights, filters
- reply-handler: response timing, qualification criteria weights
- sales-closer: follow-up intervals, objection handling parameters

Respond in this exact JSON format:
{{
  "description": "One-line description of the improvement",
  "skill_to_modify": "skill-name",
  "config_key": "dot.separated.config.path",
  "old_value": "current value",
  "new_value": "proposed value",
  "metric_name": "metric to measure (reply_rate_pct|emails_sent|errors|qa_rejections|demos_scheduled|deals_closed)",
  "baseline_value": 0.0,
  "rationale": "Why this should help"
}}"""

    try:
        response_text, cost = ceo_bot.call_claude(prompt, system_prompt, max_tokens=1024)
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        improvement = json.loads(text)
    except (json.JSONDecodeError, RuntimeError) as e:
        ceo_bot.log("improvement_system", "skipped", f"Could not identify improvement: {e}")
        return None

    # Validate the improvement is within guardrails
    skill_name = improvement.get("skill_to_modify", "")
    config_key = improvement.get("config_key", "")
    guardrails = config["authority"]["config_modification_guardrails"]
    blocked = guardrails.get("blocked_fields", [])
    for blocked_field in blocked:
        if blocked_field in config_key.lower():
            ceo_bot.log("improvement_system", "blocked",
                         f"Improvement touches blocked field: {config_key}")
            return None

    # Implement: modify the target skill's config
    skill_config_path = os.path.join(PROJECT_ROOT, "skills", skill_name, "config.json")
    if os.path.exists(skill_config_path):
        try:
            with open(skill_config_path, "r") as f:
                skill_config = json.load(f)

            # Navigate dot-separated path and set value
            keys = config_key.split(".")
            obj = skill_config
            for key in keys[:-1]:
                if key in obj:
                    obj = obj[key]
                else:
                    ceo_bot.log("improvement_system", "failed",
                                 f"Config path not found: {config_key} in {skill_name}")
                    return None

            final_key = keys[-1]
            if final_key not in obj:
                ceo_bot.log("improvement_system", "failed",
                             f"Config key not found: {final_key} in {skill_name}")
                return None

            actual_old = obj[final_key]
            improvement["old_value"] = actual_old
            obj[final_key] = improvement["new_value"]

            with open(skill_config_path, "w") as f:
                json.dump(skill_config, f, indent=2)
                f.write("\n")

            ceo_bot.log("improvement_system", "implemented",
                         f"Changed {skill_name}/{config_key}: {actual_old} -> {improvement['new_value']}")

        except (json.JSONDecodeError, IOError, KeyError) as e:
            ceo_bot.log("improvement_system", "failed", f"Config modification error: {e}")
            return None
    else:
        ceo_bot.log("improvement_system", "skipped", f"No config.json found for skill: {skill_name}")
        return None

    # Log the improvement
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": improvement.get("description", ""),
        "skill": skill_name,
        "config_key": config_key,
        "old_value": improvement.get("old_value"),
        "new_value": improvement.get("new_value"),
        "metric_name": improvement.get("metric_name", ""),
        "baseline_value": improvement.get("baseline_value", 0.0),
        "rationale": improvement.get("rationale", ""),
        "outcome": "pending",
    }
    os.makedirs(os.path.dirname(IMPROVEMENTS_LOG), exist_ok=True)
    with open(IMPROVEMENTS_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return improvement


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

def execute_nightly_review() -> dict:
    """Execute the complete nightly review cycle."""
    ceo_bot.ensure_directories()
    ceo_bot.log("nightly_review", "started", "Beginning nightly review cycle")

    # Step 1: Aggregate
    snapshot = aggregate_skill_data()

    # Step 2: Analyze
    analysis = analyze_performance(snapshot)

    # Step 3: Delegate
    delegations = analysis.get("delegations", [])
    delegation_results = []
    if delegations:
        delegation_results = execute_delegations(delegations)

    # Step 4: Memory
    update_memory(snapshot, analysis)

    # Step 5: 1% Improvement
    improvement = identify_and_implement_improvement(snapshot, analysis)

    summary = {
        "date": snapshot["date"],
        "emails_sent": snapshot["emails_sent"],
        "replies": snapshot["replies"],
        "reply_rate_pct": snapshot["reply_rate_pct"],
        "deals_closed": snapshot["deals_closed"],
        "bottleneck": analysis.get("bottleneck", ""),
        "tomorrows_priority": analysis.get("tomorrows_priority", ""),
        "delegations_count": len(delegations),
        "improvement": improvement.get("description", "None") if improvement else "None",
    }

    ceo_bot.log("nightly_review", "complete", json.dumps(summary))
    return {"summary": summary, "snapshot": snapshot, "analysis": analysis,
            "delegation_results": delegation_results, "improvement": improvement}


if __name__ == "__main__":
    result = execute_nightly_review()
    print(json.dumps(result["summary"], indent=2))
