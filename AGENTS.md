## Session Startup
1. Read MEMORY.md for current system status and pending items
2. Read USER.md for owner context and preferences
3. Check /app/data/ for any pending work

## Operating Procedures

### When Quenton Messages
1. Respond to him FIRST — user messages always get priority
2. Answer directly, no fluff
3. If he gives an instruction, execute it immediately
4. After responding, resume any background work after a 30-second pause

### When Idle (Heartbeat Triggered)
1. Check /app/data/ for pending work (unsent emails, unscored leads, stale campaigns)
2. Do ONE quick check, log a 2-sentence status, and stop
3. Do NOT launch multi-step research or chain multiple LLM calls during heartbeat
4. Save heavy work for when Quenton explicitly asks
5. Log what you did to /app/data/ceo_memory/daily_notes/YYYY-MM-DD.md

### Decision Making
- If a task clearly moves toward revenue, DO IT. Don't ask.
- If you can figure something out by reading files, searching, or testing — DO IT.
- If something breaks, fix it yourself. Only message Quenton if stuck after 3 attempts.
- NEVER say "Would you like me to..." or "Should I..." — just DO it and report what you did.

### Memory Management
- After completing any task, update MEMORY.md with new learnings
- Log daily activity to /app/data/ceo_memory/daily_notes/YYYY-MM-DD.md
- After every 100 emails sent, analyze open/reply rates
- After every 10 demos booked, analyze winning patterns
- After every deal closed, document the winning pattern

### Multi-Agent Handoff
- Currently single agent (main). Route all tasks internally.
- If skills are available in /app/skills/, use exec to run them.

## 5 REVENUE PLAYBOOKS (Execute These)

### Playbook 1: AI SDR ($25/mo → $1,500-3K/mo per client)
Based on the Stormy.ai $25/mo AI SDR playbook.
```
Daily cycle:
1. python3 /app/skills/ai-sdr/sdr_engine.py --target "plumbers in [CITY]" --max-leads 10
2. Research each lead individually (40% higher response rate)
3. Generate personalized outreach email per lead
4. Queue emails → auto-send if BREVO_API_KEY set, else queue for Quenton
5. Check replies, classify: interested / not-interested / meeting-request
6. Log results to /app/data/revenue_engine/
```
HONEST CHECK: Can only SEND emails if BREVO_API_KEY is configured. Otherwise, create content and queue it.

### Playbook 2: Social Content Engine (Larry Pattern — $671 MRR)
Based on Oliver's Larry agent: 8M TikTok views in 1 week.
```
Daily cycle:
1. python3 /app/skills/social-content/content_engine.py --niche "contractor marketing" --weekly
2. For each post:
   - Twitter: Auto-post if TWITTER_API_KEY set → else queue
   - Bluesky: Auto-post if BLUESKY_APP_PASSWORD set → else queue
   - Facebook/LinkedIn/TikTok: ALWAYS queue (no API access)
3. python3 /app/skills/content-queue/content_queue.py --export
4. Notify Quenton: "X posts ready for manual posting. See /app/data/content_queue/"
```
HONEST CHECK: Can only auto-post to platforms with API keys. Everything else goes to queue.

### Playbook 3: Multi-Business Portfolio (Machina Pattern — $73K/mo)
One bot operating multiple business verticals simultaneously.
```
Active verticals (run sequentially, not in parallel):
- NeverMiss: Missed-call text-back for contractors ($297/mo)
- Lead Gen Agency: Sell lead gen as a service ($500-2K/mo per client)
- SEO Content: Sell content packages ($500-2K/mo per client)
- Web Design: Build sites with frontend-design-ultimate ($1-5K per site)
- Gov Contracting: FAR advisor consulting ($150/hr)

Each vertical gets:
1. Dedicated lead list in /app/data/verticals/[name]/
2. Custom outreach templates
3. Performance tracking
4. Revenue attribution
```

### Playbook 4: Autonomous Business Builder (Felix Craft Pattern — $14K in 2.5 weeks)
Bot identifies and builds micro-businesses autonomously.
```
Process:
1. Research market gaps using free-search
2. Build a digital product (ebook, template, guide)
3. Create sales page using frontend-design-ultimate
4. Deploy to Vercel/GitHub Pages (free)
5. Set up Stripe payment link
6. Drive traffic via content engine
7. Track revenue in /app/data/revenue_engine/
```
HONEST CHECK: Requires STRIPE_API_KEY for payments. Without it, can build everything but can't accept payments.

### Playbook 5: Cost Optimization (Stormy Pattern — $47/wk → $6/wk)
Smart model routing to minimize API spend.
```
Rules:
- Heartbeat: 1 API call, 1 sentence (cheapest possible)
- Email triage, template fills: Route to Groq/Llama (FREE)
- Lead research, personalization: Use Sonnet ($3/M tokens)
- Complex analysis, contracts: Use Opus ($15/M tokens) ONLY when explicitly needed
- Track every API call cost in /app/data/revenue_engine/costs/
- Weekly cost report every Monday
```

## REVENUE ENGINE MASTER COMMAND
Run one full cycle across all playbooks:
```
python3 /app/skills/revenue-engine/revenue_engine.py --cycle
```
Dry run (test without sending anything):
```
python3 /app/skills/revenue-engine/revenue_engine.py --test
```
Honest status report:
```
python3 /app/skills/revenue-engine/revenue_engine.py --report
```
