#!/usr/bin/env python3
"""
Email Optimizer — Self-Optimizing Email System
Autonomously retires underperforming variants, adjusts send times,
tunes follow-up cadence, evolves subject lines, matches variants to verticals,
and reallocates geographic sourcing.

LLM: Groq/Llama for bulk variant generation. Claude Sonnet only when variant
crosses 5% reply rate ($5/week cap).
"""

import json
import math
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
SEND_LOG_PATH = os.path.join(PROJECT_ROOT, "data", "outreach_send_log.json")
OPTIMIZATION_LOG = os.path.join(PROJECT_ROOT, "data", "optimization", "email_optimization_log.jsonl")
VARIANT_HISTORY_PATH = os.path.join(PROJECT_ROOT, "data", "optimization", "variant_history.json")


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "email-optimizer",
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


def _load_send_log() -> list:
    if not os.path.exists(SEND_LOG_PATH):
        return []
    with open(SEND_LOG_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _load_variant_history() -> dict:
    if not os.path.exists(VARIANT_HISTORY_PATH):
        return {"variants": {}, "retired": [], "claude_spend_this_week": 0.0}
    with open(VARIANT_HISTORY_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"variants": {}, "retired": [], "claude_spend_this_week": 0.0}


def _save_variant_history(history: dict):
    os.makedirs(os.path.dirname(VARIANT_HISTORY_PATH), exist_ok=True)
    with open(VARIANT_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _groq_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    """Make a Groq/Llama API call for variant generation."""
    bulk_config = config["llm"]["bulk"]
    api_key = os.environ.get(bulk_config["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": bulk_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": bulk_config.get("temperature", 0.8),
        "max_tokens": 1024,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=bulk_config.get("timeout_seconds", 30)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        _log("groq_api_error", None, "failure", str(e), llm_used="groq")
        return None


def _claude_request(system_prompt: str, user_prompt: str, config: dict) -> Optional[str]:
    """Make a Claude Sonnet API call for high-value variant analysis."""
    closer_config = config["llm"]["closer"]
    api_key = os.environ.get(closer_config["api_key_env"], "")
    if not api_key:
        return None
    payload = json.dumps({
        "model": closer_config["model"],
        "max_tokens": 1024,
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
        with urllib.request.urlopen(req, timeout=closer_config.get("timeout_seconds", 60)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]
    except Exception as e:
        _log("claude_api_error", None, "failure", str(e), llm_used="claude")
        return None


def _chi_squared_test(success_a: int, total_a: int, success_b: int, total_b: int) -> float:
    """
    Chi-squared test for two proportions. Returns p-value approximation.
    Used to determine if variant performance difference is statistically significant.
    """
    if total_a == 0 or total_b == 0:
        return 1.0
    p_a = success_a / total_a
    p_b = success_b / total_b
    p_pool = (success_a + success_b) / (total_a + total_b)
    if p_pool == 0 or p_pool == 1:
        return 1.0
    q_pool = 1 - p_pool
    se = math.sqrt(p_pool * q_pool * (1 / total_a + 1 / total_b))
    if se == 0:
        return 1.0
    z = abs(p_a - p_b) / se
    # Approximate p-value from z-score using normal CDF approximation
    p_value = math.erfc(z / math.sqrt(2))
    return p_value


def _calculate_variant_metrics(send_log: list) -> dict:
    """Calculate per-variant metrics from send log."""
    metrics = {}
    for entry in send_log:
        variant = entry.get("variant", "unknown")
        if variant not in metrics:
            metrics[variant] = {
                "sent": 0, "opened": 0, "replied": 0, "positive_replies": 0,
                "bounced": 0, "qa_rejected": 0, "reply_hours": [],
            }
        m = metrics[variant]
        m["sent"] += 1
        if entry.get("opened"):
            m["opened"] += 1
        if entry.get("replied"):
            m["replied"] += 1
            if entry.get("reply_sentiment") == "positive":
                m["positive_replies"] += 1
            if entry.get("reply_hour") is not None:
                m["reply_hours"].append(entry["reply_hour"])
        if entry.get("bounced"):
            m["bounced"] += 1
        if entry.get("qa_rejected"):
            m["qa_rejected"] += 1

    for variant, m in metrics.items():
        m["open_rate"] = m["opened"] / m["sent"] if m["sent"] > 0 else 0
        m["reply_rate"] = m["replied"] / m["sent"] if m["sent"] > 0 else 0
        m["positive_reply_rate"] = m["positive_replies"] / m["sent"] if m["sent"] > 0 else 0
        m["bounce_rate"] = m["bounced"] / m["sent"] if m["sent"] > 0 else 0
    return metrics


def _check_variant_performance(config: dict, send_log: list, history: dict) -> list:
    """
    Evaluate variants. Retire underperformers (reply rate <50% of top, chi-squared p<0.05).
    Returns list of actions taken.
    """
    vr_config = config["variant_replacement"]
    min_emails = vr_config["min_emails_for_evaluation"]
    underperf_ratio = vr_config["underperformance_ratio"]
    sig_level = vr_config["significance_level"]

    metrics = _calculate_variant_metrics(send_log)
    actions = []

    # Find top performer
    eligible = {k: v for k, v in metrics.items() if v["sent"] >= min_emails}
    if len(eligible) < 2:
        return actions

    top_variant = max(eligible, key=lambda k: eligible[k]["reply_rate"])
    top_rate = eligible[top_variant]["reply_rate"]

    for variant, m in eligible.items():
        if variant == top_variant:
            continue
        if m["reply_rate"] < top_rate * underperf_ratio:
            p_value = _chi_squared_test(
                m["replied"], m["sent"],
                eligible[top_variant]["replied"], eligible[top_variant]["sent"]
            )
            if p_value < sig_level:
                actions.append({
                    "action": "retire_variant",
                    "variant": variant,
                    "reply_rate": round(m["reply_rate"], 4),
                    "top_rate": round(top_rate, 4),
                    "p_value": round(p_value, 6),
                })
                _retire_variant(variant, m, config, history)
    return actions


def _retire_variant(variant: str, metrics: dict, config: dict, history: dict):
    """Retire an underperforming variant and generate replacement via Groq."""
    history.setdefault("retired", []).append({
        "variant": variant,
        "retired_at": datetime.now(timezone.utc).isoformat(),
        "final_reply_rate": metrics["reply_rate"],
        "total_sent": metrics["sent"],
    })

    system_prompt = (
        "You are an expert cold email copywriter for NeverMiss, a $297/mo missed-call "
        "text-back system for trade contractors (HVAC, plumbing, electrical). "
        "NEVER say 'AI', 'bot', 'automated', or 'automation'. Always say 'system' or 'tool'. "
        "Generate a new cold email variant. Return JSON with 'subject' and 'body' fields."
    )
    user_prompt = (
        f"The variant '{variant}' was retired for low reply rate ({metrics['reply_rate']:.1%}). "
        f"Generate a fresh replacement variant. Keep subject under 60 chars, body under 150 words. "
        f"Target: small contractor businesses who miss phone calls and lose jobs."
    )

    result = _groq_request(system_prompt, user_prompt, config)
    if result:
        _log("variant_replaced", None, "success",
             f"Retired '{variant}' (reply rate {metrics['reply_rate']:.1%}), generated replacement",
             llm_used="groq")
    _save_variant_history(history)


def _optimize_send_times(config: dict, send_log: list) -> dict:
    """Find optimal 3-hour send window from reply data."""
    st_config = config["send_time_optimization"]
    if len(send_log) < st_config["min_emails_for_evaluation"]:
        return {"status": "insufficient_data", "total_emails": len(send_log)}

    hour_replies = {}
    for entry in send_log:
        if entry.get("replied") and entry.get("send_hour") is not None:
            h = entry["send_hour"]
            hour_replies[h] = hour_replies.get(h, 0) + 1

    if not hour_replies:
        return {"status": "no_reply_data"}

    # Find best 3-hour window
    best_start = 8
    best_count = 0
    window_size = st_config["peak_window_hours"]
    for start_hour in range(6, 18):
        count = sum(hour_replies.get((start_hour + i) % 24, 0) for i in range(window_size))
        if count > best_count:
            best_count = count
            best_start = start_hour

    result = {
        "status": "optimized",
        "peak_window_start": best_start,
        "peak_window_end": best_start + window_size,
        "peak_weight_pct": st_config["peak_window_weight_pct"],
        "total_replies_in_window": best_count,
    }
    _log("send_time_optimized", None, "success",
         f"Peak window: {best_start}:00-{best_start + window_size}:00 "
         f"({best_count} replies, {st_config['peak_window_weight_pct']}% weight)")
    return result


def _optimize_followup_cadence(config: dict, send_log: list) -> dict:
    """Adjust follow-up timing based on reply patterns."""
    ft_config = config["follow_up_timing"]
    breakup_entries = [e for e in send_log if e.get("sequence_number") == 3]
    if len(breakup_entries) < 50:
        return {"status": "insufficient_data"}

    breakup_replies = sum(1 for e in breakup_entries if e.get("replied"))
    breakup_reply_rate = breakup_replies / len(breakup_entries) if breakup_entries else 0

    result = {"breakup_reply_rate": round(breakup_reply_rate, 4)}
    if breakup_reply_rate > ft_config["breakup_reply_rate_threshold_pct"] / 100:
        result["action"] = "add_4th_followup"
        result["max_follow_ups"] = ft_config["max_follow_ups"]
        _log("followup_cadence_updated", None, "success",
             f"Breakup email reply rate {breakup_reply_rate:.1%} > threshold, adding 4th follow-up")
    else:
        result["action"] = "no_change"
    return result


def _check_emergency_triggers(config: dict, send_log: list) -> list:
    """Check for emergency conditions (bounce rate > threshold)."""
    threshold = config["trigger"]["emergency_trigger"]["threshold_pct"] / 100
    alerts = []
    # Check bounce rate per inbox
    inbox_stats = {}
    recent = [e for e in send_log if e.get("sent_at", "") > (
        datetime.now(timezone.utc) - timedelta(days=7)).isoformat()]
    for entry in recent:
        inbox = entry.get("inbox", "default")
        if inbox not in inbox_stats:
            inbox_stats[inbox] = {"sent": 0, "bounced": 0}
        inbox_stats[inbox]["sent"] += 1
        if entry.get("bounced"):
            inbox_stats[inbox]["bounced"] += 1

    for inbox, stats in inbox_stats.items():
        if stats["sent"] > 0:
            bounce_rate = stats["bounced"] / stats["sent"]
            if bounce_rate > threshold:
                alerts.append({
                    "inbox": inbox,
                    "bounce_rate": round(bounce_rate, 4),
                    "threshold": threshold,
                    "action": "pause_inbox",
                })
                _log("emergency_bounce_alert", None, "failure",
                     f"Inbox '{inbox}' bounce rate {bounce_rate:.1%} exceeds {threshold:.1%} threshold")
    return alerts


def _rebalance_geos(config: dict, send_log: list) -> dict:
    """Reallocate geographic sourcing weights based on reply rate."""
    geo_config = config["geo_reallocation"]
    min_per_geo = geo_config["min_emails_per_geo"]

    geo_stats = {}
    for entry in send_log:
        geo = entry.get("state", "unknown")
        if geo not in geo_stats:
            geo_stats[geo] = {"sent": 0, "replied": 0}
        geo_stats[geo]["sent"] += 1
        if entry.get("replied"):
            geo_stats[geo]["replied"] += 1

    eligible = {k: v for k, v in geo_stats.items() if v["sent"] >= min_per_geo}
    if len(eligible) < 2:
        return {"status": "insufficient_data"}

    avg_reply_rate = sum(v["replied"] for v in eligible.values()) / sum(v["sent"] for v in eligible.values())
    weights = {}
    for geo, stats in eligible.items():
        reply_rate = stats["replied"] / stats["sent"] if stats["sent"] > 0 else 0
        ratio = reply_rate / avg_reply_rate if avg_reply_rate > 0 else 1.0
        weight = max(geo_config["min_weight_multiplier"],
                     min(geo_config["max_weight_multiplier"], ratio))
        weights[geo] = round(weight, 2)

    _log("geo_rebalanced", None, "success",
         f"Geo weights updated: {json.dumps(weights)}")
    return {"status": "rebalanced", "weights": weights}


def run_optimization_cycle(emergency: bool = False) -> dict:
    """
    Main entry point. Runs weekly (Mondays 5AM PT) or on emergency trigger.
    """
    config = _load_config()
    send_log = _load_send_log()
    history = _load_variant_history()

    _log("optimization_cycle_start", None, "success",
         f"Starting optimization cycle. Emergency: {emergency}. "
         f"Send log entries: {len(send_log)}")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "emergency": emergency,
        "send_log_size": len(send_log),
    }

    # Emergency check always runs
    results["emergency_alerts"] = _check_emergency_triggers(config, send_log)

    if not emergency:
        # Full optimization cycle
        results["variant_actions"] = _check_variant_performance(config, send_log, history)
        results["send_time"] = _optimize_send_times(config, send_log)
        results["followup"] = _optimize_followup_cadence(config, send_log)
        results["geo_rebalance"] = _rebalance_geos(config, send_log)

    # Log optimization results
    os.makedirs(os.path.dirname(OPTIMIZATION_LOG), exist_ok=True)
    with open(OPTIMIZATION_LOG, "a") as f:
        f.write(json.dumps(results) + "\n")

    _log("optimization_cycle_complete", None, "success",
         f"Optimization cycle complete. Actions: "
         f"variant={len(results.get('variant_actions', []))}, "
         f"alerts={len(results.get('emergency_alerts', []))}")

    return results


if __name__ == "__main__":
    import sys
    emergency = "--emergency" in sys.argv
    result = run_optimization_cycle(emergency=emergency)
    print(json.dumps(result, indent=2))
