---
name: free-search
description: "Free web search, lead finding, email discovery, and competitor research. No API keys. No cost. Replaces SerpAPI ($50/mo), Hunter.io ($49/mo), and Google Custom Search. Use for any web research, finding contractor businesses, discovering emails, or researching competitors."
metadata:
  openclaw:
    emoji: "🔍"
    requires:
      bins:
        - python3
---

# Free Web Search

Zero-cost web search using DuckDuckGo HTML scraping. No API keys needed.

## Replaces
- SerpAPI ($50/mo) → Free
- Hunter.io ($49/mo) → Free
- Google Custom Search ($5/1000 queries) → Free
- Brave Search API → Free

## Usage

### General search
```bash
python3 skills/free-search/free_search.py --query "HVAC contractors Phoenix AZ"
```

### Find contractor businesses (with email/phone extraction)
```bash
python3 skills/free-search/free_search.py --find-business plumber "Phoenix AZ"
python3 skills/free-search/free_search.py --find-business electrician "Dallas TX" --max 20
```

### Find emails for a company (replaces Hunter.io)
```bash
python3 skills/free-search/free_search.py --find-email "ABC Plumbing" --domain abcplumbing.com
```

### Research competitors
```bash
python3 skills/free-search/free_search.py --competitor "ServiceTitan"
python3 skills/free-search/free_search.py --competitor "Housecall Pro"
```

### Search news
```bash
python3 skills/free-search/free_search.py --query "contractor software" --news
```

### Save results
```bash
python3 skills/free-search/free_search.py --find-business roofer "Atlanta GA" --save
```
