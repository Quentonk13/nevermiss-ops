---
name: competitive-edge
description: "Competitor weakness mining, pricing intelligence, and strategic playbooks. Use when: analyzing competitor reviews, tracking pricing changes, updating win strategies, or detecting churn signals. NOT for: contacting competitors or modifying product pricing."
metadata:
  openclaw:
    emoji: "\U0001F3C6"
    requires:
      bins:
        - python3
---

# Competitive Edge

Makes the system systematically better than every competitor. Continuously mines competitor weaknesses, tracks pricing changes, identifies feature gaps, maintains per-competitor playbooks, times market moves, and prevents churn.

## When to Use
- When running the weekly competitor analysis cycle (reviews, pricing, features, playbooks)
- When a competitor pricing change is detected and needs immediate response
- When injecting competitor playbook context into sales conversations
- When checking customer churn risk signals
- NOT for contacting competitors directly or modifying product pricing

## Commands
```bash
python3 skills/competitive-edge/competitive_edge.py --weekly-cycle
python3 skills/competitive-edge/competitive_edge.py --pricing-alert --competitor "ServiceTitan" --old-price 299 --new-price 349
python3 skills/competitive-edge/competitive_edge.py --playbook --competitor "Housecall Pro"
python3 skills/competitive-edge/competitive_edge.py --churn-check --customer-id "cust_123"
```

## Cron Setup
```bash
openclaw cron add --name "competitive-edge-weekly" --cron "0 5 * * 4" --tz "America/Los_Angeles" --session isolated --message "Run full weekly competitor analysis: review mining, pricing check, feature gap update, playbook refresh, and market timing adjustment"
```
Real-time trigger also fires on competitor pricing change detection via browser-agent monitoring.

## Key Rules
- Weekly review scraping via browser-agent (G2, Capterra, Trustpilot, Google Reviews)
- On competitor price increase: generate price-anchoring variant + flag owner
- On competitor price decrease: analyze what they sacrificed, generate counter-positioning, update objection scripts
- Per-competitor "how to beat them" playbooks maintained and auto-injected into Claude prompts when competitor mentioned
- Playbook injections are additive context, never override base conversation scripts
- Never recommend changing core price ($297/mo) without explicit owner approval
- Never contact competitors directly (no mystery shopping, no fake signups)
- Feature recommendations are suggestions only -- owner decides what gets built
- Claude hard cap: $15/week

## LLM Usage
- **Claude Sonnet**: Strategic analysis -- weakness extraction, positioning updates, counter-messaging, feature gap prioritization. Weekly cadence. Hard cap: $15/week.
- **Groq / Llama 3.1 70B Versatile**: Data gathering -- review summarization, sentiment extraction, pattern detection (no spend cap)
