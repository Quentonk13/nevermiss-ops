---
name: revenue-engine
description: "Master orchestrator for all 5 proven money-making playbooks. Ties AI SDR, Social Content, Multi-Business, Digital Products, and Cost Optimization into one autonomous cycle. HONEST about what it can/cannot do."
---

# NeverMiss Revenue Engine

## Quick Start
```bash
# First run — dry test (sends nothing, posts nothing)
python3 skills/revenue-engine/revenue_engine.py --test

# Check what APIs are available
python3 skills/revenue-engine/revenue_engine.py --access

# Run a live cycle
python3 skills/revenue-engine/revenue_engine.py --cycle

# Get honest status
python3 skills/revenue-engine/revenue_engine.py --report
```

## What It Does
1. **AI SDR**: Find leads → research → personalize → send (if Brevo key set) or queue
2. **Social Content**: Create posts → auto-post (if API keys set) or queue for manual
3. **Track costs**: Every API call logged with estimated cost
4. **Honest reporting**: Never claims it did something it didn't

## Honesty Policy
- If an API key is missing, it says so and queues for manual action
- If a platform has no free API (Facebook, LinkedIn, Craigslist), it queues content and tells you to post manually
- Test mode (`--test`) runs everything without sending — always test first
