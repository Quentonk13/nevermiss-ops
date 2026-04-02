---
name: analytics
description: "Reporting and analytics engine — daily/weekly reports, funnel analysis, revenue forecasting, API cost tracking. Use for any metrics or performance questions."
metadata:
  openclaw:
    emoji: "📊"
    requires:
      bins:
        - python3
---

# Analytics Engine

Generates formatted reports from the NeverMiss SQLite database for delivery via Telegram.

## Functions
- `daily_report()` — Today's metrics summary
- `weekly_report()` — 7-day trends and comparisons
- `funnel_analysis()` — Lead → Email → Reply → Demo → Close conversion rates
- `api_cost_report()` — API spend by provider
- `top_performing_templates()` — Best email templates by open/reply rate
- `revenue_forecast()` — MRR projection based on pipeline

## Usage
```bash
python3 skills/analytics/analytics_engine.py --daily
python3 skills/analytics/analytics_engine.py --weekly
python3 skills/analytics/analytics_engine.py --funnel
python3 skills/analytics/analytics_engine.py --api-costs
python3 skills/analytics/analytics_engine.py --templates
python3 skills/analytics/analytics_engine.py --forecast
```
