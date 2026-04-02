#!/usr/bin/env python3
"""
performance-engine: Tracks system metrics, runs A/B variant analysis with
statistical significance testing, optimizes email variants, and generates
weekly performance reports.

Entry points:
  --weekly-report      Generate the full weekly performance report (Sundays 8PM PT)
  --variant-analysis   Run variant significance tests (triggered at 100-email milestones)
  --metrics-summary    Print current metrics snapshot to stdout
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
with open(CONFIG_PATH, "r") as _f:
    CONFIG = json.load(_f)

DATA_PATHS = {k: PROJECT_ROOT / v for k, v in CONFIG["data_paths"].items()}
LOG_PATH = PROJECT_ROOT / CONFIG["logging"]["log_file"]
TARGETS = CONFIG["targets"]
AB_CONFIG = CONFIG["ab_testing"]
REVENUE_CONFIG = CONFIG["revenue"]
LLM_CONFIG = CONFIG["llm"]
REPORT_CONFIG = CONFIG["report"]

# ---------------------------------------------------------------------------
# Logger (console)
# ---------------------------------------------------------------------------
logger = logging.getLogger("performance-engine")
logger.setLevel(getattr(logging, CONFIG["logging"]["log_level"], logging.INFO))
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
    logger.addHandler(_handler)


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
        "skill": "performance-engine",
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


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, returning list of dicts. Empty list if missing."""
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing."""
    if not path.exists():
        return {}
    with open(path, "r") as fh:
        return json.load(fh)


def _save_json(path: Path, data: Any) -> None:
    """Write JSON data to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# Variant performance file (shared with email-optimizer)
# ---------------------------------------------------------------------------
VARIANT_PERF_PATH = PROJECT_ROOT / "skills" / "email-optimizer" / "variant_performance.json"


def _load_variant_performance() -> dict:
    return _load_json(VARIANT_PERF_PATH)


