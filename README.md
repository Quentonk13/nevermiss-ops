# NeverMiss Autonomous Revenue Engine — OpenClaw Build

AI-powered autonomous outbound sales system for NeverMiss, a $297/month missed-call text-back SaaS for trade contractors.

## Architecture

Built on **OpenClaw** (open-source AI agent framework, Node.js gateway). 14 skills operate autonomously with minimal owner involvement.

### LLM Routing
- **Groq/Llama 3.1 70B**: All bulk tasks (lead scoring, email generation, classification, QA)
- **Claude Sonnet**: Revenue-critical conversations only (interested leads, objections, post-demo follow-ups)

### Pipeline Flow
```
Source Leads → Clean & Deduplicate → Score (1-5) → Gate (≥3) →
Queue Outreach → QA Check → Send Email → Track →
Detect Reply → Classify → Route → Handle Conversation →
Push for Demo → Prep Owner → Post-Demo Follow-Up →
Close or Re-engage → Track Revenue → Analyze → Optimize
```

## Skills (14)

| # | Skill | Purpose | LLM |
|---|-------|---------|-----|
| 1 | `crm-engine` | Central pipeline, dedup, suppression | None |
| 2 | `qa-guard` | Outbound message QA gate | Groq (tone only) |
| 3 | `browser-agent` | Web interaction layer | Groq + Claude |
| 4 | `lead-pipeline` | Source, enrich, score leads | Groq |
| 5 | `outreach-sequencer` | Cold email sequences via Instantly.ai | Groq |
| 6 | `reply-handler` | Classify and route inbound replies | Groq + Claude |
| 7 | `sales-closer` | Post-booking pipeline, demo prep | Groq + Claude |
| 8 | `performance-engine` | Metrics, A/B testing, reports | Groq |
| 9 | `market-intel` | Competitor and market research | Groq |
| 10 | `email-optimizer` | Self-optimizing email system | Groq + Claude |
| 11 | `sales-optimizer` | Close rate improvement | Claude + Groq |
| 12 | `marketing-optimizer` | Channel allocation, positioning | Groq + Claude |
| 13 | `competitive-edge` | Product positioning, pricing intel | Claude + Groq |
| 14 | `ceo-bot` | Master orchestrator, nightly review | Claude + Groq |

## Setup

1. Copy `.env.example` to `.env` and fill in API keys:
   ```
   GROQ_API_KEY=
   ANTHROPIC_API_KEY=
   HUNTER_API_KEY=
   INSTANTLY_API_KEY=
   SERPAPI_KEY=
   FACEBOOK_SESSION_COOKIE=
   ```

2. Install dependencies:
   ```bash
   pip install playwright beautifulsoup4 requests
   playwright install chromium
   ```

3. Configure `config.json` with your Calendly link, signup link, and target geos.

4. Install skills in OpenClaw workspace.

## Data Storage

All runtime data stored in `data/` (gitignored):
- `crm.json` — Lead database
- `suppression_list.json` — Permanent no-contact list
- `system_log.jsonl` — All skill activity logs
- `inbox_warmup_tracker.json` — Inbox warmup state
- `performance_metrics.json` — Aggregated metrics
- `ceo_memory/` — CEO-bot's 3-layer memory system

## Security Lockdowns

- Send limits are hard-coded integers, not LLM-inferred
- Suppression list is permanent (no auto-removal)
- CRM transitions are deterministic if/else logic
- No autonomous domain registration, payment processing, or data deletion
- Claude API daily budget cap: $50
- Weekly optimizer Claude budget cap: $80
- Browser agent runs sandboxed (no purchases, no ToS, no posting)

## Target Market

US trade contractors (1-50 employees):
- **Tier 1**: HVAC, plumbing, electrical
- **Tier 2**: Roofing, general contractors, landscaping, pest control
- **Tier 3**: Painting, fencing, concrete, tree service, garage door, appliance repair

## Owner

Quenton — Gonevermiss@gmail.com
