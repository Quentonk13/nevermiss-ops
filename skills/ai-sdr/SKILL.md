---
name: ai-sdr
description: "Autonomous AI Sales Development Rep. Full sales cycle: research leads, personalize outreach, send sequences, triage replies. Replaces a $200K/yr SDR hire for ~$25/mo in API costs. Based on the proven Stormy.ai playbook."
metadata:
  openclaw:
    emoji: "💰"
    requires:
      bins:
        - python3
---

# AI SDR — Autonomous Sales Dev Rep

Replaces a $200K/yr SDR hire for ~$25-50/mo in API costs.

## What It Does
1. **Research** — Finds leads using free-search (no paid APIs)
2. **Personalize** — Researches each lead individually for 40% higher response rates
3. **Outreach** — Sends personalized sequences via Instantly
4. **Triage** — Classifies replies (interested/not interested/meeting request)
5. **Book** — Auto-responds to interested leads, books demos

## Usage
```bash
# Full SDR cycle for a target market
python3 skills/ai-sdr/sdr_engine.py --target "plumbers in Phoenix AZ" --max-leads 20

# Research and personalize for a specific company
python3 skills/ai-sdr/sdr_engine.py --company "ABC Plumbing" --domain abcplumbing.com

# Triage incoming replies
python3 skills/ai-sdr/sdr_engine.py --triage-inbox

# Daily SDR report
python3 skills/ai-sdr/sdr_engine.py --report
```

## Revenue Model
- Cost: ~$25-50/mo (API calls)
- As a service: $1,500-3,000/mo per client
- Pipeline increase: 40%+ vs manual outreach