# ---------------------------------------------------------------------------
# Z-test for proportions (manual — no scipy dependency)
# ---------------------------------------------------------------------------
def _z_test(
    successes_a: int,
    trials_a: int,
    successes_b: int,
    trials_b: int,
) -> dict:
    """
    Two-proportion z-test comparing variant A vs variant B.

    Returns dict with z_statistic, p_value (two-tailed approx), significant (bool),
    and winner ("A", "B", or "none").
    """
    if trials_a == 0 or trials_b == 0:
        return {
            "z_statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "winner": "none",
            "p_a": 0.0,
            "p_b": 0.0,
        }

    p_a = successes_a / trials_a
    p_b = successes_b / trials_b

    # Pooled proportion
    p_pool = (successes_a + successes_b) / (trials_a + trials_b)

    # Standard error
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / trials_a + 1 / trials_b))
    if se == 0:
        return {
            "z_statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "winner": "none",
            "p_a": p_a,
            "p_b": p_b,
        }

    z = (p_a - p_b) / se

    # Approximate two-tailed p-value using the error function
    # P(Z > |z|) * 2 via the complementary error function
    p_value = math.erfc(abs(z) / math.sqrt(2))

    significant = abs(z) >= AB_CONFIG["z_critical"]
    winner = "none"
    if significant:
        winner = "A" if z > 0 else "B"

    return {
        "z_statistic": round(z, 4),
        "p_value": round(p_value, 6),
        "significant": significant,
        "winner": winner,
        "p_a": round(p_a, 4),
        "p_b": round(p_b, 4),
    }


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------
def _calculate_variant_metrics() -> dict:
    """
    Read outreach/reply/system logs and compute per-variant stats:
      open_rate, reply_rate, positive_reply_rate, bounce_rate, qa_rejection_rate.
    """
    outreach_logs = _load_jsonl(DATA_PATHS["outreach_log"])
    reply_logs = _load_jsonl(DATA_PATHS["replies_log"])
    system_logs = _load_jsonl(DATA_PATHS["system_log"])

    # Also read variant_performance.json from email-optimizer as authoritative source
    variant_perf = _load_variant_performance()
    variant_data = variant_perf.get("variants", {})

    # Build counters from logs
    variants: dict[str, dict] = {}
    for v_name in variant_data:
        variants[v_name] = {
            "sent": 0,
            "opened": 0,
            "replied": 0,
            "positive_replies": 0,
            "bounced": 0,
            "qa_rejected": 0,
        }

    # Count sends per variant from outreach log
    for entry in outreach_logs:
        v = entry.get("variant")
        if v and v in variants:
            variants[v]["sent"] += 1
            if entry.get("opened"):
                variants[v]["opened"] += 1
            if entry.get("bounced"):
                variants[v]["bounced"] += 1

    # Count replies from replies log
    for entry in reply_logs:
        v = entry.get("variant")
        if v and v in variants:
            variants[v]["replied"] += 1
            sentiment = entry.get("sentiment", "").lower()
            if sentiment in ("positive", "interested"):
                variants[v]["positive_replies"] += 1

    # Count QA rejections from system log
    for entry in system_logs:
        if entry.get("skill") == "qa-guard" and entry.get("result") == "rejected":
            v = entry.get("details", "")
            # Try to extract variant from details field
            for v_name in variants:
                if f"variant={v_name}" in v or f"variant {v_name}" in v.lower():
                    variants[v_name]["qa_rejected"] += 1
                    break

    # Calculate rates
    metrics: dict[str, dict] = {}
    for v_name, counts in variants.items():
        sent = counts["sent"]
        metrics[v_name] = {
            "total_sent": sent,
            "total_opened": counts["opened"],
            "total_replied": counts["replied"],
            "total_positive_replies": counts["positive_replies"],
            "total_bounced": counts["bounced"],
            "total_qa_rejected": counts["qa_rejected"],
            "open_rate_pct": round((counts["opened"] / sent * 100) if sent > 0 else 0.0, 2),
            "reply_rate_pct": round((counts["replied"] / sent * 100) if sent > 0 else 0.0, 2),
            "positive_reply_rate_pct": round(
                (counts["positive_replies"] / sent * 100) if sent > 0 else 0.0, 2
            ),
            "bounce_rate_pct": round((counts["bounced"] / sent * 100) if sent > 0 else 0.0, 2),
            "qa_rejection_rate_pct": round(
                (counts["qa_rejected"] / max(counts["qa_rejected"] + sent, 1) * 100), 2
            ),
            "status": variant_data.get(v_name, {}).get("status", "unknown"),
        }

    return metrics


def _calculate_pipeline_metrics() -> dict:
    """
    Read CRM data and compute stage conversion rates and average days per stage.
    Stages: lead -> contacted -> replied -> qualified -> booked -> demo_completed -> closed
    """
    crm = _load_json(DATA_PATHS["crm"])
    leads = crm.get("leads", {})

    stage_order = [
        "new", "contacted", "replied", "qualified",
        "booked", "demo_completed", "closed",
    ]

    # Count leads per stage
    stage_counts: dict[str, int] = {s: 0 for s in stage_order}
    stage_days: dict[str, list[float]] = {s: [] for s in stage_order}

    for lead_id, lead in leads.items():
        current = lead.get("status", "new")
        if current in stage_counts:
            stage_counts[current] += 1

        # Also count all leads that have passed through each stage
        history = lead.get("status_history", [])
        stages_seen = set()
        prev_ts = None
        for h_entry in history:
            stage = h_entry.get("status") or h_entry.get("stage")
            ts_str = h_entry.get("timestamp") or h_entry.get("date")
            if stage and stage in stage_counts:
                stages_seen.add(stage)
                if prev_ts and ts_str:
                    try:
                        t_prev = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                        t_curr = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        delta_days = (t_curr - t_prev).total_seconds() / 86400
                        if delta_days >= 0:
                            stage_days[stage].append(delta_days)
                    except (ValueError, TypeError):
                        pass
                prev_ts = ts_str

    # Conversion rates between consecutive stages
    conversions: dict[str, float] = {}
    for i in range(len(stage_order) - 1):
        from_stage = stage_order[i]
        to_stage = stage_order[i + 1]
        from_count = stage_counts.get(from_stage, 0)
        to_count = stage_counts.get(to_stage, 0)
        key = f"{from_stage}_to_{to_stage}"
        conversions[key] = round((to_count / from_count * 100) if from_count > 0 else 0.0, 2)

    # Average days per stage
    avg_days: dict[str, float] = {}
    for stage, days_list in stage_days.items():
        avg_days[stage] = round(sum(days_list) / len(days_list), 1) if days_list else 0.0

    # Total leads
    total_leads = len(leads)

    return {
        "total_leads": total_leads,
        "leads_by_stage": stage_counts,
        "conversion_rates": conversions,
        "avg_days_per_stage": avg_days,
        "targets": {
            "contacted_to_replied_pct": TARGETS["contacted_to_replied_pct"],
            "replied_to_qualified_pct": TARGETS["replied_to_qualified_pct"],
            "qualified_to_booked_pct": TARGETS["qualified_to_booked_pct"],
            "booked_to_closed_pct": TARGETS["booked_to_closed_pct"],
        },
    }


