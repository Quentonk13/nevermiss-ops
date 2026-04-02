---
name: marketing-optimizer
description: "Channel ROI optimization, positioning refinement, and growth expansion. Use when: ranking channel performance, expanding to new geos/verticals, or refining positioning. NOT for: sending outreach or handling leads directly."
metadata:
  openclaw:
    emoji: "\U0001F4C8"
    requires:
      bins:
        - python3
---

# Marketing Optimizer

Maximizes lead acquisition ROI across all marketing channels. Ranks channels by return, discovers new verticals and geos, manages Facebook group strategy, refines positioning weekly, and discovers seasonal content angles.

## When to Use
- When ranking channel ROI and reallocating sourcing effort
- When evaluating geo or vertical expansion candidates
- When refining core value propositions and messaging positioning
- When generating seasonal content angles per vertical
- NOT for sending outreach emails or handling leads directly

## Commands
```bash
python3 skills/marketing-optimizer/marketing_optimizer.py --daily-update
python3 skills/marketing-optimizer/marketing_optimizer.py --weekly-refinement
python3 skills/marketing-optimizer/marketing_optimizer.py --channel-rankings
python3 skills/marketing-optimizer/marketing_optimizer.py --expansion-candidates
python3 skills/marketing-optimizer/marketing_optimizer.py --facebook-draft --post-id "post_123"
```

## Cron Setup
```bash
openclaw cron add --name "marketing-optimizer-deep" --cron "0 5 * * 2" --tz "America/Los_Angeles" --session isolated --message "Run weekly deep marketing optimization: Claude positioning refinement, content angle discovery, and channel rebalancing"
openclaw cron add --name "marketing-optimizer-daily" --cron "0 7 * * *" --tz "America/Los_Angeles" --session isolated --message "Run daily channel ROI update, geo expansion check, and Facebook group monitoring"
```

## Key Rules
- Channel ROI calculated daily: cost-per-qualified-lead for Google Maps, Hunter.io, Yelp, Facebook groups, referrals
- Geo expansion: maximum 2 new cities per month, 2-week test per city before committing
- Vertical expansion: one new vertical at a time, 2-week performance window before graduation
- Facebook drafts require explicit owner approval before any external posting
- Positioning changes: one variable at a time, never multiple messaging elements simultaneously
- Never spend money on paid advertising without explicit owner approval
- Claude hard cap: $10/week

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Data aggregation, ROI calculations, draft generation, seasonal pattern detection (no spend cap)
- **Claude Sonnet**: Positioning refinement (weekly), content angle discovery, strategic channel decisions. Hard cap: $10/week.
