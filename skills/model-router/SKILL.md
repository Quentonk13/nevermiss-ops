---
name: model-router
description: "Smart model routing to cut AI costs by 80%. Routes 90% of tasks to cheap models (Groq/Llama), only uses expensive models (Claude Sonnet/Opus) for revenue-critical tasks. Based on the Stormy.ai playbook that dropped weekly costs from $47 to $6."
metadata:
  openclaw:
    emoji: "🧠"
    requires:
      bins:
        - python3
---

# Model Router — Smart Cost Optimization

Drop weekly AI costs from $47 to $6 with intelligent model routing.

## Strategy (Proven by Stormy.ai)
- **90% of tasks** → Groq/Llama (FREE or near-free)
  - Email classification, reply triage, simple lookups
  - Template filling, data formatting, status checks
  - Heartbeat tasks, routine monitoring
- **10% of tasks** → Claude Sonnet ($3/M tokens)
  - Lead research, personalized outreach
  - Complex strategy decisions, competitor analysis
  - Revenue-critical conversations
- **<1% of tasks** → Claude Opus ($15/M tokens)
  - Only for deep research, contract analysis, complex negotiations

## Usage
```bash
# Check current cost tracking
python3 skills/model-router/router.py --status

# Analyze model usage and suggest optimizations
python3 skills/model-router/router.py --optimize

# Cost report
python3 skills/model-router/router.py --cost-report
```
