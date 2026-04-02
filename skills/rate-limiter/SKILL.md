---
name: rate-limiter
description: "API rate limiting, usage tracking, and adaptive backoff for all external provider calls (anthropic, groq, apollo, instantly, google). Use when: checking if an API call is allowed, recording a completed call, viewing usage stats, or resetting a provider. NOT for: making API calls directly, managing API keys, or billing."
metadata:
  openclaw:
    emoji: "⏱"
    requires:
      bins:
        - python3
---

# Rate Limiter

Centralized rate-limit enforcement for every external API provider used by NeverMiss. All skills that make outbound API calls should check this limiter before calling and record usage afterward.

## When to Use

- Before any API call: `can_call(provider)` or `wait_if_needed(provider)`
- After any API call: `record_call(provider, tokens_in, tokens_out, cost)`
- Reviewing spend/volume: `get_usage_stats()`
- After a provider outage or config change: `reset_provider(provider)`
- Tuning throughput: `set_limit(provider, rpm)`

## Default Rate Limits

| Provider  | RPM |
|-----------|-----|
| anthropic | 15  |
| groq      | 30  |
| apollo    | 20  |
| instantly | 10  |
| google    | 5   |

## Integration Pattern

```python
from skills.rate_limiter.rate_limiter import can_call, record_call, wait_if_needed

# Option A: non-blocking check
if can_call("anthropic"):
    resp = call_anthropic(...)
    record_call("anthropic", tokens_in=resp.input_tokens, tokens_out=resp.output_tokens, cost=0.003)

# Option B: blocking wait
wait_if_needed("anthropic")
resp = call_anthropic(...)
record_call("anthropic", tokens_in=resp.input_tokens, tokens_out=resp.output_tokens, cost=0.003)
```

## Backoff Behavior

When a provider hits its RPM ceiling, the effective limit is automatically halved for 10 minutes. This prevents burst-retry storms and lets quotas recover. The halved limit is visible in `get_usage_stats()` (`in_backoff: true`).

## Persistence

State is stored in `/app/data/rate_limits.json`. Every 50 global calls a summary line is appended to `/app/data/ceo_memory/daily_notes/YYYY-MM-DD.md`.

## CLI

```bash
python skills/rate-limiter/rate_limiter.py status   # show all providers
python skills/rate-limiter/rate_limiter.py reset groq
python skills/rate-limiter/rate_limiter.py test      # quick smoke test
```
