#!/usr/bin/env python3
"""
Delegator — Sub-Agent Management for CEO-Bot
Triggers skills, modifies configs within guardrails, checks performance,
resolves conflicts between optimizers, and runs weekly performance reviews.
"""

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")

CRM_ENGINE = None


def _get_crm_engine():
    """Lazy-load CRM engine module."""
    global CRM_ENGINE
    if CRM_ENGINE is None:
        crm_path = os.path.join(SKILLS_DIR, "crm-engine", "crm_engine.py")
        spec = importlib.util.spec_from_file_location("crm_engine", crm_path)
        crm_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crm_module)
        CRM_ENGINE = crm_module
    return CRM_ENGINE


def _log(action: str, result: str, details: str, lead_id: Optional[str] = None) -> None:
    """Append structured log entry to system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "ceo-bot",
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": "none",
        "tokens_estimated": 0,
        "cost_estimated": 0.0,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_ceo_config() -> dict:
    """Load CEO-bot configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _load_skill_config(skill_name: str) -> dict:
    """Load a managed skill's config.json."""
    path = os.path.join(SKILLS_DIR, skill_name, "config.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found for skill: {skill_name}")
    with open(path, "r") as f:
        return json.load(f)


def _save_skill_config(skill_name: str, config: dict) -> None:
    """Write a managed skill's config.json."""
    path = os.path.join(SKILLS_DIR, skill_name, "config.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def _load_skill_module(skill_name: str):
    """Dynamically load a skill's main Python module."""
    skill_dir = os.path.join(SKILLS_DIR, skill_name)
    # Convention: main module is <skill_name_with_underscores>.py
    module_name = skill_name.replace("-", "_")
    module_path = os.path.join(skill_dir, f"{module_name}.py")
    if not os.path.exists(module_path):
        raise FileNotFoundError(f"Module not found: {module_path}")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_managed_skills() -> list:
    """Return the list of skills CEO-bot manages."""
    config = _load_ceo_config()
    return config.get("managed_skills", [])


# ── Core Functions ────────────────────────────────────────────────────

def delegate_task(skill_name: str, task_description: str) -> dict:
    """Trigger a skill to execute a specific task.

    Loads the skill module and calls its ``handle_delegation(task_description)``
    function if available.  If the skill lacks that entry point, falls back to
    writing a task file that the skill picks up on its next scheduled run.

    Returns a result dict with status and any output from the skill.
    """
    config = _load_ceo_config()
    if not config.get("authority", {}).get("can_trigger_skills", False):
        _log("delegate_task", "blocked", f"No authority to trigger skills. skill={skill_name}")
        return {"status": "blocked", "reason": "authority_denied"}

    if skill_name not in _get_managed_skills():
        _log("delegate_task", "rejected", f"Skill not managed: {skill_name}")
        return {"status": "rejected", "reason": f"skill '{skill_name}' is not a managed skill"}

    _log("delegate_task", "initiated", f"skill={skill_name} task={task_description[:200]}")

    # Attempt to call the skill's delegation handler
    try:
        mod = _load_skill_module(skill_name)
        if hasattr(mod, "handle_delegation"):
            output = mod.handle_delegation(task_description)
            _log("delegate_task", "success",
                 f"skill={skill_name} output_len={len(str(output))}")
            # Log to delegation log via memory manager
            from memory_manager import log_delegation
            log_delegation({
                "target_skill": skill_name,
                "task_description": task_description,
                "priority": "normal",
                "status": "completed",
                "triggered_by": "ceo-bot",
                "outcome": str(output)[:500],
            })
            return {"status": "success", "output": output}
        else:
            # Fallback: write a task file for the skill to pick up
            task_file = os.path.join(SKILLS_DIR, skill_name, "pending_task.json")
            task_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "from": "ceo-bot",
                "task": task_description,
                "status": "pending",
            }
            with open(task_file, "w") as f:
                json.dump(task_entry, f, indent=2)
                f.write("\n")
            _log("delegate_task", "queued",
                 f"skill={skill_name} no handle_delegation, wrote pending_task.json")
            from memory_manager import log_delegation
            log_delegation({
                "target_skill": skill_name,
                "task_description": task_description,
                "priority": "normal",
                "status": "queued",
                "triggered_by": "ceo-bot",
                "outcome": "pending_task.json written",
            })
            return {"status": "queued", "task_file": task_file}
    except Exception as exc:
        _log("delegate_task", "error", f"skill={skill_name} error={exc}")
        return {"status": "error", "error": str(exc)}


