---
name: sales-closer
description: "Post-booking pipeline for demo prep, follow-ups, and win/loss tracking. Use when: a lead books a demo, needs a follow-up after demo, or tracking close outcomes. NOT for: cold outreach or reply classification."
metadata:
  openclaw:
    emoji: "\U0001F91D"
    requires:
      bins:
        - python3
---

# Sales Closer

Post-booking pipeline skill: pre-demo prep briefings, post-demo follow-up sequences, and win/loss tracking for the autonomous revenue engine.

## When to Use
- When a lead transitions to `booked` status in CRM (pre-demo briefing)
- When generating post-demo follow-up emails
- When tracking wins, losses, and MRR
- NOT for cold outreach generation or reply classification

## Commands
```bash
python3 skills/sales-closer/sales_closer.py --run-daily
python3 skills/sales-closer/sales_closer.py --brief --lead-id "lead_123"
python3 skills/sales-closer/sales_closer.py --follow-up --lead-id "lead_123"
python3 skills/sales-closer/sales_closer.py --log-outcome --lead-id "lead_123" --result won --mrr 297
```

## Cron Setup
```bash
openclaw cron add --name "sales-closer-daily" --cron "0 9 * * *" --tz "America/Los_Angeles" --session isolated --message "Run daily sales closer check for pending follow-ups, 24h post-demo nudges, and stalled deal detection"
```
Event-driven trigger also fires on CRM status transition to `booked`.

## Key Rules
- Pre-demo brief sent 30 minutes before demo (what lead cares about, expected objections, homework from their website/reviews, recommended close approach)
- Post-demo follow-ups use RELAXED qa-guard rules: links, product name, dollar amounts all allowed
- Follow-up sequence: +24h personalized follow-up, +3 days shorter nudge, then mark stalled + notify owner
- Win tracking: close date, MRR ($297), days to close, objections overcome, opening variant
- Loss tracking: loss reason, stage lost at -- all data fed to performance-engine

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Pre-demo lead briefing generation (1 paragraph, under 150 words)
- **Claude Sonnet**: Post-demo follow-up email generation (4-5 sentences, personalized, revenue-critical)
