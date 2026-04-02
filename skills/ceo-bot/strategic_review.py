#!/usr/bin/env python3
"""
Weekly Strategic Review — Sunday 7PM PT
Deep Claude analysis: trajectory to 20 founding members, acceleration levers,
risks, resource allocation, competitor moves, product feedback, next week's top 3 priorities.
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
REVIEWS_DIR = os.path.join(CEO_MEMORY_DIR, "strategic_reviews")
SYSTEM_LOG = os.path.join(DATA_DIR, "system_log.jsonl")
IMPROVEMENTS_LOG = os.path.join(CEO_MEMORY_DIR, "improvements_log.jsonl")

import ceo_bot


def _read_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default if default is not None else {}


def _collect_weekly_data() -> dict:
    """Collect all data from the past 7 days for strategic analysis."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    # Aggregate system log entries for the week
    weekly_stats = {
        "emails_sent": 0,
        "replies": 0,
        "demos_completed": 0,
        "deals_closed": 0,
        "errors": 0,
        "total_api_cost": 0.0,
        "skill_activity": {},
        "error_breakdown": {},
    }

    if os.path.exists(SYSTEM_LOG):
        with open(SYSTEM_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
                    if ts < week_start:
                        continue

                    skill = entry.get("skill", "unknown")
                    action = entry.get("action", "")
                    result = entry.get("result", "")

                    weekly_stats["skill_activity"][skill] = weekly_stats["skill_activity"].get(skill, 0) + 1
                    weekly_stats["total_api_cost"] += entry.get("cost_estimated", 0.0)

                    if skill == "outreach-sequencer" and action == "send_email" and result == "success":
                        weekly_stats["emails_sent"] += 1
                    elif skill == "reply-handler" and action in ("reply_processed", "handle_reply") and result == "success":
                        weekly_stats["replies"] += 1
                    elif result in ("failure", "error"):
                        weekly_stats["errors"] += 1
                        weekly_stats["error_breakdown"][skill] = weekly_stats["error_breakdown"].get(skill, 0) + 1
                except (json.JSONDecodeError, ValueError):
                    continue

    if weekly_stats["emails_sent"] > 0:
        weekly_stats["reply_rate_pct"] = round(weekly_stats["replies"] / weekly_stats["emails_sent"] * 100, 2)
    else:
        weekly_stats["reply_rate_pct"] = 0.0

    # Current pipeline
    crm_data = _read_json(os.path.join(DATA_DIR, "crm.json"), [])
    pipeline = {}
    if isinstance(crm_data, list):
        for lead in crm_data:
            status = lead.get("status", "unknown")
            pipeline[status] = pipeline.get(status, 0) + 1
        weekly_stats["total_leads"] = len(crm_data)
        weekly_stats["pipeline"] = pipeline
        weekly_stats["deals_closed"] = pipeline.get("closed", 0)
        weekly_stats["demos_completed"] = pipeline.get("demo_completed", 0)
    else:
        weekly_stats["total_leads"] = 0
        weekly_stats["pipeline"] = {}

    # Competitive intel
    competitive = _read_json(os.path.join(DATA_DIR, "competitive_edge", "latest.json"), {})
    weekly_stats["competitive_intel"] = competitive

    # Improvements this week
    improvements = []
    if os.path.exists(IMPROVEMENTS_LOG):
        with open(IMPROVEMENTS_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01T00:00:00+00:00"))
                    if ts >= week_start:
                        improvements.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
    weekly_stats["improvements"] = improvements

    # Daily notes summary
    daily_notes_summary = []
    for i in range(7):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        note_path = os.path.join(CEO_MEMORY_DIR, "daily_notes", f"{day}.md")
        if os.path.exists(note_path):
            with open(note_path, "r") as f:
                content = f.read()
            # Extract just the first few lines for summary
            note_lines = content.strip().split("\n")[:5]
            daily_notes_summary.append({"date": day, "summary": "\n".join(note_lines)})
    weekly_stats["daily_notes_summary"] = daily_notes_summary

    # Tacit knowledge count
    tacit_dir = os.path.join(CEO_MEMORY_DIR, "tacit")
    tacit_count = 0
    if os.path.exists(tacit_dir):
        for f in os.listdir(tacit_dir):
            if f.endswith(".md"):
                tacit_count += 1
    weekly_stats["tacit_knowledge_entries"] = tacit_count

    weekly_stats["total_api_cost"] = round(weekly_stats["total_api_cost"], 4)

    return weekly_stats


def _get_previous_review() -> dict | None:
    """Load the most recent previous strategic review for comparison."""
    if not os.path.exists(REVIEWS_DIR):
        return None
    files = sorted([f for f in os.listdir(REVIEWS_DIR) if f.endswith(".json")])
    if not files:
        return None
    try:
        with open(os.path.join(REVIEWS_DIR, files[-1]), "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def execute_strategic_review() -> dict:
    """Execute the weekly strategic review using Claude for deep analysis."""
    ceo_bot.ensure_directories()
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    ceo_bot.log("strategic_review", "started", "Beginning weekly strategic review")

    weekly_data = _collect_weekly_data()
    previous_review = _get_previous_review()

    previous_context = ""
    if previous_review:
        prev_priorities = previous_review.get("analysis", {}).get("next_week_priorities", [])
        prev_risks = previous_review.get("analysis", {}).get("risks", [])
        previous_context = f"""
LAST WEEK'S PRIORITIES:
{json.dumps(prev_priorities, indent=2)}

LAST WEEK'S IDENTIFIED RISKS:
{json.dumps(prev_risks, indent=2)}
"""

    improvements_summary = ""
    if weekly_data.get("improvements"):
        improvements_summary = "\nIMPROVEMENTS THIS WEEK:\n"
        for imp in weekly_data["improvements"]:
            improvements_summary += (
                f"- {imp.get('description', 'N/A')} "
                f"(outcome: {imp.get('outcome', 'pending')})\n"
            )

    system_prompt = (
        "You are the CEO-bot strategic advisor for NeverMiss AI, an AI receptionist startup "
        "targeting home service businesses. The goal is to reach 20 founding members as fast as possible. "
        "Provide deep, honest strategic analysis. No marketing speak. Think like a founder who has "
        "limited resources and needs to make every action count."
    )

    prompt = f"""WEEKLY STRATEGIC REVIEW — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

THIS WEEK'S DATA:
- Emails sent: {weekly_data['emails_sent']}
- Replies: {weekly_data['replies']} ({weekly_data['reply_rate_pct']}% rate)
- Total leads: {weekly_data.get('total_leads', 0)}
- Demos completed: {weekly_data.get('demos_completed', 0)}
- Deals closed: {weekly_data.get('deals_closed', 0)}
- Errors: {weekly_data['errors']}
- API cost: ${weekly_data['total_api_cost']}
- Active skills: {len(weekly_data.get('skill_activity', {}))}
- Tacit knowledge entries: {weekly_data.get('tacit_knowledge_entries', 0)}

PIPELINE:
{json.dumps(weekly_data.get('pipeline', {}), indent=2)}

ERROR BREAKDOWN BY SKILL:
{json.dumps(weekly_data.get('error_breakdown', {}), indent=2)}

SKILL ACTIVITY (actions this week):
{json.dumps(weekly_data.get('skill_activity', {}), indent=2)}

COMPETITIVE INTEL:
{json.dumps(weekly_data.get('competitive_intel', {}), indent=2) if weekly_data.get('competitive_intel') else 'No new competitive data'}
{improvements_summary}
{previous_context}

Analyze and respond in this exact JSON format:
{{
  "trajectory_assessment": "Are we on track to 20 founding members? Current pace, projected timeline, confidence level.",
  "acceleration_levers": [
    {{"lever": "description", "effort": "low|medium|high", "impact": "low|medium|high", "recommendation": "specific action"}}
  ],
  "risks": [
    {{"risk": "description", "severity": "critical|high|medium|low", "mitigation": "specific action"}}
  ],
  "resource_allocation": {{
    "assessment": "Are resources allocated optimally?",
    "recommendations": ["recommendation1", "recommendation2"]
  }},
  "competitor_analysis": "Key competitor moves and our positioning",
  "product_feedback_synthesis": "What the data tells us about product-market fit",
  "next_week_priorities": [
    {{"priority": "description", "owner_skill": "skill-name", "success_metric": "how to measure"}}
  ],
  "owner_summary": "3-sentence summary for the owner"
}}"""

    try:
        response_text, cost = ceo_bot.call_claude(prompt, system_prompt, max_tokens=4096)
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        analysis = json.loads(text)
    except json.JSONDecodeError:
        analysis = {
            "trajectory_assessment": f"Analysis parsing failed. Raw: {response_text[:300]}",
            "acceleration_levers": [],
            "risks": [{"risk": "Strategic review parsing error", "severity": "medium", "mitigation": "Review raw output"}],
            "resource_allocation": {"assessment": "Unable to assess", "recommendations": []},
            "competitor_analysis": "Unable to analyze",
            "product_feedback_synthesis": "Unable to analyze",
            "next_week_priorities": [{"priority": "Fix strategic review pipeline", "owner_skill": "ceo-bot", "success_metric": "Successful parse next week"}],
            "owner_summary": "Strategic review had a parsing error. Manual review recommended.",
        }
    except RuntimeError as e:
        analysis = {
            "trajectory_assessment": f"Claude budget exhausted — manual strategic review needed. Error: {e}",
            "acceleration_levers": [],
            "risks": [{"risk": "No strategic analysis this week", "severity": "high", "mitigation": "Owner manual review"}],
            "resource_allocation": {"assessment": "Cannot assess without Claude", "recommendations": []},
            "competitor_analysis": "Budget exhausted",
            "product_feedback_synthesis": "Budget exhausted",
            "next_week_priorities": [{"priority": "Ensure Claude budget for next strategic review", "owner_skill": "ceo-bot", "success_metric": "Budget available"}],
            "owner_summary": "Claude budget exhausted. No automated strategic analysis this week. Please review data manually.",
        }

    # Save the review
    review = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "week_ending": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "data": {k: v for k, v in weekly_data.items() if k not in ("competitive_intel", "daily_notes_summary")},
        "analysis": analysis,
    }

    review_path = os.path.join(REVIEWS_DIR, f"{review['week_ending']}.json")
    with open(review_path, "w") as f:
        json.dump(review, f, indent=2)
        f.write("\n")

    # Also save a readable markdown version
    md_path = os.path.join(REVIEWS_DIR, f"{review['week_ending']}.md")
    md_lines = [
        f"# Strategic Review — Week Ending {review['week_ending']}",
        "",
        f"## Trajectory",
        analysis.get("trajectory_assessment", "N/A"),
        "",
        "## Acceleration Levers",
    ]
    for lever in analysis.get("acceleration_levers", []):
        md_lines.append(f"- **{lever.get('lever', 'N/A')}** (effort: {lever.get('effort', '?')}, impact: {lever.get('impact', '?')}): {lever.get('recommendation', 'N/A')}")
    md_lines.append("")
    md_lines.append("## Risks")
    for risk in analysis.get("risks", []):
        md_lines.append(f"- [{risk.get('severity', '?').upper()}] {risk.get('risk', 'N/A')} — Mitigation: {risk.get('mitigation', 'N/A')}")
    md_lines.append("")
    md_lines.append("## Resource Allocation")
    md_lines.append(analysis.get("resource_allocation", {}).get("assessment", "N/A"))
    for rec in analysis.get("resource_allocation", {}).get("recommendations", []):
        md_lines.append(f"- {rec}")
    md_lines.append("")
    md_lines.append("## Competitor Analysis")
    md_lines.append(analysis.get("competitor_analysis", "N/A"))
    md_lines.append("")
    md_lines.append("## Product Feedback")
    md_lines.append(analysis.get("product_feedback_synthesis", "N/A"))
    md_lines.append("")
    md_lines.append("## Next Week's Priorities")
    for i, p in enumerate(analysis.get("next_week_priorities", [])[:3], 1):
        md_lines.append(f"{i}. **{p.get('priority', 'N/A')}** (owner: {p.get('owner_skill', '?')}, metric: {p.get('success_metric', '?')})")
    md_lines.append("")
    md_lines.append("## Owner Summary")
    md_lines.append(analysis.get("owner_summary", "N/A"))

    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")

    summary = {
        "week_ending": review["week_ending"],
        "trajectory": analysis.get("trajectory_assessment", "")[:100],
        "top_risk": analysis.get("risks", [{}])[0].get("risk", "None") if analysis.get("risks") else "None",
        "priorities_count": len(analysis.get("next_week_priorities", [])),
        "owner_summary": analysis.get("owner_summary", ""),
    }

    ceo_bot.log("strategic_review", "complete", json.dumps(summary))
    return {"summary": summary, "analysis": analysis, "data": weekly_data}


if __name__ == "__main__":
    result = execute_strategic_review()
    print(json.dumps(result["summary"], indent=2))
