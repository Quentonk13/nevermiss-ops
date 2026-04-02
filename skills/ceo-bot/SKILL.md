---
name: ceo-bot
description: "Master orchestrator and strategic command layer. Use when: running nightly reviews, generating morning briefs, conducting strategic analysis, or coordinating cross-skill delegation. NOT for: direct lead communication or overriding security."
metadata:
  openclaw:
    emoji: "\U0001F9E0"
    requires:
      bins:
        - python3
---

# CEO Bot

Master orchestrator and strategic command layer. Sits above all other skills, aggregates their outputs, analyzes performance against targets, delegates work, manages a 3-layer memory system, and drives continuous 1% improvement across the entire system.

## When to Use
- For nightly performance review and delegation across all skills
- For generating the morning brief with yesterday's stats and today's focus
- For weekly strategic review analyzing trajectory toward founding member goal
- For resolving conflicts between optimizers or reallocating resources
- NOT for direct lead communication, overriding security lockdowns, or external posting

## Commands
```bash
python3 skills/ceo-bot/ceo_bot.py --nightly-review
python3 skills/ceo-bot/morning_brief.py --generate
python3 skills/ceo-bot/strategic_review.py --weekly
python3 skills/ceo-bot/nightly_review.py --run
python3 skills/ceo-bot/delegator.py --execute-pending
python3 skills/ceo-bot/memory_manager.py --update
```

## Cron Setup
```bash
openclaw cron add --name "ceo-bot-nightly" --cron "0 22 * * *" --tz "America/Los_Angeles" --session isolated --message "Run nightly CEO review: aggregate all skill data, analyze performance vs targets, execute delegations, update 3-layer memory, identify and implement one 1% improvement"
openclaw cron add --name "ceo-bot-morning-brief" --cron "30 6 * * *" --tz "America/Los_Angeles" --session isolated --message "Generate morning brief: yesterday stats, overnight actions taken, today focus areas (under 10 lines)"
openclaw cron add --name "ceo-bot-strategic-review" --cron "0 19 * * 0" --tz "America/Los_Angeles" --session isolated --message "Run weekly strategic review: deep trajectory analysis toward 20 founding members, acceleration levers, risks, resource allocation, next week top 3 priorities"
```
Real-time trigger also fires immediately on critical events (budget overrun, system failure, security alert, bounce rate spike).

## Key Rules
- Performance targets: reply rate >3%, qualified rate >40% of replies, booking rate >40% of qualified, close rate >25% of demos
- Authority to trigger any skill, modify skill config within guardrails, reallocate resources, conduct performance reviews, resolve optimizer conflicts
- CANNOT override security lockdowns, exceed budget caps, change pricing, make financial commitments, post publicly, delete data, or communicate externally
- 1% improvement system: each nightly review identifies ONE small, low-risk, measurable, reversible improvement; auto-pause if negative trend over 3 consecutive days
- 3-layer memory: Knowledge Graph (durable business facts), Daily Notes (dated decisions/learnings), Tacit Knowledge (hard rules from experience)
- Claude hard cap: $30/week

## LLM Usage
- **Claude Sonnet**: Strategic reasoning, nightly analysis, weekly reviews, bottleneck identification, delegation decisions. Hard cap: $30/week.
- **Groq / Llama 3.1 70B Versatile**: Data aggregation, summarization, formatting, routine memory updates, morning brief generation.
