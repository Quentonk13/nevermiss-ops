---
name: browser-agent
description: "Shared web interaction layer for browsing, scraping, and screenshots. Use when: any skill needs web data, site audits, review scraping, or competitor monitoring. NOT for: API-based data fetching or email sending."
metadata:
  openclaw:
    emoji: "\U0001F310"
    requires:
      bins:
        - python3
---

# Browser Agent

Shared web interaction layer giving the system eyes and hands on the web. Browses live pages, reads content, interacts with elements, takes screenshots, and extracts structured data. Used by lead-pipeline (site audits), competitive-edge (competitor monitoring), and market-intel (review scraping).

## When to Use
- When a skill needs to browse a webpage, take a screenshot, or extract structured data
- For lead website auditing (tech stack, chat widgets, booking, quality)
- For competitor website change detection and monitoring
- For review aggregation from G2, Capterra, BBB, Yelp, Google Maps
- NOT for API-based data fetching or email operations

## Commands
```bash
python3 skills/browser-agent/browser_agent.py --url "https://example.com" --action navigate
python3 skills/browser-agent/site_auditor.py --lead-id "lead_123"
python3 skills/browser-agent/review_scraper.py --source google --business "Business Name"
python3 skills/browser-agent/competitor_monitor.py --run-weekly
```

## Cron Setup
```bash
openclaw cron add --name "competitor-monitoring-weekly" --cron "0 6 * * 1" --tz "America/Los_Angeles" --session isolated --message "Run weekly competitor website monitoring via browser-agent competitor_monitor"
```

## Key Rules
- Rate limiting enforced: 100 visits/hour, 500/day
- robots.txt respected as a hard gate -- no bypass allowed
- Sandboxed browser: no purchases, no ToS agreements, no CAPTCHA bypass, no content posting
- Intelligent caching: 24h for competitor pages, 7d for static content
- User agent rotation to avoid fingerprinting
- All browsing activity logged to `data/system_log.jsonl`

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Page content analysis, data extraction, sentiment analysis
- **Claude Sonnet**: Complex reasoning tasks only (multi-page analysis, ambiguous data interpretation)
