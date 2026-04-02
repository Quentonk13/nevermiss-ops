# Revenue Monitor

**Never be surprised by your sales data again.**

Daily revenue tracking across Gumroad, KDP, and Etsy. Automatic alerts when something spikes or drops. Weekly and monthly reports delivered to Telegram.

## What It Tracks

- **Gumroad** — Sales count, revenue, products sold, top referrers
- **Amazon KDP** — Units ordered, royalties, Kindle Unlimited pages (KENP)
- **Etsy** — Orders, gross revenue, net after fees

## Features

- 📊 Daily summary every morning
- 🚀 Spike alert when daily revenue exceeds 3x your average
- ⚠️ Drop alert when you go N days without a sale
- 📈 Weekly report every Sunday
- 📅 Month-end report with trends and insights
- 💬 Telegram alerts (configurable)
- 📁 Revenue log stored as JSON for your records

## Quick Start

1. Install the skill
2. Your agent will ask for API keys (Gumroad token, Etsy API key)
3. Say "Revenue report" to get today's summary

## Example Daily Output

```
📊 REVENUE SUMMARY — Tuesday, March 18

GUMROAD
  Sales: 3 | Revenue: $29.97
  • Prayer Journal: 2 @ $9.99
  • Scripture Cards: 1 @ $9.99

KDP
  Units: 1 | Royalties: ~$3.50

ETSY
  Orders: 0 | Revenue: $0.00

─────────────────────────
TODAY TOTAL: $33.47
MTD TOTAL: $187.23
MTD GOAL: $500.00 (37% to goal)
─────────────────────────
7-DAY AVG: $21.40/day
30-DAY TOTAL: $412.80
```

## API Requirements

| Platform | What You Need |
|----------|---------------|
| Gumroad | API access token (Settings → Advanced → API) |
| KDP | AgentReach session OR manual CSV export |
| Etsy | API key from developer.etsy.com |

## Built By

Ten Life Creatives — built for our own digital products business.
Real revenue data. Real alerts. No fluff.
