---
name: qa-guard
description: "Synchronous QA gate for outbound messages. Use when: checking emails before sending for spam, compliance, and tone. NOT for: generating email content or handling replies."
metadata:
  openclaw:
    emoji: "\U0001F6E1\uFE0F"
    requires:
      bins:
        - python3
---

# QA Guard

Synchronous gate that checks ALL outbound messages for spam triggers, compliance violations, and quality issues before sending. Nothing leaves the system without passing QA. Called by outreach-sequencer and reply-handler.

## When to Use
- Before sending any outbound email (cold or reply)
- When outreach-sequencer generates a new email and needs validation
- When reply-handler drafts an auto-response and needs quality check
- NOT for generating email content -- only validating it

## Commands
```bash
python3 skills/qa-guard/qa_guard.py --subject "subject line" --body "email body" --type cold --sequence-number 1
```

Entry point function:
```python
check_email(subject, body, email_type="cold", sequence_number=1, variant=None, is_forwarding=False)
# Returns: {"passed": bool, "reasons": [...], "tone_score": float|None, "attempts": int}
```

## Cron Setup
No cron schedule -- this skill is event-driven, called synchronously by outreach-sequencer and reply-handler before every outbound message.

## Key Rules
- Spam pattern detection is entirely rule-based (ALL CAPS, exclamation marks, dollar signs, spam trigger words, links in emails 1-3, emojis, AI language, product name in cold emails)
- Cold emails must not exceed 3 sentences; replies must not exceed 4 sentences
- Subject lines must be 6 words or fewer with no punctuation (except ?)
- Email body must not start with "I"
- On rejection: max 2 regeneration attempts per email, then skip lead and log failure
- Rejection rate tracked per variant for optimization feedback

## LLM Usage
- **Groq / Llama 3.1 70B Versatile**: Tone check only -- scores human-likeness 1-5, rejects below 3
- All other checks (spam detection, compliance, structural validation) are rule-based with no LLM involvement
