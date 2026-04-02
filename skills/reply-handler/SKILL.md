---
name: reply-handler
description: "Classifies and routes inbound email replies. Use when: processing incoming replies, auto-responding to questions/objections, or updating lead status. NOT for: sending cold outreach or lead sourcing."
metadata:
  openclaw:
    emoji: "\U0001F4AC"
    requires:
      bins:
        - python3
---

# Reply Handler

Detects, classifies, and routes all inbound email replies. Matches replies to leads, classifies intent into 10 categories, and either auto-responds or takes pipeline action.

## When to Use
- When processing new inbound email replies from leads
- When classifying reply intent (interested, objection, question, bounce, etc.)
- When auto-generating responses to questions or objections
- NOT for sending cold outreach or sourcing leads

## Commands
```bash
python3 skills/reply-handler/reply_handler.py --run
python3 skills/reply-handler/reply_handler.py --process-single --reply-id "reply_123"
```

## Cron Setup
```bash
openclaw cron add --name "reply-handler-poll" --cron "*/15 7-21 * * *" --tz "America/Los_Angeles" --session isolated --message "Poll Instantly for new replies, classify intent, and route responses"
```

## Key Rules
- 10 classification categories: INTERESTED, NOT_INTERESTED, QUESTION, OBJECTION_PRICE, OBJECTION_TIMING, OBJECTION_TRUST, OBJECTION_NEED, OUT_OF_OFFICE, BOUNCE, SPAM
- All outbound replies pass through qa-guard before sending
- Multi-turn conversation supported with full context; max 5 turns before automatic escalation to owner
- Routing is deterministic based on classification -- no LLM decides actions, only categories and response text
- Claude API costs tracked per-lead and globally

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Classification of reply intent into categories, plus auto-generated responses for QUESTION replies
- **Claude Sonnet**: Senior sales closer responses for INTERESTED and OBJECTION_* replies (higher-stakes conversations requiring nuance)