def modify_skill_config(skill_name: str, param: str, value) -> dict:
    """Modify a single parameter in a skill's config.json within guardrails.

    Guardrails enforced:
    - Cannot modify blocked fields (pricing, api_keys, security).
    - Send volume changes capped at configured percentage.
    - Budget increases capped at configured percentage.

    Returns a dict with the old value, new value, and status.
    """
    ceo_config = _load_ceo_config()
    authority = ceo_config.get("authority", {})

    if not authority.get("can_modify_configs", False):
        _log("modify_config", "blocked", f"No authority. skill={skill_name} param={param}")
        return {"status": "blocked", "reason": "authority_denied"}

    if skill_name not in _get_managed_skills():
        _log("modify_config", "rejected", f"Skill not managed: {skill_name}")
        return {"status": "rejected", "reason": f"skill '{skill_name}' not managed"}

    guardrails = authority.get("config_modification_guardrails", {})
    blocked_fields = guardrails.get("blocked_fields", [])

    # Check blocked fields — param or any parent key
    for blocked in blocked_fields:
        if blocked in param.lower():
            _log("modify_config", "blocked",
                 f"Blocked field. skill={skill_name} param={param}")
            return {"status": "blocked", "reason": f"field '{param}' is in blocked list"}

    skill_config = _load_skill_config(skill_name)

    # Navigate nested params using dot notation (e.g., "sending.daily_limit")
    keys = param.split(".")
    container = skill_config
    for key in keys[:-1]:
        if key not in container or not isinstance(container[key], dict):
            _log("modify_config", "error",
                 f"Path not found. skill={skill_name} param={param}")
            return {"status": "error", "reason": f"config path '{param}' not found"}
        container = container[key]

    final_key = keys[-1]
    old_value = container.get(final_key)

    # Enforce send volume change cap
    max_send_change = guardrails.get("max_send_volume_change_pct", 20)
    if "volume" in param.lower() or "limit" in param.lower() or "send" in param.lower():
        if old_value is not None and isinstance(old_value, (int, float)) and old_value > 0:
            change_pct = abs(value - old_value) / old_value * 100
            if change_pct > max_send_change:
                _log("modify_config", "blocked",
                     f"Change too large ({change_pct:.1f}% > {max_send_change}%). "
                     f"skill={skill_name} param={param} old={old_value} new={value}")
                return {
                    "status": "blocked",
                    "reason": f"change of {change_pct:.1f}% exceeds {max_send_change}% cap",
                }

    # Enforce budget increase cap
    max_budget_increase = guardrails.get("max_budget_increase_pct", 0)
    if "budget" in param.lower() or "cost" in param.lower() or "spend" in param.lower():
        if old_value is not None and isinstance(old_value, (int, float)):
            if value > old_value:
                increase_pct = ((value - old_value) / old_value * 100) if old_value > 0 else 100
                if increase_pct > max_budget_increase:
                    _log("modify_config", "blocked",
                         f"Budget increase {increase_pct:.1f}% exceeds cap {max_budget_increase}%. "
                         f"skill={skill_name} param={param}")
                    return {
                        "status": "blocked",
                        "reason": f"budget increase of {increase_pct:.1f}% exceeds {max_budget_increase}% cap",
                    }

    container[final_key] = value
    _save_skill_config(skill_name, skill_config)

    _log("modify_config", "success",
         f"skill={skill_name} param={param} old={old_value} new={value}")
    return {"status": "success", "param": param, "old_value": old_value, "new_value": value}


