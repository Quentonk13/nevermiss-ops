---
name: outreach-sequencer
description: "Generates and sends cold email sequences via Instantly.ai. Use when: sending cold outreach, managing follow-up cadence, or monitoring inbox health. NOT for: handling replies or post-booking follow-ups."
metadata:
  openclaw:
    emoji: "\U0001F4E7"
    requires:
      bins:
        - python3
---

# Outreach Sequencer

Generates personalized cold email sequences and sends them via the Instantly.ai API. Manages variant rotation, inbox warmup, follow-up cadence, bounce monitoring, and daily send limits across all active inboxes.

## When to Use
- When generating and sending cold email sequences to qualified leads
- When managing follow-up cadence (3-day, 4-day, 5-day intervals)
- When monitoring inbox health and bounce rates
- NOT for handling inbound replies or post-booking communications

## Commands
```bash
python3 skills/outreach-sequencer/outreach_sequencer.py --run
python3 skills/outreach-sequencer/outreach_sequencer.py --check-warmup
python3 skills/outreach-sequencer/outreach_sequencer.py --inbox-health
```

## Cron Setup
```bash
openclaw cron add --name "outreach-sequencer-sends" --cron "*/30 7-16 * * *" --tz "America/Los_Angeles" --session isolated --message "Run outreach sequencer to generate and send cold emails for qualified leads"
```

## Key Rules
- Three variants (A: casual/peer, B: direct/numbers, C: curiosity/question) rotated evenly, no repeat variant per lead in a sequence
- Every email passes through qa-guard before queuing; max 2 regeneration attempts on rejection
- Send window: 8AM-5PM in recipient's local timezone, randomized (never on the hour/half-hour)
- Warmup protocol: Week 1 = 5/inbox/day, Week 2 = 10, Week 3 = 20, Week 4 = 35, Week 5+ = 50 (hard limits, never exceeded)
- Bounce rate > 3% = warning; > 5% = inbox PAUSED + owner notified
- Suppression list checked before every send via crm-engine
- Follow-up sequence: FU1 at +3 days, FU2 at +4 days, FU3 (breakup) at +5 days; stops on any reply or bounce

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Generates all email copy (subject + body) using variant-specific prompt templates
- No other LLM provider used by this skill
