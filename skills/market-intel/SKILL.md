---
name: market-intel
description: "Competitor and market research intelligence. Use when: tracking competitor pricing/positioning, researching verticals, or monitoring contractor community language. NOT for: direct competitor engagement or outreach."
metadata:
  openclaw:
    emoji: "\U0001F50E"
    requires:
      bins:
        - python3
---

# Market Intel

Researches competitors, monitors the market, and provides actionable competitive intelligence. Tracks pricing changes, customer complaints, vertical-specific data, and contractor community language patterns to sharpen sales messaging and outreach.

## When to Use
- When running weekly competitor pricing and positioning sweeps
- When updating vertical research files (job values, pain points, seasonal patterns)
- When monitoring contractor groups/forums for missed-call language and competitor complaints
- NOT for direct competitor engagement or sending outreach

## Commands
```bash
python3 skills/market-intel/market_intel.py --weekly-refresh
python3 skills/market-intel/market_intel.py --daily-monitor
python3 skills/market-intel/market_intel.py --vertical-update --vertical hvac
python3 skills/market-intel/market_intel.py --competitor-check --name "ServiceTitan"
```

## Cron Setup
```bash
openclaw cron add --name "market-intel-weekly" --cron "0 6 * * 0" --tz "America/Los_Angeles" --session isolated --message "Run full weekly competitor pricing and positioning sweep, vertical research update, and competitive positioning document regeneration"
openclaw cron add --name "market-intel-daily" --cron "0 7 * * *" --tz "America/Los_Angeles" --session isolated --message "Run daily Facebook and forum monitoring for missed-call language, competitor complaints, and objections"
```

## Key Rules
- Tracks 8 direct competitors: ServiceTitan, Housecall Pro, Jobber, Podium, Smith.ai, Ruby Receptionists, Numa, Hatch
- Per competitor: current pricing tiers, core value proposition, weaknesses from reviews, common customer complaints
- Maintains competitive positioning documents (vs live answering, vs FSM platforms, vs basic missed-call apps)
- Per-vertical research: average job values, phone management pain points, industry terminology, seasonal patterns, online hangouts
- Messaging intelligence fed to performance-engine and email-optimizer for refinement

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Review synthesis, complaint pattern extraction, competitive positioning analysis, vertical research summarization, messaging intelligence extraction
- No Claude usage -- all LLM tasks routed to Groq for cost efficiency
