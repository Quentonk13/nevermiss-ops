---
name: crm-engine
description: "Central pipeline tracking, deduplication, status management, and suppression enforcement for NeverMiss. Use when: inserting leads, updating lead status, checking suppression list, running daily audits, or generating pipeline summaries. NOT for: sending emails, classifying replies, or making LLM calls."
metadata:
  openclaw:
    emoji: "📋"
    requires:
      bins:
        - python3
---

# CRM Engine

Central data layer for the NeverMiss autonomous revenue engine. All other skills write to and read from this system.

## When to Use

- Inserting or deduplicating a new lead
- Updating a lead's pipeline status
- Checking if an email is on the suppression list
- Running the nightly audit for stale leads
- Generating weekly pipeline summaries

## Pipeline Stages

```
new → contacted → replied → qualified → booked → demo_completed → closed → onboarding
  → objection_handled → (re-enters at replied or lost)
  → stalled → (re-enters or lost after 30 days)
  → lost (terminal)
```

All stage transitions are **deterministic** — hard-coded Python if/else logic, never LLM-inferred.

## Commands

```bash
# Run daily audit (flags leads stuck >14 days)
python3 skills/crm-engine/crm_engine.py audit

# Generate weekly pipeline summary
python3 skills/crm-engine/crm_engine.py summary
```

## Cron Setup

```bash
# Daily audit at 11:00 PM PT
openclaw cron add --name "crm-audit" --cron "0 23 * * *" --tz "America/Los_Angeles" --session isolated --message "Run CRM daily audit: python3 skills/crm-engine/crm_engine.py audit"

# Weekly summary on Sundays (feeds into performance-engine report)
openclaw cron add --name "crm-weekly" --cron "0 19 * * 0" --tz "America/Los_Angeles" --session isolated --message "Generate CRM weekly summary: python3 skills/crm-engine/crm_engine.py summary"
```

## Key Rules

- Leads can ONLY move forward in the pipeline (except objection_handled → replied, stalled → re-engaged)
- Every status change logged with timestamp, triggering skill, and reason
- No lead can exist in two stages simultaneously
- Suppression list is PERMANENT — once added, never removed without manual owner action
- Deduplication: exact email → fuzzy company+city+state (Levenshtein < 3) → exact phone
- Score gate: only leads with score >= 3 are inserted

## Data

- Primary store: `data/crm.json`
- Suppression list: `data/suppression_list.json`
- Logs: `data/system_log.jsonl`

## LLM Usage

None. Pure logic and data management. Zero API cost.