def _calculate_revenue_metrics() -> dict:
    """
    Compute MRR, CAC, and revenue-per-lead from CRM closed deals.
    """
    crm = _load_json(DATA_PATHS["crm"])
    leads = crm.get("leads", {})

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_mrr = 0.0
    weekly_mrr = 0.0
    monthly_mrr = 0.0
    closed_count = 0
    total_cost = 0.0

    for lead_id, lead in leads.items():
        status = lead.get("status", "")
        if status not in ("closed", "onboarding"):
            continue

        mrr = lead.get("mrr", REVENUE_CONFIG["default_mrr_per_deal"])
        total_mrr += mrr
        closed_count += 1

        # Determine close date from history
        close_date = None
        history = lead.get("status_history", [])
        for h in history:
            h_status = h.get("status") or h.get("stage")
            if h_status == "closed":
                ts_str = h.get("timestamp") or h.get("date")
                if ts_str:
                    try:
                        close_date = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass
                break

        if close_date:
            if close_date >= week_ago:
                weekly_mrr += mrr
            if close_date >= month_ago:
                monthly_mrr += mrr

        # Accumulate acquisition cost if tracked
        total_cost += lead.get("acquisition_cost", 0.0)

    total_leads = len(leads)
    cac = round(total_cost / closed_count, 2) if closed_count > 0 else 0.0
    revenue_per_lead = round(total_mrr / total_leads, 2) if total_leads > 0 else 0.0

    return {
        "total_mrr": round(total_mrr, 2),
        "weekly_new_mrr": round(weekly_mrr, 2),
        "monthly_new_mrr": round(monthly_mrr, 2),
        "closed_deals": closed_count,
        "cac": cac,
        "revenue_per_lead": revenue_per_lead,
        "default_mrr_per_deal": REVENUE_CONFIG["default_mrr_per_deal"],
    }


