"""
Model Router — Smart Cost Optimization
========================================
Routes tasks to the cheapest model that can handle them.
Based on the Stormy.ai playbook: weekly costs $47 → $6.

Routing Logic:
- FREE tier (Groq/Llama): Email triage, template fills, data formatting, status checks
- MID tier (Claude Sonnet): Lead research, personalization, strategy
- HIGH tier (Claude Opus): Deep analysis, contract review, complex negotiation

Usage:
    python3 router.py --status
    python3 router.py --optimize
    python3 router.py --cost-report
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get("NEVERMISS_DB", "/app/data/nevermiss.db")

# Cost per 1M tokens (approximate)
MODEL_COSTS = {
    "groq/llama": {"input": 0.00, "output": 0.00, "tier": "free"},
    "groq/llama-3.3-70b": {"input": 0.00, "output": 0.00, "tier": "free"},
    "anthropic/claude-sonnet": {"input": 3.00, "output": 15.00, "tier": "mid"},
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "tier": "mid"},
    "anthropic/claude-opus": {"input": 15.00, "output": 75.00, "tier": "high"},
    "anthropic/claude-opus-4-6": {"input": 15.00, "output": 75.00, "tier": "high"},
}

# ANTHROPIC CREDITS ARE $0. ALL TASKS → FREE TIER. NO EXCEPTIONS.
ROUTING_RULES = {
    # ALL tasks go to FREE tier — OpenRouter free models
    "email_triage": "free",
    "reply_classification": "free",
    "template_fill": "free",
    "data_format": "free",
    "status_check": "free",
    "heartbeat": "free",
    "simple_lookup": "free",
    "notification": "free",
    "log_analysis": "free",
    "lead_research": "free",
    "personalization": "free",
    "outreach_compose": "free",
    "competitor_analysis": "free",
    "strategy_decision": "free",
    "content_generation": "free",
    "report_generation": "free",
    "email_compose": "free",
    "contract_analysis": "free",
    "complex_negotiation": "free",
    "deep_research": "free",
    "far_regulation": "free",
    "legal_review": "free",
}


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS model_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_type TEXT,
        model TEXT,
        tier TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        estimated_cost REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


def get_recommended_model(task_type: str) -> dict:
    """Get the recommended model for a task type."""
    tier = ROUTING_RULES.get(task_type, "mid")  # Default to mid if unknown

    # ALL tiers point to free OpenRouter models — $0 Anthropic credits remaining
    models = {
        "free": {"model": "nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter", "cost_per_1k": 0.00},
        "mid": {"model": "nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter", "cost_per_1k": 0.00},
        "high": {"model": "nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter", "cost_per_1k": 0.00},
    }

    return {
        "task_type": task_type,
        "tier": tier,
        **models[tier]
    }


def log_usage(task_type: str, model: str, input_tokens: int, output_tokens: int):
    """Log model usage for cost tracking."""
    db = get_db()
    tier = "free"
    for m, info in MODEL_COSTS.items():
        if m in model.lower():
            tier = info["tier"]
            cost = (input_tokens / 1_000_000 * info["input"]) + (output_tokens / 1_000_000 * info["output"])
            break
    else:
        cost = 0

    db.execute(
        "INSERT INTO model_usage (task_type, model, tier, input_tokens, output_tokens, estimated_cost) VALUES (?,?,?,?,?,?)",
        (task_type, model, tier, input_tokens, output_tokens, cost)
    )
    db.commit()


def cost_report(days: int = 7) -> dict:
    """Generate cost report for the last N days."""
    db = get_db()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # Total costs by tier
    tiers = db.execute("""
        SELECT tier, COUNT(*) as calls, SUM(input_tokens) as input_tok,
               SUM(output_tokens) as output_tok, SUM(estimated_cost) as cost
        FROM model_usage WHERE created_at >= ?
        GROUP BY tier
    """, (since,)).fetchall()

    # Total costs by task
    tasks = db.execute("""
        SELECT task_type, COUNT(*) as calls, SUM(estimated_cost) as cost
        FROM model_usage WHERE created_at >= ?
        GROUP BY task_type ORDER BY cost DESC LIMIT 10
    """, (since,)).fetchall()

    total_cost = sum(row["cost"] or 0 for row in tiers)
    total_calls = sum(row["calls"] or 0 for row in tiers)

    report = {
        "period": f"Last {days} days",
        "total_cost": f"${total_cost:.2f}",
        "total_calls": total_calls,
        "by_tier": [dict(row) for row in tiers],
        "top_tasks": [dict(row) for row in tasks],
    }

    print(f"\n{'='*50}")
    print(f"  Model Cost Report — Last {days} Days")
    print(f"{'='*50}")
    print(f"  Total cost:  ${total_cost:.2f}")
    print(f"  Total calls: {total_calls}")
    print(f"\n  By Tier:")
    for t in tiers:
        print(f"    {t['tier']:6s}: {t['calls']:4d} calls — ${(t['cost'] or 0):.2f}")
    if tasks:
        print(f"\n  Top Tasks by Cost:")
        for t in tasks:
            print(f"    {t['task_type']:25s}: {t['calls']:4d} calls — ${(t['cost'] or 0):.2f}")

    # Optimization suggestions
    print(f"\n  Optimization Tips:")
    for t in tasks:
        current_tier = ROUTING_RULES.get(t["task_type"], "mid")
        if current_tier == "high" and (t["cost"] or 0) > 1:
            print(f"    ⚠️  {t['task_type']}: Consider downgrading to 'mid' tier (saves ${(t['cost'] or 0) * 0.8:.2f})")
        elif current_tier == "mid" and (t["cost"] or 0) > 0.5:
            print(f"    💡 {t['task_type']}: Could some of these use 'free' tier?")
    print(f"{'='*50}\n")

    return report


def optimization_check() -> dict:
    """Analyze usage and suggest optimizations."""
    db = get_db()
    since = (datetime.utcnow() - timedelta(days=7)).isoformat()

    # Find tasks using expensive models that could be cheaper
    expensive = db.execute("""
        SELECT task_type, model, COUNT(*) as calls, SUM(estimated_cost) as cost
        FROM model_usage
        WHERE tier IN ('mid', 'high') AND created_at >= ?
        GROUP BY task_type, model
        ORDER BY cost DESC
    """, (since,)).fetchall()

    suggestions = []
    total_savings = 0

    for row in expensive:
        recommended = get_recommended_model(row["task_type"])
        if recommended["tier"] == "free" and row["model"] != recommended["model"]:
            savings = row["cost"] or 0
            total_savings += savings
            suggestions.append({
                "task": row["task_type"],
                "current": row["model"],
                "recommended": recommended["model"],
                "savings": f"${savings:.2f}/week",
            })

    print(f"\n{'='*50}")
    print(f"  Model Routing Optimization")
    print(f"{'='*50}")
    if suggestions:
        for s in suggestions:
            print(f"  {s['task']}:")
            print(f"    Current:     {s['current']}")
            print(f"    Recommended: {s['recommended']}")
            print(f"    Savings:     {s['savings']}")
        print(f"\n  Total potential savings: ${total_savings:.2f}/week")
    else:
        print(f"  All tasks are optimally routed!")
    print(f"{'='*50}\n")

    return {"suggestions": suggestions, "total_savings": f"${total_savings:.2f}/week"}


def status():
    """Show current routing configuration."""
    print(f"\n{'='*50}")
    print(f"  Model Routing Configuration")
    print(f"{'='*50}")
    print(f"\n  FREE Tier (Groq/Llama — $0/mo):")
    for task, tier in ROUTING_RULES.items():
        if tier == "free":
            print(f"    - {task}")
    print(f"\n  MID Tier (Claude Sonnet — ~$3/M tokens):")
    for task, tier in ROUTING_RULES.items():
        if tier == "mid":
            print(f"    - {task}")
    print(f"\n  HIGH Tier (Claude Opus — ~$15/M tokens):")
    for task, tier in ROUTING_RULES.items():
        if tier == "high":
            print(f"    - {task}")
    print(f"\n  Target: 100% free (OpenRouter) — $0 Anthropic credits")
    print(f"  Target weekly cost: $0")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Model Router — Smart Cost Optimization")
    parser.add_argument("--status", action="store_true", help="Show routing config")
    parser.add_argument("--optimize", action="store_true", help="Analyze and suggest optimizations")
    parser.add_argument("--cost-report", action="store_true", help="Cost report")
    parser.add_argument("--days", type=int, default=7, help="Days for report")
    parser.add_argument("--route", help="Get recommended model for a task type")
    args = parser.parse_args()

    if args.status:
        status()
    elif args.optimize:
        optimization_check()
    elif args.cost_report:
        cost_report(args.days)
    elif args.route:
        rec = get_recommended_model(args.route)
        print(f"Task: {rec['task_type']} → Model: {rec['model']} (Tier: {rec['tier']})")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
