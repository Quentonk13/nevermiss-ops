# Email Engine

Direct email sending engine with SMTP and Instantly.ai support.

## Setup

### Environment Variables

**SMTP (direct sending):**
```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=you@example.com
SMTP_PASS=your-password
SMTP_FROM=you@example.com
```

**Instantly.ai:**
```
INSTANTLY_API_KEY=your-api-key
```

**Optional:**
```
EMAIL_LOG_PATH=/app/data/email_log.json       # Default log location
EMAIL_ACCOUNT_CREATED=2026-01-15               # ISO date for warmup calculation
```

## Usage

```python
from skills.email_engine.email_engine import send_email, send_bulk, check_email_status, get_send_stats, record_bounce

# Single send
result = send_email(
    to="mike@acmeroofing.com",
    subject="Quick question, {{first_name}}",
    body="Hey {{first_name}}, I noticed {{company}} does {{trade}} in {{city}}...",
    variables={"first_name": "Mike", "company": "Acme Roofing", "trade": "roofing", "city": "Denver"},
    utc_offset=-7,
)

# Bulk send
recipients = [
    {"email": "mike@acme.com", "first_name": "Mike", "company": "Acme", "trade": "roofing", "city": "Denver", "utc_offset": -7},
    {"email": "jane@bestco.com", "first_name": "Jane", "company": "BestCo", "trade": "HVAC", "city": "Phoenix", "utc_offset": -7},
]
results = send_bulk(recipients, "Hey {{first_name}}", "We help {{trade}} companies in {{city}}...")

# Check status (useful for Instantly tracking)
status = check_email_status(result["id"])

# View stats
stats = get_send_stats()

# Record a bounce (call from webhook handler)
record_bounce(email_id="some-uuid")
```

## Features

### Method Selection
- `method="auto"` — picks Instantly if configured, falls back to SMTP
- `method="smtp"` — force SMTP
- `method="instantly"` — force Instantly.ai API

### Template Variables
Use `{{variable_name}}` in subject and body. Common variables: `first_name`, `company`, `trade`, `city`. Any key in the variables dict or recipient dict works.

### Sending Window
Emails only send between 8 AM and 5 PM in the recipient's local time. Pass `utc_offset` (hours from UTC) to enable this. Out-of-window sends return status `deferred` with `retry_after_seconds`.

### Warmup Limits
Daily send limits increase based on account age (set `EMAIL_ACCOUNT_CREATED`):

| Account Age | Daily Limit |
|-------------|-------------|
| 0-2 days    | 5           |
| 3-6 days    | 10          |
| 7-13 days   | 25          |
| 14-20 days  | 50          |
| 21-29 days  | 75          |
| 30-44 days  | 100         |
| 45-59 days  | 150         |
| 60-89 days  | 250         |
| 90+ days    | 500         |

### Bounce Tracking
- Call `record_bounce(email_id)` when you receive a bounce notification
- If bounce rate exceeds 5% (over the last 100 sends), all sending auto-pauses
- `get_send_stats()` reports current bounce rate and pause status

### Send Log
All sends are logged to `/app/data/email_log.json` (configurable via `EMAIL_LOG_PATH`). Each entry includes: id, to, subject, method, status, timestamp, error details.

## Quick Test

```bash
python skills/email-engine/email_engine.py
```

Prints current stats and runs a template rendering test (no emails sent).
