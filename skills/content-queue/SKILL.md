---
name: content-queue
description: "Manages content across auto-postable and manual-post platforms. For platforms the bot CAN'T auto-post to (Facebook, LinkedIn, Craigslist), content goes into a queue and Quenton gets notified to post manually. For platforms with API access (Twitter, Bluesky, email), posts directly."
---

# Content Queue — Honest Content Management

## The Problem
The bot can create content for any platform, but can only AUTO-POST to platforms with API access.

## Auto-Postable (bot handles it):
- Telegram (working)
- Twitter/X (needs TWITTER_API_KEY)
- Bluesky (needs BLUESKY_APP_PASSWORD)
- Email via Brevo (needs BREVO_API_KEY)

## Manual-Post (bot creates, you post):
- Facebook — no free posting API
- LinkedIn — no free posting API
- Craigslist — no API at all
- Instagram — no free API
- TikTok — requires developer approval

## Usage
```bash
# Add content to queue
python3 skills/content-queue/content_queue.py --add --platform facebook --content "Your post text"

# List what needs manual posting
python3 skills/content-queue/content_queue.py --list

# Export all manual items (copy-paste ready)
python3 skills/content-queue/content_queue.py --export

# Mark something as posted
python3 skills/content-queue/content_queue.py --done 3
```