# ---------------------------------------------------------------------------
# Milestone trigger check
# ---------------------------------------------------------------------------
def _check_milestone_triggers() -> list[str]:
    """
    Check if any variant has crossed a 100-email increment since last check.
    Returns list of variant names that hit a milestone.
    """
    variant_metrics = _calculate_variant_metrics()
    perf_path = DATA_PATHS["performance_metrics"]
    perf_data = _load_json(perf_path)
    last_milestones = perf_data.get("last_milestones", {})

    triggered: list[str] = []

    for v_name, m in variant_metrics.items():
        sent = m["total_sent"]
        milestone = AB_CONFIG["min_emails_per_variant"]
        last = last_milestones.get(v_name, 0)

        # Current milestone bucket: floor(sent / 100) * 100
        current_bucket = (sent // milestone) * milestone
        if current_bucket > last and current_bucket >= milestone:
            triggered.append(v_name)
            last_milestones[v_name] = current_bucket

    # Persist updated milestones
    perf_data["last_milestones"] = last_milestones
    _save_json(perf_path, perf_data)

    return triggered


# ---------------------------------------------------------------------------
# Groq / Llama narrative generation
# ---------------------------------------------------------------------------
def _generate_report_narrative(metrics: dict) -> str:
    """
    Call Groq API with Llama 3.1 70B to generate a concise narrative summary
    of the weekly metrics. Falls back to a template summary on failure.
    """
    api_key = os.environ.get(LLM_CONFIG["api_key_env"], "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set; falling back to template narrative.")
        return _template_narrative(metrics)

    prompt = _build_narrative_prompt(metrics)

    try:
        import httpx
    except ImportError:
        try:
            import urllib.request
            return _groq_call_urllib(api_key, prompt)
        except Exception as e:
            logger.error("Narrative generation failed (urllib): %s", e)
            return _template_narrative(metrics)

    try:
        payload = {
            "model": LLM_CONFIG["model"],
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise business analyst. Summarize the weekly "
                        "performance metrics for a B2B cold-outreach system targeting "
                        "home-services businesses. Highlight wins, concerns, and "
                        "one actionable recommendation. Keep it under 300 words."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": LLM_CONFIG["temperature"],
            "max_tokens": 600,
        }

        with httpx.Client(timeout=LLM_CONFIG["timeout_seconds"]) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        narrative = data["choices"][0]["message"]["content"].strip()
        _log_event(
            action="generate_narrative",
            result="success",
            details=f"tokens={data.get('usage', {}).get('total_tokens', 0)}",
            llm_used=LLM_CONFIG["model"],
            tokens_estimated=data.get("usage", {}).get("total_tokens", 0),
        )
        return narrative

    except Exception as e:
        logger.error("Groq narrative generation failed: %s", e)
        _log_event(action="generate_narrative", result="error", details=str(e))
        return _template_narrative(metrics)


def _groq_call_urllib(api_key: str, prompt: str) -> str:
    """Fallback Groq call using stdlib urllib (no httpx)."""
    import urllib.request

    payload = json.dumps({
        "model": LLM_CONFIG["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a concise business analyst. Summarize the weekly "
                    "performance metrics for a B2B cold-outreach system targeting "
                    "home-services businesses. Highlight wins, concerns, and "
                    "one actionable recommendation. Keep it under 300 words."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": LLM_CONFIG["temperature"],
        "max_tokens": 600,
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

    with urllib.request.urlopen(req, timeout=LLM_CONFIG["timeout_seconds"]) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    narrative = data["choices"][0]["message"]["content"].strip()
    _log_event(
        action="generate_narrative",
        result="success",
        details=f"tokens={data.get('usage', {}).get('total_tokens', 0)} (urllib)",
        llm_used=LLM_CONFIG["model"],
        tokens_estimated=data.get("usage", {}).get("total_tokens", 0),
    )
    return narrative


def _build_narrative_prompt(metrics: dict) -> str:
    """Build the user-prompt payload for Groq from collected metrics."""
    sections = []

    # Variant metrics
    vm = metrics.get("variant_metrics", {})
    if vm:
        lines = ["## Variant Performance"]
        for v_name, v_data in sorted(vm.items()):
            lines.append(
                f"  {v_name}: sent={v_data['total_sent']}  "
                f"open={v_data['open_rate_pct']}%  reply={v_data['reply_rate_pct']}%  "
                f"positive_reply={v_data['positive_reply_rate_pct']}%  "
                f"bounce={v_data['bounce_rate_pct']}%  "
                f"qa_reject={v_data['qa_rejection_rate_pct']}%"
            )
        sections.append("\n".join(lines))

    # Pipeline
    pm = metrics.get("pipeline_metrics", {})
    if pm:
        lines = [
            "## Pipeline",
            f"  Total leads: {pm.get('total_leads', 0)}",
        ]
        for k, v in pm.get("conversion_rates", {}).items():
            lines.append(f"  {k}: {v}%")
        sections.append("\n".join(lines))

    # Revenue
    rm = metrics.get("revenue_metrics", {})
    if rm:
        lines = [
            "## Revenue",
            f"  Total MRR: ${rm.get('total_mrr', 0)}",
            f"  Weekly new MRR: ${rm.get('weekly_new_mrr', 0)}",
            f"  Monthly new MRR: ${rm.get('monthly_new_mrr', 0)}",
            f"  Closed deals: {rm.get('closed_deals', 0)}",
            f"  CAC: ${rm.get('cac', 0)}",
        ]
        sections.append("\n".join(lines))

    # Targets
    sections.append(
        "## Targets\n"
        f"  Reply rate target: {TARGETS['reply_rate_pct']}%\n"
        f"  Positive reply target: {TARGETS['positive_reply_rate_pct']}%\n"
        f"  Max bounce: {TARGETS['bounce_rate_max_pct']}%\n"
        f"  Open rate target: {TARGETS['open_rate_pct']}%"
    )

    return "\n\n".join(sections)


def _template_narrative(metrics: dict) -> str:
    """Fallback template-based narrative when Groq is unavailable."""
    vm = metrics.get("variant_metrics", {})
    pm = metrics.get("pipeline_metrics", {})
    rm = metrics.get("revenue_metrics", {})

    parts = ["Weekly Performance Report (auto-generated template)\n"]

    # Variant summary
    if vm:
        parts.append("VARIANT PERFORMANCE:")
        for v_name, v_data in sorted(vm.items()):
            flag = ""
            if v_data["reply_rate_pct"] < TARGETS["reply_rate_pct"]:
                flag = " [BELOW TARGET]"
            if v_data["bounce_rate_pct"] > TARGETS["bounce_rate_max_pct"]:
                flag += " [HIGH BOUNCE]"
            parts.append(
                f"  Variant {v_name}: {v_data['total_sent']} sent, "
                f"{v_data['open_rate_pct']}% open, {v_data['reply_rate_pct']}% reply, "
                f"{v_data['bounce_rate_pct']}% bounce{flag}"
            )

    # Pipeline summary
    if pm:
        parts.append(f"\nPIPELINE: {pm.get('total_leads', 0)} total leads")
        for k, v in pm.get("conversion_rates", {}).items():
            parts.append(f"  {k}: {v}%")

    # Revenue summary
    if rm:
        parts.append(
            f"\nREVENUE: ${rm.get('total_mrr', 0)} total MRR | "
            f"${rm.get('weekly_new_mrr', 0)} new this week | "
            f"CAC ${rm.get('cac', 0)}"
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# WhatsApp / OpenClaw notification delivery
# ---------------------------------------------------------------------------
def _send_report_notification(report_text: str) -> None:
    """
    Deliver the report via the configured method (openclaw_message).
    Logs the delivery attempt.
    """
    delivery = REPORT_CONFIG.get("delivery_method", "openclaw_message")

    _log_event(
        action="send_report",
        result="dispatched",
        details=f"method={delivery} length={len(report_text)}",
    )

    # The actual delivery is handled by the openclaw harness which reads
    # the log event and routes it to the owner's WhatsApp/notification channel.
    # We write the report to a well-known location for the harness to pick up.
    report_path = PROJECT_ROOT / "data" / "weekly_report_latest.json"
    _save_json(report_path, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "delivery_method": delivery,
        "report": report_text,
    })

    logger.info("Report saved to %s for delivery via %s", report_path, delivery)


# ---------------------------------------------------------------------------
# Core entry: weekly report
# ---------------------------------------------------------------------------
def run_weekly_report() -> dict:
    """
    Main weekly report flow (Sundays 8PM PT):
      1. Collect variant metrics from logs
      2. Collect pipeline metrics from CRM
      3. Collect revenue metrics from closed deals
      4. Generate narrative via Groq/Llama
      5. Send report via notification
    Returns the full metrics dict.
    """
    _log_event(action="weekly_report", result="started", details="Collecting metrics")

    # 1. Variant metrics
    variant_metrics = _calculate_variant_metrics()

    # 2. Pipeline metrics
    pipeline_metrics = _calculate_pipeline_metrics()

    # 3. Revenue metrics
    revenue_metrics = _calculate_revenue_metrics()

    # Assemble
    metrics = {
        "report_date": datetime.now(timezone.utc).isoformat(),
        "variant_metrics": variant_metrics,
        "pipeline_metrics": pipeline_metrics,
        "revenue_metrics": revenue_metrics,
    }

    # Flag any variants against targets
    alerts: list[str] = []
    for v_name, vm in variant_metrics.items():
        if vm["total_sent"] > 0:
            if vm["reply_rate_pct"] < TARGETS["reply_rate_pct"]:
                alerts.append(f"Variant {v_name} reply rate {vm['reply_rate_pct']}% below target {TARGETS['reply_rate_pct']}%")
            if vm["bounce_rate_pct"] > TARGETS["bounce_rate_max_pct"]:
                alerts.append(f"Variant {v_name} bounce rate {vm['bounce_rate_pct']}% exceeds max {TARGETS['bounce_rate_max_pct']}%")
            if vm["open_rate_pct"] < TARGETS["open_rate_pct"]:
                alerts.append(f"Variant {v_name} open rate {vm['open_rate_pct']}% below target {TARGETS['open_rate_pct']}%")
    metrics["alerts"] = alerts

    # 4. Narrative
    narrative = _generate_report_narrative(metrics)
    metrics["narrative"] = narrative

    # 5. Persist full metrics snapshot
    _save_json(DATA_PATHS["performance_metrics"], metrics)

    # 6. Send notification
    report_text = narrative
    if REPORT_CONFIG.get("include_recommendations") and alerts:
        report_text += "\n\nALERTS:\n" + "\n".join(f"  - {a}" for a in alerts)
    _send_report_notification(report_text)

    _log_event(
        action="weekly_report",
        result="completed",
        details=f"variants={len(variant_metrics)} alerts={len(alerts)}",
    )

    return metrics


# ---------------------------------------------------------------------------
# Core entry: variant analysis (A/B significance testing)
# ---------------------------------------------------------------------------
def run_variant_analysis() -> dict:
    """
    Triggered at every 100-email milestone per variant.
      - z-test at 95% confidence comparing each pair of active variants
      - Flag underperformers for replacement (staged for owner approval)
      - Log statistical results
    Returns analysis results dict.
    """
    _log_event(action="variant_analysis", result="started", details="Running significance tests")

    variant_metrics = _calculate_variant_metrics()
    active_variants = [
        (name, m) for name, m in variant_metrics.items()
        if m.get("status") == "active" and m["total_sent"] >= AB_CONFIG["min_emails_per_variant"]
    ]

    if len(active_variants) < 2:
        _log_event(
            action="variant_analysis",
            result="skipped",
            details=f"Need >= 2 active variants with >= {AB_CONFIG['min_emails_per_variant']} sends; have {len(active_variants)}",
        )
        return {"status": "skipped", "reason": "insufficient_variants", "comparisons": []}

    comparisons: list[dict] = []
    underperformers: list[str] = []

    # Compare all pairs on reply_rate
    for i in range(len(active_variants)):
        for j in range(i + 1, len(active_variants)):
            name_a, m_a = active_variants[i]
            name_b, m_b = active_variants[j]

            result = _z_test(
                successes_a=m_a["total_replied"],
                trials_a=m_a["total_sent"],
                successes_b=m_b["total_replied"],
                trials_b=m_b["total_sent"],
            )

            comparison = {
                "variant_a": name_a,
                "variant_b": name_b,
                "metric": "reply_rate",
                "p_a": result["p_a"],
                "p_b": result["p_b"],
                "z_statistic": result["z_statistic"],
                "p_value": result["p_value"],
                "significant": result["significant"],
                "winner": result["winner"],
            }
            comparisons.append(comparison)

            # Determine the actual winner/loser variant name
            if result["significant"]:
                winner_name = name_a if result["winner"] == "A" else name_b
                loser_name = name_b if result["winner"] == "A" else name_a
                loser_rate = result["p_b"] if result["winner"] == "A" else result["p_a"]
                winner_rate = result["p_a"] if result["winner"] == "A" else result["p_b"]

                # Check underperformance threshold
                if winner_rate > 0:
                    ratio = winner_rate / max(loser_rate, 0.0001)
                    if ratio >= AB_CONFIG["underperformance_threshold_multiplier"]:
                        underperformers.append(loser_name)

                _log_event(
                    action="variant_significance",
                    result="significant",
                    details=(
                        f"{winner_name} beats {loser_name}: "
                        f"z={result['z_statistic']} p={result['p_value']}"
                    ),
                )

    # Deduplicate underperformers
    underperformers = list(set(underperformers))

    # Flag underperformers for replacement (requires owner approval)
    flagged: list[dict] = []
    for v_name in underperformers:
        flag_entry = {
            "variant": v_name,
            "reason": "statistically_underperforming",
            "action": "replacement_staged",
            "requires_approval": AB_CONFIG["require_owner_approval"],
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        }
        flagged.append(flag_entry)
        _log_event(
            action="flag_underperformer",
            result="flagged",
            details=f"variant={v_name} staged for replacement (owner approval required)",
        )

    analysis = {
        "status": "completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "comparisons": comparisons,
        "underperformers": underperformers,
        "flagged_for_replacement": flagged,
    }

    # Persist analysis results
    perf_data = _load_json(DATA_PATHS["performance_metrics"])
    perf_data["latest_variant_analysis"] = analysis
    _save_json(DATA_PATHS["performance_metrics"], perf_data)

    _log_event(
        action="variant_analysis",
        result="completed",
        details=f"comparisons={len(comparisons)} underperformers={len(underperformers)}",
    )

    return analysis


# ---------------------------------------------------------------------------
# Metrics summary (quick stdout dump)
# ---------------------------------------------------------------------------
def run_metrics_summary() -> dict:
    """Print a quick metrics snapshot to stdout."""
    variant_metrics = _calculate_variant_metrics()
    pipeline_metrics = _calculate_pipeline_metrics()
    revenue_metrics = _calculate_revenue_metrics()

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "variant_metrics": variant_metrics,
        "pipeline_metrics": pipeline_metrics,
        "revenue_metrics": revenue_metrics,
    }

    print(json.dumps(summary, indent=2, default=str))
    return summary


# ---------------------------------------------------------------------------
# Event-driven: check milestones and trigger analysis if needed
# ---------------------------------------------------------------------------
def check_and_run_milestones() -> None:
    """
    Called on outreach/reply/status-change events. Checks if any variant
    crossed a 100-email milestone and triggers variant analysis if so.
    """
    triggered = _check_milestone_triggers()
    if triggered:
        logger.info("Milestone triggered for variants: %s", ", ".join(triggered))
        _log_event(
            action="milestone_trigger",
            result="triggered",
            details=f"variants={','.join(triggered)}",
        )
        run_variant_analysis()
    else:
        logger.debug("No milestone triggers.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Performance Engine — metrics, A/B testing, weekly reports"
    )
    parser.add_argument(
        "--weekly-report",
        action="store_true",
        help="Generate the full weekly performance report",
    )
    parser.add_argument(
        "--variant-analysis",
        action="store_true",
        help="Run variant significance tests",
    )
    parser.add_argument(
        "--metrics-summary",
        action="store_true",
        help="Print current metrics snapshot to stdout",
    )
    parser.add_argument(
        "--check-milestones",
        action="store_true",
        help="Check for 100-email milestones and trigger analysis if needed",
    )

    args = parser.parse_args()

    if args.weekly_report:
        result = run_weekly_report()
        logger.info("Weekly report complete. Alerts: %d", len(result.get("alerts", [])))
    elif args.variant_analysis:
        result = run_variant_analysis()
        logger.info("Variant analysis: %s", result.get("status", "unknown"))
    elif args.metrics_summary:
        run_metrics_summary()
    elif args.check_milestones:
        check_and_run_milestones()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
