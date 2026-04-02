# SKILL: Revenue Monitor

## Purpose
Track daily revenue across Gumroad, KDP, and Etsy. Alert on anomalies (sales spikes, drops, or zero-revenue days). Generate daily and weekly summaries. Make sure no sale goes unnoticed and no revenue problem goes undetected.

---

## Configuration (Set Once)

Check `skills/revenue-monitor/config.json`. If not present, ask:

1. **Gumroad:** Do you have a Gumroad API access token? (Settings → Advanced → API)
2. **KDP:** Do you have KDP sales tracking set up? (Manual CSV export or AgentReach session)
3. **Etsy:** Do you have an Etsy API key? (developer.etsy.com)
4. **Telegram alert chat ID:** For revenue alerts (leave blank to disable)
5. **Revenue alert thresholds:**
   - Alert if daily sales exceed $[X] (spike alert)
   - Alert if no sales for [X] consecutive days (drop alert)
   - Weekly revenue goal: $[X]
6. **Check frequency:** Daily at [time] / On demand only

Save to `skills/revenue-monitor/config.json`.

---

## Daily Revenue Check

Run every day (or when triggered). Pull data from all configured platforms.

### Gumroad Check

```python
# Gumroad REST API v2
# GET https://api.gumroad.com/v2/sales
# Headers: Authorization: Bearer {GUMROAD_ACCESS_TOKEN}
# Params: after={yesterday_date}, before={today_date}

import requests
from datetime import date, timedelta

yesterday = (date.today() - timedelta(days=1)).isoformat()
today = date.today().isoformat()

response = requests.get(
    "https://api.gumroad.com/v2/sales",
    headers={"Authorization": f"Bearer {GUMROAD_TOKEN}"},
    params={"after": yesterday, "before": today}
)

sales = response.json().get("sales", [])
```

Extract per sale:
- `product_name`
- `price` (in cents — divide by 100)
- `created_at`
- `variants_and_quantity`
- `referrer` (where the sale came from)

Compile into:
```
GUMROAD — [Date]
Sales: [X]
Revenue: $[X.XX]
Products sold:
  - [Product A]: [X] units @ $[X]
  - [Product B]: [X] units @ $[X]
Top referrer: [URL or "direct"]
```

### KDP Check (via AgentReach or Manual)

If AgentReach is configured with a KDP session:
```bash
agentreach kdp sales --days 1
```

If not, check `~/.agentreach/kdp-sales-cache/` for last exported data.

If no automation: prompt the user to export KDP sales report and paste/share it.

KDP data to extract:
- Units ordered per title
- Estimated royalties
- KENP (Kindle Unlimited pages read)

```
KDP — [Date]
Units ordered: [X]
Estimated royalties: $[X.XX]
KENP pages: [X] (~$[X.XX])
Top title: [Title name]
```

### Etsy Check (if configured)

```python
# Etsy API v3
# GET https://openapi.etsy.com/v3/application/shops/{shop_id}/receipts
# Headers: x-api-key: {ETSY_API_KEY}

response = requests.get(
    f"https://openapi.etsy.com/v3/application/shops/{ETSY_SHOP_ID}/receipts",
    headers={"x-api-key": ETSY_API_KEY},
    params={"min_created": yesterday_timestamp, "max_created": today_timestamp}
)
```

Compile:
```
ETSY — [Date]
Orders: [X]
Revenue: $[X.XX] (before Etsy fees)
Net revenue: ~$[X.XX] (after ~6.5% transaction fee)
Top product: [Product name]
```

---

## Daily Revenue Summary Format

```
📊 REVENUE SUMMARY — [Day, Date]

GUMROAD
  Sales: [X] | Revenue: $[X.XX]
  [Product breakdown]

KDP
  Units: [X] | Royalties: ~$[X.XX]
  [Title breakdown]

ETSY
  Orders: [X] | Revenue: $[X.XX]
  [Product breakdown]

─────────────────────────
TODAY TOTAL: $[X.XX]
MTD TOTAL: $[X.XX]
MTD GOAL: $[X.XX] ([X]% to goal)
─────────────────────────

YESTERDAY: $[X.XX] | CHANGE: [+/- X%]
7-DAY AVG: $[X.XX]/day
30-DAY TOTAL: $[X.XX]
```

---

## Anomaly Detection & Alerts

### Spike Alert (Positive)
Trigger: Today's revenue exceeds 3x the 7-day average

