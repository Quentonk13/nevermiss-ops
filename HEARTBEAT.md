## On Each Heartbeat

Run the autonomous scheduler. ONE command. That's it.

```bash
python3 /app/skills/autonomous/scheduler.py --run
```

The scheduler checks the current UTC hour and runs the right task:
- 06:00 UTC → Morning brief (3 lines to Quenton)
- 08:00 UTC → Machina cycle (run ALL business verticals)
- 10:00 UTC → SDR cycle (find leads, research, queue outreach)
- 12:00 UTC → Felix Craft cycle (build/launch digital products)
- 14:00 UTC → Content cycle (create posts, auto-post/queue)
- 18:00 UTC → Audit (check replies, CRM, generate report)
- 22:00 UTC → Evening summary (5 lines to Quenton)
- 02:00 UTC → Sleep (HEARTBEAT_OK)

Target markets rotate daily across Dallas, Houston, Austin — plumbers, HVAC, electricians, roofers, general contractors.

### Force Run Any Task
```bash
python3 /app/skills/autonomous/scheduler.py --force sdr
python3 /app/skills/autonomous/scheduler.py --force content
python3 /app/skills/autonomous/scheduler.py --force felix
python3 /app/skills/autonomous/scheduler.py --force machina
python3 /app/skills/autonomous/scheduler.py --force audit
```

### Rules
- Keep response under 200 words
- If rate limited, stop and log
- NEVER claim you posted/sent something without API confirmation
- Log everything to /app/data/ceo_memory/daily_notes/

### Alert Immediately On
- Interested reply from a lead
- Demo booked
- Deal closed
- System failure
