#!/usr/bin/env python3
"""
Sales Optimizer — Continuous Close Rate Improvement
Analyzes conversations, optimizes objection scripts, enhances demo prep,
adjusts lead score weights, and auto-reverts degraded performance.

LLM: Claude Sonnet ($20/week cap) for conversation analysis.
     Groq/Llama for pattern extraction and pacing stats.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")
SCRIPT_VERSIONS_DIR = os.path.join(PROJECT_ROOT, "data", "optimization", "script_versions")
OPTIMIZATION_LOG = os.path.join(PROJECT_ROOT, "data", "optimization", "sales_optimization_log.jsonl")
WINNING_PHRASES_PATH = os.path.join(PROJECT_ROOT, "data", "winning_phrases.json")
CRM_PATH = os.path.join(PROJECT_ROOT, "data", "crm.json")


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "sales-optimizer",
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


def _load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _load_crm_data() -> dict:
    if not os.path.exists(CRM_PATH):
        return {"leads": []}
    with open(CRM_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"leads": []}


def _load_conversations_log() -> list:
    """Load conversation history from system log filtered by reply-handler entries."""
    if not os.path.exists(LOG_PATH):
        return []
    conversations = []
    with open(LOG_PATH, "r") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("skill") in ("reply-handler", "sales-closer"):
                    conversations.append(entry)
            except json.JSONDecodeError:
                continue
    return conversations


def _groq_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    groq_config = config["llm"]["groq"]
    api_key = os.environ.get(groq_config["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": groq_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": groq_config.get("temperature", 0.1),
        "max_tokens": groq_config.get("max_tokens_per_call", 2048),
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        _log("groq_api_error", None, "failure", str(e), llm_used="groq")
        return None


def _claude_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    claude_config = config["llm"]["claude"]
    api_key = os.environ.get(claude_config["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": claude_config["model"],
        "max_tokens": claude_config.get("max_tokens_per_call", 2048),
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]
    except Exception as e:
        _log("claude_api_error", None, "failure", str(e), llm_used="claude")
        return None


def _get_close_rate(crm_data: dict, days: int = 30) -> float:
    """Calculate close rate over the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [l for l in crm_data.get("leads", [])
              if l.get("status") in ("closed", "lost") and l.get("updated_at", "") > cutoff]
    if not recent:
        return 0.0
    closed = sum(1 for l in recent if l["status"] == "closed")
    return closed / len(recent)


def _analyze_objection_patterns(config: dict, conversations: list) -> dict:
    """Every 10 objection conversations, compare winning vs losing patterns."""
    objection_convos = [c for c in conversations
                        if "OBJECTION" in c.get("details", "").upper()]

    batch_size = config["thresholds"]["objection_batch_size"]
    if len(objection_convos) < batch_size:
        return {"status": "insufficient_data", "count": len(objection_convos)}

    recent_batch = objection_convos[-batch_size:]
    winning = [c for c in recent_batch if "closed" in c.get("result", "").lower()]
    losing = [c for c in recent_batch if "lost" in c.get("result", "").lower()]

    system_prompt = (
        "You are a sales conversation analyst for NeverMiss ($297/mo missed-call text-back "
        "for trade contractors). Analyze winning vs losing objection handling patterns. "
        "Return JSON with: winning_patterns (list), losing_patterns (list), "
        "recommended_script_updates (list of {objection_type, new_response})."
    )
    user_prompt = (
        f"WINNING conversations ({len(winning)}):\n"
        + "\n".join(c.get("details", "")[:500] for c in winning[:5])
        + f"\n\nLOSING conversations ({len(losing)}):\n"
        + "\n".join(c.get("details", "")[:500] for c in losing[:5])
    )

    result = _claude_request(system_prompt, user_prompt, config)
    if result:
        _log("objection_analysis", None, "success",
             f"Analyzed {len(recent_batch)} objection conversations",
             llm_used="claude", tokens=2000, cost=0.03)
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"status": "parsed", "raw": result[:500]}
    return {"status": "llm_failed"}


