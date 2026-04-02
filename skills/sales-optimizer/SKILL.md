---
name: sales-optimizer
description: "Close rate improvement through conversation analysis and script optimization. Use when: analyzing win/loss patterns, upgrading objection scripts, or calibrating lead scores. NOT for: sending emails or booking demos."
metadata:
  openclaw:
    emoji: "\U0001F3AF"
    requires:
      bins:
        - python3
---

# Sales Optimizer

Continuously improves close rate by learning from every sales conversation. Analyzes wins, losses, objection handling, demo outcomes, and conversation pacing to autonomously upgrade scripts, calibrate lead scores, and maintain a winning phrases database.

## When to Use
- After every terminal conversation (closed or lost) for post-conversation analysis
- When running weekly deep analysis of objection scripts and demo outcomes
- When calibrating lead scoring weights based on actual outcomes
- NOT for sending emails, booking demos, or direct lead communication

## Commands
```bash
python3 skills/sales-optimizer/sales_optimizer.py --weekly-analysis
python3 skills/sales-optimizer/sales_optimizer.py --post-conversation --lead-id "lead_123" --outcome won
python3 skills/sales-optimizer/sales_optimizer.py --calibrate-scores
python3 skills/sales-optimizer/sales_optimizer.py --win-loss-report
```

## Cron Setup
```bash
openclaw cron add --name "sales-optimizer-weekly" --cron "0 6 * * 3" --tz "America/Los_Angeles" --session isolated --message "Run weekly deep sales analysis: objection script comparison, demo briefing analysis, conversation pacing optimization, lead score calibration, and win/loss pattern report"
```
Event-driven trigger also fires after every terminal conversation (closed or lost).

## Key Rules
- Objection script upgrades: every 10 objection conversations, compare winning vs losing with Claude, auto-update reply-handler prompts
- Demo prep enhancement: after 10+ demos, analyze briefings vs outcomes, update sales-closer briefing template
- Lead score weight changes capped at +/-1 per optimization cycle
- If close rate drops >20% after an update, auto-revert and notify owner
- Never changes price, founding member cap, or core value proposition
- All script updates logged with before/after for rollback capability

## LLM Usage
- **Claude Sonnet**: Conversation analysis, objection script comparison, closing language extraction (revenue-critical tasks requiring nuance). Weekly spend cap: $20/week.
- **Groq / Llama 3.1 70B Versatile**: Pattern extraction, demo briefing analysis, pacing statistics (cost-efficient batch processing)
