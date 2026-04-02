---
name: social-content
description: "Autonomous social media content creation and scheduling. Based on Oliver's 'Larry' agent pattern ($671 MRR, 8M views in 1 week). Creates viral short-form content for TikTok, Twitter, LinkedIn. Drives traffic without manual effort."
metadata:
  openclaw:
    emoji: "📱"
    requires:
      bins:
        - python3
---

# Social Content Engine

Autonomous content creation based on Oliver's "Larry" agent pattern.

## Results (Proven)
- $671 MRR from autonomous content
- 8M views in 1 week
- Zero manual content creation

## What It Does
1. **Generate** — Creates viral hooks, scripts, and posts for any platform
2. **Schedule** — Queues content across platforms
3. **Analyze** — Tracks what's working, doubles down on winners
4. **Iterate** — Self-improves based on engagement data

## Usage
```bash
# Generate content ideas for a niche
python3 skills/social-content/content_engine.py --niche "HVAC contractors" --platform twitter --count 10

# Generate a week of content
python3 skills/social-content/content_engine.py --niche "plumbing tips" --weekly

# Generate viral hooks for TikTok/Reels
python3 skills/social-content/content_engine.py --hooks "contractor marketing" --count 20

# Analyze top performing content
python3 skills/social-content/content_engine.py --analyze

# Full content calendar
python3 skills/social-content/content_engine.py --calendar --weeks 4
```