```
🚀 REVENUE SPIKE ALERT — [Date]

Today: $[X.XX] (vs 7-day avg of $[X.XX])
That's [X]x your normal daily revenue!

Top source: [Platform] — [Product]
Possible cause: [Check if you ran any promotion, got a feature, etc.]

Action: Consider reposting what worked today. Check referrer data.
```

### Drop Alert (Concern)
Trigger: Zero sales for N consecutive days (configured threshold, default 3)

```
⚠️ REVENUE ALERT — [X] Days No Sales

Last sale: [Date] — [Product] on [Platform]
Days since: [X]

Possible causes to investigate:
• Product listings active? (Check all platforms)
• Any SEO/search ranking drops?
• Seasonal dip?
• Payment method issues?

Recommended action: Run a quick promotion or share a product link.
```

### Weekly Drop Alert
Trigger: This week's revenue is more than 30% below last week

```
📉 WEEKLY REVENUE DOWN [X]%

This week: $[X.XX]
Last week: $[X.XX]
Difference: -$[X.XX]

[Breakdown by platform showing where the drop happened]

Investigate: [Platform where the biggest drop occurred]
```

---

## Weekly Revenue Report

Every Sunday (or when triggered: "weekly revenue report"):

```
📈 WEEKLY REVENUE REPORT — Week of [Date]

TOTAL THIS WEEK: $[X.XX]
vs Last Week: $[X.XX] ([+/-X%])
vs Goal ($[X]): [X]% achieved

PLATFORM BREAKDOWN:
  Gumroad: $[X.XX] ([X] sales)
  KDP:     $[X.XX] ([X] units + KENP)
  Etsy:    $[X.XX] ([X] orders)

TOP PERFORMERS:
  1. [Product] — $[X.XX] ([X] units)
  2. [Product] — $[X.XX] ([X] units)
  3. [Product] — $[X.XX] ([X] units)

NEW PRODUCTS LAUNCHED THIS WEEK: [X]

BEST DAY: [Day] — $[X.XX]
WORST DAY: [Day] — $[X.XX]

MONTH TO DATE: $[X.XX] / $[Goal] goal ([X]%)

INSIGHTS:
• [One observation about what worked]
• [One observation about what didn't]
• [One recommendation for next week]
```

---

## Revenue Log Format

Log all data to `systems/feedback/revenue-data.json`:

```json
{
  "log": [
    {
      "date": "2026-03-18",
      "gumroad": {
        "sales_count": 0,
        "revenue": 0.00,
        "products": []
      },
      "kdp": {
        "units": 0,
        "royalties": 0.00,
        "kenp_pages": 0
      },
      "etsy": {
        "orders": 0,
        "revenue": 0.00
      },
      "total": 0.00
    }
  ]
}
```

---

## Month-End Report

On the last day of each month:

```
📅 MONTHLY REVENUE REPORT — [Month Year]

TOTAL REVENUE: $[X.XX]
vs Prior Month: $[X.XX] ([+/-X%])

BREAKDOWN:
  Gumroad: $[X.XX] ([X]% of total)
  KDP:     $[X.XX] ([X]% of total)
  Etsy:    $[X.XX] ([X]% of total)

PRODUCTS (ranked by revenue):
  1. [Product] — $[X.XX]
  2. [Product] — $[X.XX]
  ...

DAYS WITH SALES: [X] / [X] days
BEST DAY: [Date] — $[X.XX]
AVERAGE DAY: $[X.XX]

GOAL STATUS: $[X.XX] / $[Goal] = [X]%
NEXT MONTH GOAL: $[X.XX]

ACTION ITEMS FOR NEXT MONTH:
• [Based on data — what to double down on]
• [What underperformed and why]
• [New products or promotions to try]
```

---

## Telegram Alert Format

When sending to Telegram, keep it short:

Daily (sent each morning):
```
💰 Yesterday: $X.XX
📦 Gumroad: X sales | KDP: X units | Etsy: X orders
📈 MTD: $X.XX
```

Spike alert: Send full spike alert message (see above)
Drop alert: Send full drop alert message (see above)

---

## Commands / Triggers
- **"Revenue report"** → Today's daily summary
- **"Weekly report"** → Full weekly breakdown
- **"Monthly report"** → Full month summary
- **"How are sales?"** → Quick daily summary
- **"Gumroad sales"** → Gumroad only
- **"KDP sales"** → KDP only
- **"How much this month?"** → MTD total
- **"Revenue last 30 days"** → 30-day summary
- **"Set revenue goal $X"** → Update config
- **"Any alerts?"** → Check for anomalies now
