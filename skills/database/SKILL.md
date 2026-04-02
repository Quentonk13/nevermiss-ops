# Database Skill

SQLite database layer for the NeverMiss system. Stores leads, campaigns, emails, conversations, revenue, API usage, and daily metrics.

## Usage

```python
from skills.database.db_engine import add_lead, get_leads, log_email, log_api_usage
```

Tables are created automatically on first import. Data is stored at `/app/data/nevermiss.db` (override with `NEVERMISS_DB_DIR` env var).

## Key Functions

| Function | Purpose |
|---|---|
| `add_lead()` | Insert a new lead |
| `get_leads()` | Query leads with optional status/source filters |
| `update_lead_status()` | Change a lead's status |
| `get_lead_by_email()` | Look up a lead by email |
| `log_email()` | Record an outbound email |
| `log_api_usage()` | Track API calls and costs |
| `log_revenue()` | Record revenue events |
| `get_daily_metrics()` | Fetch metrics for a given day |
| `upsert_daily_metrics()` | Increment daily metric counters |
| `add_conversation()` | Start a conversation thread |
| `append_message()` | Add a message to a conversation |
| `execute()` | Run arbitrary read SQL |