def get_skill_status(skill_name: str) -> dict:
    """Check a skill's performance by reading its config and recent logs.

    Returns a dict with: config summary, recent log entries (last 50),
    error count, last run time, and CRM-derived metrics where applicable.
    """
    if skill_name not in _get_managed_skills():
        return {"status": "error", "reason": f"skill '{skill_name}' not managed"}

    result: dict = {"skill": skill_name, "timestamp": datetime.now(timezone.utc).isoformat()}

    # Config snapshot
    try:
        config = _load_skill_config(skill_name)
        result["config_version"] = config.get("version", "unknown")
        result["config_keys"] = list(config.keys())
    except FileNotFoundError:
        result["config_error"] = "config.json not found"

    # Recent logs for this skill
    recent_logs: list = []
    error_count = 0
    last_run: Optional[str] = None

    if os.path.exists(LOG_PATH):
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)
        with open(LOG_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("skill") != skill_name:
                    continue
                try:
                    ts = datetime.fromisoformat(entry["timestamp"])
                except (KeyError, ValueError):
                    continue
                if ts < day_ago:
                    continue
                recent_logs.append(entry)
                if entry.get("result") in ("failure", "error"):
                    error_count += 1
                last_run = entry["timestamp"]

    result["logs_24h"] = len(recent_logs)
    result["errors_24h"] = error_count
    result["last_run"] = last_run
    result["recent_entries"] = recent_logs[-50:]

    # CRM metrics if available
    try:
        crm = _get_crm_engine()
        metrics = crm.get_all_metrics()
        result["crm_metrics"] = metrics
    except Exception:
        pass

    _log("get_skill_status", "success", f"skill={skill_name} logs={len(recent_logs)} errors={error_count}")
    return result


def resolve_conflict(skill_a: str, skill_b: str, context: str) -> dict:
    """Decide between conflicting optimizer recommendations.

    Uses Claude to analyze the conflict and produce a binding decision with
    rationale. The decision specifies which skill's recommendation to follow
    and any modifications to apply.
    """
    from ceo_bot import call_claude, check_authority

    if not check_authority("reallocate_resources"):
        _log("resolve_conflict", "blocked", f"No authority. {skill_a} vs {skill_b}")
        return {"status": "blocked", "reason": "authority_denied"}

    # Gather status of both skills
    status_a = get_skill_status(skill_a)
    status_b = get_skill_status(skill_b)

    system_prompt = (
        "You are the CEO-bot for NeverMiss AI, resolving a conflict between two optimizer "
        "skills. Analyze both sides and produce a binding decision. Be concise.\n\n"
        "Output JSON with keys: winner (skill name), rationale (1-2 sentences), "
        "actions (list of concrete steps), modifications (any config changes needed)."
    )

    prompt = (
        f"CONFLICT: {skill_a} vs {skill_b}\n\n"
        f"CONTEXT: {context}\n\n"
        f"SKILL A ({skill_a}) STATUS:\n{json.dumps(status_a, indent=2, default=str)[:2000]}\n\n"
        f"SKILL B ({skill_b}) STATUS:\n{json.dumps(status_b, indent=2, default=str)[:2000]}"
    )

    try:
        response_text, cost = call_claude(prompt, system_prompt, max_tokens=1024)
        # Try to parse as JSON, fall back to raw text
        try:
            decision = json.loads(response_text)
        except json.JSONDecodeError:
            decision = {"raw_analysis": response_text}

        decision["status"] = "resolved"
        decision["skill_a"] = skill_a
        decision["skill_b"] = skill_b
        decision["cost"] = cost

        _log("resolve_conflict", "success",
             f"{skill_a} vs {skill_b} winner={decision.get('winner', 'see analysis')}")
        return decision

    except RuntimeError as exc:
        _log("resolve_conflict", "error", f"Claude call failed: {exc}")
        return {
            "status": "error",
            "error": str(exc),
            "fallback": "Manual review needed — Claude budget may be exhausted.",
        }


def weekly_performance_review() -> dict:
    """Review all managed skills' performance over the past week.

    Aggregates logs, error rates, and CRM metrics for each skill, then uses
    Claude to produce a structured performance assessment with grades and
    recommendations.
    """
    from ceo_bot import call_claude

    managed = _get_managed_skills()
    skill_reports: dict = {}

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Aggregate per-skill log data for the week
    skill_logs: dict = {s: {"total": 0, "errors": 0, "last_run": None} for s in managed}

    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                skill = entry.get("skill", "")
                if skill not in skill_logs:
                    continue
                try:
                    ts = datetime.fromisoformat(entry["timestamp"])
                except (KeyError, ValueError):
                    continue
                if ts < week_ago:
                    continue
                skill_logs[skill]["total"] += 1
                if entry.get("result") in ("failure", "error"):
                    skill_logs[skill]["errors"] += 1
                skill_logs[skill]["last_run"] = entry["timestamp"]

    for skill_name in managed:
        report = {
            "skill": skill_name,
            "log_entries_7d": skill_logs[skill_name]["total"],
            "errors_7d": skill_logs[skill_name]["errors"],
            "error_rate": (
                round(skill_logs[skill_name]["errors"] / skill_logs[skill_name]["total"] * 100, 1)
                if skill_logs[skill_name]["total"] > 0 else 0.0
            ),
            "last_run": skill_logs[skill_name]["last_run"],
        }
        # Load config version
        try:
            cfg = _load_skill_config(skill_name)
            report["version"] = cfg.get("version", "unknown")
        except FileNotFoundError:
            report["version"] = "config_missing"

        skill_reports[skill_name] = report

    # CRM pipeline for overall context
    try:
        crm = _get_crm_engine()
        pipeline = crm.get_pipeline_data()
        crm_summary = {
            "total_leads": len(pipeline.get("leads", {})),
            "metrics": pipeline.get("metrics", {}),
        }
    except Exception as exc:
        crm_summary = {"error": str(exc)}

    # Claude analysis
    system_prompt = (
        "You are CEO-bot for NeverMiss AI, conducting a weekly performance review of all "
        "sub-agent skills. Grade each skill (A/B/C/D/F), identify top performers, "
        "underperformers, and provide specific recommendations.\n\n"
        "Output JSON with keys: overall_grade, skill_grades (dict of skill->grade), "
        "top_performers (list), underperformers (list), recommendations (list of "
        "{skill, action, priority}), systemic_issues (list)."
    )

    prompt = (
        f"WEEKLY PERFORMANCE DATA (past 7 days):\n\n"
        f"SKILL REPORTS:\n{json.dumps(skill_reports, indent=2, default=str)}\n\n"
        f"CRM PIPELINE:\n{json.dumps(crm_summary, indent=2, default=str)}\n\n"
        f"TARGETS: reply>3%, qualified>40% of replies, booking>40% of qualified, close>25% of demos"
    )

    try:
        response_text, cost = call_claude(prompt, system_prompt, max_tokens=2048)
        try:
            review = json.loads(response_text)
        except json.JSONDecodeError:
            review = {"raw_analysis": response_text}
        review["status"] = "complete"
        review["cost"] = cost
    except RuntimeError as exc:
        review = {
            "status": "error",
            "error": str(exc),
            "skill_reports": skill_reports,
        }

    review["timestamp"] = now.isoformat()
    review["skill_reports"] = skill_reports
    review["crm_summary"] = crm_summary

    _log("weekly_performance_review", "success" if review["status"] == "complete" else "error",
         f"skills={len(managed)} status={review['status']}")

    return review