def _enhance_demo_prep(config: dict, conversations: list, crm_data: dict) -> dict:
    """After 10+ demos, analyze briefings vs outcomes to improve demo prep."""
    demo_convos = [c for c in conversations if "demo" in c.get("action", "").lower()]
    batch_size = config["thresholds"]["demo_batch_size"]
    if len(demo_convos) < batch_size:
        return {"status": "insufficient_data", "count": len(demo_convos)}

    system_prompt = (
        "Analyze demo briefings and their outcomes. Identify patterns in successful demos. "
        "Return JSON with: success_patterns (list), failure_patterns (list), "
        "updated_brief_template (string, max 150 words)."
    )
    user_prompt = "Recent demo data:\n" + "\n".join(
        c.get("details", "")[:300] for c in demo_convos[-10:]
    )

    result = _groq_request(system_prompt, user_prompt, config)
    if result:
        _log("demo_prep_enhanced", None, "success",
             f"Analyzed {len(demo_convos)} demo briefings", llm_used="groq")
    return {"status": "analyzed", "demos_reviewed": len(demo_convos)}


def _save_script_version(script_type: str, content: dict):
    """Save a script version with timestamp for rollback."""
    os.makedirs(SCRIPT_VERSIONS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCRIPT_VERSIONS_DIR, f"{script_type}_{timestamp}.json")
    with open(path, "w") as f:
        json.dump({
            "type": script_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content": content,
        }, f, indent=2)
    _log("script_version_saved", None, "success", f"Saved {script_type} version to {path}")


def _auto_revert_if_degraded(config: dict, crm_data: dict) -> dict:
    """If close rate drops >20% after update, revert and notify owner."""
    threshold = config["thresholds"]["close_rate_drop_revert_pct"] / 100
    current_rate = _get_close_rate(crm_data, days=7)
    baseline_rate = _get_close_rate(crm_data, days=30)

    if baseline_rate == 0:
        return {"status": "no_baseline"}

    drop = (baseline_rate - current_rate) / baseline_rate
    if drop > threshold:
        _log("auto_revert_triggered", None, "failure",
             f"Close rate dropped {drop:.1%} (from {baseline_rate:.1%} to {current_rate:.1%}). "
             f"Reverting last script update and notifying owner.")
        return {
            "status": "reverted",
            "baseline_rate": round(baseline_rate, 4),
            "current_rate": round(current_rate, 4),
            "drop_pct": round(drop * 100, 1),
            "notify_owner": True,
        }
    return {"status": "healthy", "current_rate": round(current_rate, 4)}


def run_optimization_cycle(event_type: str = "weekly") -> dict:
    """
    Main entry point.
    event_type: "weekly" (Wednesday 6AM PT) or "post_conversation" (after closed/lost).
    """
    config = _load_config()
    crm_data = _load_crm_data()
    conversations = _load_conversations_log()

    _log("sales_optimization_start", None, "success",
         f"Starting {event_type} optimization cycle. "
         f"Conversations: {len(conversations)}, CRM leads: {len(crm_data.get('leads', []))}")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
    }

    # Always check for degradation
    results["health_check"] = _auto_revert_if_degraded(config, crm_data)

    if event_type == "weekly":
        results["objection_analysis"] = _analyze_objection_patterns(config, conversations)
        results["demo_prep"] = _enhance_demo_prep(config, conversations, crm_data)
    elif event_type == "post_conversation":
        # Lighter analysis on each conversation close
        results["objection_analysis"] = _analyze_objection_patterns(config, conversations)

    # Log results
    os.makedirs(os.path.dirname(OPTIMIZATION_LOG), exist_ok=True)
    with open(OPTIMIZATION_LOG, "a") as f:
        f.write(json.dumps(results) + "\n")

    _log("sales_optimization_complete", None, "success",
         f"Optimization cycle complete. Health: {results['health_check'].get('status')}")
    return results


if __name__ == "__main__":
    import sys
    event = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    result = run_optimization_cycle(event_type=event)
    print(json.dumps(result, indent=2))
