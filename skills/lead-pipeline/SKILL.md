---
name: lead-pipeline
description: "Sources, enriches, deduplicates, and scores contractor leads. Use when: sourcing new leads from Hunter/Maps/Yelp/Facebook or scoring existing leads. NOT for: outreach, replies, or CRM operations."
metadata:
  openclaw:
    emoji: "\U0001F50D"
    requires:
      bins:
        - python3
---

# Lead Pipeline

Sources, enriches, deduplicates, scores, and stores contractor leads from multiple channels. Feeds qualified leads (score >= 3) into the CRM engine for outreach sequencing.

## When to Use
- When sourcing new leads from Hunter.io, Google Maps, Yelp, or Facebook groups
- When enriching or scoring existing lead data
- When deduplicating leads across sources
- NOT for sending outreach, handling replies, or direct CRM operations

## Commands
```bash
python3 skills/lead-pipeline/lead_pipeline.py --source hunter --geo "Los Angeles"
python3 skills/lead-pipeline/lead_pipeline.py --source google-maps --vertical hvac
python3 skills/lead-pipeline/lead_pipeline.py --source yelp --geo "Phoenix"
python3 skills/lead-pipeline/lead_pipeline.py --source facebook --monitor
```

## Cron Setup
```bash
openclaw cron add --name "lead-pipeline-daily" --cron "0 6 * * *" --tz "America/Los_Angeles" --session isolated --message "Run daily lead sourcing from Hunter.io, Google Maps, and Yelp"
openclaw cron add --name "lead-pipeline-facebook" --cron "0 8,12,16,20 * * *" --tz "America/Los_Angeles" --session isolated --message "Run Facebook group mining for contractor leads"
```

## Key Rules
- Scoring is deterministic (1-5 points): base +1, Tier 1 vertical +1, <20 employees +1, no live chat/slow response/no website +1, warm intent or >50 reviews or owner role +1
- Only leads scoring >= 3 are passed to CRM engine
- Deduplication runs before CRM insertion via crm-engine
- Daily output log tracks: leads per channel, score distribution, duplicates found, qualified leads passed

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Lead enrichment, Facebook post classification (missed-call relevance YES/NO), vertical inference
- No Claude usage -- all LLM tasks routed to Groq for cost efficiency
