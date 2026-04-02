---
name: performance-engine
description: "Tracks metrics, runs A/B testing, and generates performance reports. Use when: analyzing variant performance, checking pipeline metrics, or generating weekly reports. NOT for: modifying email variants or sending outreach."
metadata:
  openclaw:
    emoji: "\U0001F4CA"
    requires:
      bins:
        - python3
---

# Performance Engine

Tracks all system metrics, runs A/B variant analysis with statistical significance testing, optimizes email variants, and generates weekly performance reports.

## When to Use
- When analyzing email variant performance (open rate, reply rate, bounce rate)
- When running A/B significance tests at 100-email milestones
- When generating the weekly performance report
- When checking pipeline conversion rates or revenue metrics
- NOT for modifying email content or sending outreach

## Commands
```bash
python3 skills/performance-engine/performance_engine.py --weekly-report
python3 skills/performance-engine/performance_engine.py --variant-analysis
python3 skills/performance-engine/performance_engine.py --metrics-summary
```

## Cron Setup
```bash
openclaw cron add --name "performance-engine-weekly" --cron "0 20 * * 0" --tz "America/Los_Angeles" --session isolated --message "Generate weekly performance report with pipeline metrics, variant analysis, revenue stats, and actionable recommendations"
```
Event-driven metric collection also runs on outreach/reply/status-change events. Variant analysis triggers at every 100-email milestone per variant.

## Key Rules
- Tracks per-variant: open rate, reply rate, positive reply rate, bounce rate, QA rejection rate
- Pipeline metrics: stage conversion rates (lead to contacted through booked to closed), average days per stage
- Revenue metrics: weekly/monthly MRR, total MRR, revenue per lead, CAC
- All metrics broken down by vertical, tier, state/region, lead source, and lead score
- A/B testing uses z-test for proportions at 95% confidence; underperformers flagged for replacement (staged for owner approval, not auto-deployed)

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Variant generation (replacement drafts based on winner patterns) and report narrative summaries
- No Claude usage in this skill
