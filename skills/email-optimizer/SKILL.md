---
name: email-optimizer
description: "Self-optimizing email system for variants, send times, and follow-up cadence. Use when: retiring underperforming variants, adjusting send windows, or tuning geo allocation. NOT for: sending emails or handling replies."
metadata:
  openclaw:
    emoji: "\u26A1"
    requires:
      bins:
        - python3
---

# Email Optimizer

Autonomous self-optimizing email system. Continuously analyzes outreach performance data and makes optimization decisions without human approval: retiring underperforming variants, adjusting send times, tuning follow-up cadence, evolving subject lines, matching variants to verticals, and reallocating geographic sourcing.

## When to Use
- When a variant underperforms and needs replacement (after 200+ emails with statistical significance)
- When optimizing send time windows based on reply rate data
- When adjusting follow-up timing or adding a 4th follow-up
- When rebalancing geographic lead sourcing weights
- NOT for directly sending emails or handling inbound replies

## Commands
```bash
python3 skills/email-optimizer/email_optimizer.py --weekly-optimize
python3 skills/email-optimizer/email_optimizer.py --emergency --inbox "inbox_name"
python3 skills/email-optimizer/email_optimizer.py --variant-check
python3 skills/email-optimizer/email_optimizer.py --geo-rebalance
```

## Cron Setup
```bash
openclaw cron add --name "email-optimizer-weekly" --cron "0 5 * * 1" --tz "America/Los_Angeles" --session isolated --message "Run weekly email optimization: variant replacement, send time optimization, follow-up timing, subject line evolution, vertical-variant matching, and geo reallocation"
```
Emergency trigger also fires immediately when any inbox bounce rate exceeds 3% (monitored by outreach-sequencer).

## Key Rules
- Variant replacement after 200+ emails if reply rate <50% of top performer (chi-squared, p < 0.05); no owner approval needed
- Send time optimization after 500+ total emails: identify 3-hour peak window, weight 60% of sends there
- Follow-up timing adjusted based on reply rate data; 4th follow-up added if breakup email >2% reply rate
- Subject line patterns tracked and losing patterns added to qa-guard reject list after 300+ emails
- Vertical-variant matching after 100+ emails per cell with >2x difference
- Geo reallocation every 2 weeks based on reply rate ranking
- 20% of sends always reserved for exploration (non-optimized random assignment)
- Never reduces total daily send volume or changes warmup limits
- All replacement variants must pass qa-guard before deployment

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Generates replacement email variants, subject line variations, and all bulk optimization copy
- **Claude Sonnet**: Used ONLY when a variant crosses 5% reply rate, to analyze what makes it work and generate refined variants. Hard cap of $5/week on Claude spend.
