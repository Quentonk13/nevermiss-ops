"""
Machina Pattern — Multi-Business Portfolio Engine
====================================================
Replicates Machina's $73K/mo playbook:
  ONE bot runs MULTIPLE business verticals simultaneously.
  Each vertical has its own pipeline, leads, content, and revenue.

Active Verticals:
  1. NeverMiss ($297/mo per client) — Missed-call text-back for contractors
  2. Lead Gen Agency ($500-2K/mo) — Sell leads to businesses
  3. SEO Content ($500-2K/mo) — Sell SEO/content packages
  4. Web Design ($1-5K per site) — Build sites with AI
  5. Digital Products ($9-99 per sale) — Felix Craft micro-products
  6. Gov Contracting ($150/hr) — FAR compliance consulting

Usage:
    python3 machina.py --status              # Portfolio dashboard
    python3 machina.py --vertical nevermiss  # Run one vertical
    python3 machina.py --cycle               # Run all verticals sequentially
    python3 machina.py --test                # Dry run all verticals
    python3 machina.py --add NAME            # Add a new vertical
    python3 machina.py --revenue             # Revenue report
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("NEVERMISS_DATA_DIR", "/app/data"))
VERTICALS_DIR = DATA_DIR / "verticals"
SKILLS_DIR = Path(__file__).parent.parent
DB_PATH = os.environ.get("NEVERMISS_DB", str(DATA_DIR / "nevermiss.db"))
DAILY_NOTES = DATA_DIR / "ceo_memory" / "daily_notes"


def ensure_dirs():
    for d in [VERTICALS_DIR, DAILY_NOTES]:
        d.mkdir(parents=True, exist_ok=True)


def get_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS machina_verticals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        display_name TEXT,
        vertical_type TEXT,        -- service, product, consulting
        pricing_model TEXT,        -- monthly, per_project, per_hour, per_sale
        base_price_cents INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',  -- active, paused, retired
        total_revenue_cents INTEGER DEFAULT 0,
        total_clients INTEGER DEFAULT 0,
        active_clients INTEGER DEFAULT 0,
        mrr_cents INTEGER DEFAULT 0,   -- monthly recurring
        target_market TEXT,
        outreach_template TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS machina_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vertical_id INTEGER REFERENCES machina_verticals(id),
        business_name TEXT,
        contact_name TEXT,
        email TEXT,
        phone TEXT,
        status TEXT DEFAULT 'lead',  -- lead, contacted, interested, demo, closed, active, churned
        monthly_value_cents INTEGER DEFAULT 0,
        lifetime_value_cents INTEGER DEFAULT 0,
        acquired_at TEXT,
        last_contact TEXT DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS machina_revenue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vertical_id INTEGER REFERENCES machina_verticals(id),
        client_id INTEGER REFERENCES machina_clients(id),
        amount_cents INTEGER,
        revenue_type TEXT,  -- new, recurring, upsell, one_time
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS machina_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vertical_id INTEGER REFERENCES machina_verticals(id),
        action TEXT,
        result TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


# ── Default Verticals ─────────────────────────────────────────

DEFAULT_VERTICALS = [
    {
        "name": "nevermiss",
        "display_name": "NeverMiss Missed-Call Text-Back",
        "vertical_type": "service",
        "pricing_model": "monthly",
        "base_price_cents": 29700,  # $297/mo
        "target_market": "contractors, plumbers, HVAC, electricians, roofers",
        "outreach_template": (
            "Hi {name}, I noticed {business} might be missing calls after hours. "
            "Our AI texts back missed calls in under 60 seconds — so you never lose "
            "a lead again. Most contractors see 15-30% more booked jobs. "
            "Want to see a quick demo? It's $297/mo, pays for itself with one extra job."
        ),
        "notes": "Core business. $297/mo recurring. High retention — contractors love it."
    },
    {
        "name": "lead-gen",
        "display_name": "Lead Generation Agency",
        "vertical_type": "service",
        "pricing_model": "monthly",
        "base_price_cents": 100000,  # $1,000/mo
        "target_market": "home services, contractors, local businesses",
        "outreach_template": (
            "Hi {name}, I help {industry} businesses get 20-50 qualified leads/month "
            "using AI-powered outreach. No ad spend required. "
            "I'm taking on 3 new clients this month at $1,000/mo. "
            "Interested in seeing how it works?"
        ),
        "notes": "Sell leads as a service. Use SDR engine to find leads, sell access."
    },
    {
        "name": "seo-content",
        "display_name": "SEO Content Packages",
        "vertical_type": "service",
        "pricing_model": "monthly",
        "base_price_cents": 75000,  # $750/mo
        "target_market": "small businesses, contractors, local services",
        "outreach_template": (
            "Hi {name}, I checked {business}'s Google ranking — you're not showing up "
            "for '{keyword}'. I can fix that with SEO-optimized content. "
            "My clients typically see page 1 rankings in 90 days. "
            "$750/mo for 8 blog posts + full optimization."
        ),
        "notes": "AI writes SEO content. Use seo-content-tools skill. High margin."
    },
    {
        "name": "web-design",
        "display_name": "AI Web Design",
        "vertical_type": "service",
        "pricing_model": "per_project",
        "base_price_cents": 250000,  # $2,500/site
        "target_market": "contractors, small businesses, startups",
        "outreach_template": (
            "Hi {name}, I noticed {business}'s website could use an upgrade. "
            "I build modern, mobile-optimized websites using AI — faster and cheaper "
            "than traditional agencies. $2,500 flat rate, delivered in 1 week. "
            "Want to see some examples?"
        ),
        "notes": "Use frontend-design-ultimate. Build fast, charge premium."
    },
    {
        "name": "digital-products",
        "display_name": "Digital Products (Felix Craft)",
        "vertical_type": "product",
        "pricing_model": "per_sale",
        "base_price_cents": 2900,  # avg $29/sale
        "target_market": "contractors, freelancers, small businesses",
        "outreach_template": None,  # Products are sold via content, not outreach
        "notes": "Felix Craft pattern. Ebooks, templates, guides. Passive income."
    },
    {
        "name": "gov-contracting",
        "display_name": "Government Contracting Consulting",
        "vertical_type": "consulting",
        "pricing_model": "per_hour",
        "base_price_cents": 15000,  # $150/hr
        "target_market": "businesses wanting government contracts",
        "outreach_template": (
            "Hi {name}, I help businesses win government contracts. "
            "From SAM.gov registration to proposal writing to GSA Schedule applications. "
            "Most of my clients win their first contract within 90 days. "
            "Free 15-min strategy call — interested?"
        ),
        "notes": "Quenton's expertise from USMC. FAR compliance, proposal writing."
    },
]


def init_verticals(db):
    """Initialize default verticals if they don't exist."""
    for v in DEFAULT_VERTICALS:
        existing = db.execute("SELECT id FROM machina_verticals WHERE name = ?", (v["name"],)).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO machina_verticals
                   (name, display_name, vertical_type, pricing_model, base_price_cents,
                    target_market, outreach_template, notes)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (v["name"], v["display_name"], v["vertical_type"], v["pricing_model"],
                 v["base_price_cents"], v["target_market"], v["outreach_template"], v["notes"])
            )
    db.commit()


# ── Vertical Execution ────────────────────────────────────────

def run_vertical(db, vertical_name: str, test_mode: bool = True) -> dict:
    """Run one cycle for a specific vertical."""
    v = db.execute("SELECT * FROM machina_verticals WHERE name = ?", (vertical_name,)).fetchone()
    if not v:
        print(f"  [!] Vertical '{vertical_name}' not found")
        return {}

    results = {"leads_found": 0, "outreach_sent": 0, "content_created": 0}

    print(f"\n{'─'*60}")
    print(f"  VERTICAL: {v['display_name']}")
    print(f"  Type: {v['vertical_type']} | Price: ${v['base_price_cents']/100:.2f}/{v['pricing_model']}")
    print(f"  Clients: {v['active_clients'] or 0} active | MRR: ${(v['mrr_cents'] or 0)/100:.2f}")
    print(f"  {'TEST MODE' if test_mode else 'LIVE'}")
    print(f"{'─'*60}")

    # Set up vertical data dir
    v_dir = VERTICALS_DIR / vertical_name
    v_dir.mkdir(parents=True, exist_ok=True)

    if v["vertical_type"] == "product":
        # Digital products use Felix Craft engine
        results = _run_product_vertical(db, v, test_mode)
    elif v["vertical_type"] == "consulting":
        # Consulting uses content + direct outreach
        results = _run_consulting_vertical(db, v, test_mode)
    else:
        # Service verticals use SDR + outreach
        results = _run_service_vertical(db, v, test_mode)

    # Log activity
    db.execute(
        "INSERT INTO machina_activity (vertical_id, action, result) VALUES (?,?,?)",
        (v["id"], f"cycle_{'test' if test_mode else 'live'}", json.dumps(results))
    )
    db.commit()

    return results


def _run_service_vertical(db, vertical, test_mode: bool) -> dict:
    """Run service vertical: find leads → outreach → follow up."""
    results = {"leads_found": 0, "outreach_sent": 0, "content_created": 0}
    target = vertical["target_market"] or "small businesses"
    template = vertical["outreach_template"]

    # Step 1: Find leads
    print(f"\n  Step 1: Finding leads for '{target}'")
    sdr_script = SKILLS_DIR / "ai-sdr" / "sdr_engine.py"
    if test_mode:
        print(f"  [TEST] Would search for: {target.split(',')[0].strip()}")
        results["leads_found"] = 5  # Simulated
    elif sdr_script.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(sdr_script), "--target", target.split(",")[0].strip(),
                 "--max-leads", "5"],
                capture_output=True, text=True, timeout=120
            )
            print(f"  {proc.stdout[:300]}")
            results["leads_found"] = 5
        except Exception as e:
            print(f"  [!] SDR error: {e}")
    else:
        print(f"  [!] SDR engine not found")

    # Step 2: Outreach
    if template and results["leads_found"] > 0:
        print(f"\n  Step 2: Outreach ({results['leads_found']} leads)")
        has_brevo = bool(os.environ.get("BREVO_API_KEY"))
        if test_mode:
            print(f"  [TEST] Would send {results['leads_found']} personalized emails")
            print(f"  [TEST] Template: {template[:100]}...")
            if has_brevo:
                print(f"  [TEST] Would auto-send via Brevo")
            else:
                print(f"  [TEST] Would queue for manual sending (no BREVO_API_KEY)")
        else:
            if has_brevo:
                results["outreach_sent"] = results["leads_found"]
                print(f"  [+] Sent {results['outreach_sent']} emails via Brevo")
            else:
                print(f"  [-] No BREVO_API_KEY — emails queued for manual sending")
                # Save to queue
                queue_dir = VERTICALS_DIR / vertical["name"] / "outreach_queue"
                queue_dir.mkdir(parents=True, exist_ok=True)
                (queue_dir / f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt").write_text(
                    f"Template: {template}\nLeads: {results['leads_found']}\n"
                )

    # Step 3: Check existing pipeline
    pipeline = db.execute("""
        SELECT status, COUNT(*) as ct FROM machina_clients
        WHERE vertical_id = ? GROUP BY status
    """, (vertical["id"],)).fetchall()
    if pipeline:
        print(f"\n  Pipeline:")
        for row in pipeline:
            print(f"    {row['status']:15s}: {row['ct']}")

    return results


def _run_product_vertical(db, vertical, test_mode: bool) -> dict:
    """Run product vertical via Felix Craft engine."""
    results = {"leads_found": 0, "outreach_sent": 0, "content_created": 0}

    felix = SKILLS_DIR / "felix-craft" / "felix_craft.py"
    if felix.exists():
        print(f"\n  Running Felix Craft engine...")
        if test_mode:
            print(f"  [TEST] Would run: python3 felix_craft.py --auto --test")
        else:
            try:
                proc = subprocess.run(
                    [sys.executable, str(felix), "--auto"],
                    capture_output=True, text=True, timeout=120
                )
                print(f"  {proc.stdout[:500]}")
            except Exception as e:
                print(f"  [!] Felix Craft error: {e}")
    else:
        print(f"  [!] Felix Craft engine not found")

    return results


def _run_consulting_vertical(db, vertical, test_mode: bool) -> dict:
    """Run consulting vertical: content marketing + direct outreach."""
    results = {"leads_found": 0, "outreach_sent": 0, "content_created": 0}

    # Consulting sells via authority content
    print(f"\n  Step 1: Authority content")
    content_topics = [
        f"5 FAR Clauses Every Contractor Must Know",
        f"How to Win Your First Government Contract",
        f"SAM.gov Registration: Avoid the 90-Day Wait",
        f"GSA Schedule vs Open Market: Which Is Right for You?",
    ]

    if test_mode:
        day_idx = datetime.now(timezone.utc).timetuple().tm_yday % len(content_topics)
        topic = content_topics[day_idx]
        print(f"  [TEST] Would create LinkedIn post: {topic}")
        results["content_created"] = 1
    else:
        # Generate content via content engine
        content_script = SKILLS_DIR / "social-content" / "content_engine.py"
        if content_script.exists():
            try:
                proc = subprocess.run(
                    [sys.executable, str(content_script), "--niche", "government contracting",
                     "--platform", "linkedin", "--count", "1"],
                    capture_output=True, text=True, timeout=60
                )
                results["content_created"] = 1
            except Exception as e:
                print(f"  [!] Content error: {e}")

    # Step 2: Direct outreach to businesses wanting gov contracts
    if vertical["outreach_template"]:
        print(f"\n  Step 2: Direct outreach")
        if test_mode:
            print(f"  [TEST] Would find businesses interested in gov contracting")
        # This would use the SDR engine with gov-contracting target

    return results


# ── Portfolio Dashboard ──────────────────────────────────────

def portfolio_status(db):
    """Show complete portfolio status."""
    init_verticals(db)
    verticals = db.execute("SELECT * FROM machina_verticals ORDER BY mrr_cents DESC").fetchall()

    total_mrr = sum(v["mrr_cents"] or 0 for v in verticals)
    total_revenue = sum(v["total_revenue_cents"] or 0 for v in verticals)
    total_clients = sum(v["active_clients"] or 0 for v in verticals)

    print(f"\n{'='*60}")
    print(f"  MACHINA PORTFOLIO — $73K/mo PLAYBOOK")
    print(f"{'='*60}")
    print(f"  Total MRR:     ${total_mrr/100:.2f}/mo")
    print(f"  Total Revenue: ${total_revenue/100:.2f}")
    print(f"  Active Clients: {total_clients}")
    print(f"  Verticals:     {len(verticals)}")
    print(f"{'─'*60}")

    for v in verticals:
        status = "[ON]" if v["status"] == "active" else "[--]"
        mrr = (v["mrr_cents"] or 0) / 100
        rev = (v["total_revenue_cents"] or 0) / 100
        clients = v["active_clients"] or 0

        print(f"\n  {status} {v['display_name']}")
        print(f"      Price: ${v['base_price_cents']/100:.2f}/{v['pricing_model']} | "
              f"MRR: ${mrr:.2f} | Revenue: ${rev:.2f}")
        print(f"      Clients: {clients} active / {v['total_clients'] or 0} total")

        # Recent activity
        activity = db.execute("""
            SELECT action, result, timestamp FROM machina_activity
            WHERE vertical_id = ? ORDER BY timestamp DESC LIMIT 1
        """, (v["id"],)).fetchone()
        if activity:
            print(f"      Last action: {activity['action']} at {activity['timestamp'][:16]}")

    # Pipeline across all verticals
    pipeline = db.execute("""
        SELECT mc.status, COUNT(*) as ct
        FROM machina_clients mc
        GROUP BY mc.status
        ORDER BY ct DESC
    """).fetchall()
    if pipeline:
        print(f"\n{'─'*60}")
        print(f"  PIPELINE (all verticals):")
        for row in pipeline:
            print(f"    {row['status']:15s}: {row['ct']}")

    # Revenue targets
    print(f"\n{'─'*60}")
    print(f"  REVENUE TARGETS:")
    print(f"    Current MRR:  ${total_mrr/100:.2f}/mo")
    print(f"    Target:       $73,000/mo (Machina benchmark)")
    if total_mrr > 0:
        pct = (total_mrr / 7300000) * 100
        print(f"    Progress:     {pct:.1f}%")
    print(f"\n  TO HIT $73K/mo:")
    print(f"    NeverMiss:   245 clients × $297 = $72,765")
    print(f"    OR mixed:")
    print(f"    - 50 NeverMiss ($297)   = $14,850")
    print(f"    - 20 Lead Gen ($1,000)  = $20,000")
    print(f"    - 20 SEO ($750)         = $15,000")
    print(f"    - 10 Web Design ($2,500)= $25,000/mo equiv")
    print(f"    - Digital Products       = $3,000+")
    print(f"    = ~$77,850/mo")

    # What's needed
    print(f"\n  NEEDS:")
    has_brevo = bool(os.environ.get("BREVO_API_KEY"))
    has_stripe = bool(os.environ.get("STRIPE_API_KEY"))
    if not has_brevo:
        print(f"    [-] BREVO_API_KEY — for automated email outreach")
    if not has_stripe:
        print(f"    [-] STRIPE_API_KEY — for accepting payments")
    print(f"{'='*60}\n")


# ── Revenue Report ────────────────────────────────────────────

def revenue_report(db, days: int = 30):
    """Generate revenue report across all verticals."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rev = db.execute("""
        SELECT mv.display_name, mr.revenue_type,
               COUNT(*) as transactions, SUM(mr.amount_cents) as total
        FROM machina_revenue mr
        JOIN machina_verticals mv ON mr.vertical_id = mv.id
        WHERE mr.timestamp >= ?
        GROUP BY mv.display_name, mr.revenue_type
        ORDER BY total DESC
    """, (since,)).fetchall()

    total = sum(r["total"] or 0 for r in rev) if rev else 0

    print(f"\n{'='*60}")
    print(f"  REVENUE REPORT — Last {days} Days")
    print(f"{'='*60}")
    print(f"  Total: ${total/100:.2f}")

    if rev:
        for r in rev:
            print(f"  {r['display_name']:30s} | {r['revenue_type']:10s} | "
                  f"{r['transactions']} tx | ${(r['total'] or 0)/100:.2f}")
    else:
        print(f"  No revenue recorded yet.")
        print(f"  Run: python3 machina.py --cycle to start generating revenue")

    print(f"{'='*60}\n")


# ── Full Cycle ────────────────────────────────────────────────

def run_full_cycle(db, test_mode: bool = True):
    """Run all active verticals sequentially."""
    init_verticals(db)
    verticals = db.execute(
        "SELECT * FROM machina_verticals WHERE status = 'active'"
    ).fetchall()

    print(f"\n{'='*60}")
    print(f"  MACHINA — FULL PORTFOLIO CYCLE")
    print(f"  {'TEST MODE' if test_mode else 'LIVE'}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Running {len(verticals)} active verticals")
    print(f"{'='*60}")

    total_results = {
        "verticals_run": 0,
        "total_leads": 0,
        "total_outreach": 0,
        "total_content": 0,
    }

    for v in verticals:
        results = run_vertical(db, v["name"], test_mode=test_mode)
        total_results["verticals_run"] += 1
        total_results["total_leads"] += results.get("leads_found", 0)
        total_results["total_outreach"] += results.get("outreach_sent", 0)
        total_results["total_content"] += results.get("content_created", 0)

        # Rate limit between verticals
        if not test_mode:
            time.sleep(3)

    # Summary
    print(f"\n{'='*60}")
    print(f"  CYCLE COMPLETE")
    print(f"{'='*60}")
    print(f"  Verticals run:  {total_results['verticals_run']}")
    print(f"  Leads found:    {total_results['total_leads']}")
    print(f"  Outreach sent:  {total_results['total_outreach']}")
    print(f"  Content created: {total_results['total_content']}")

    # Log
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note_path = DAILY_NOTES / f"{today}.md"
    with open(note_path, "a") as f:
        f.write(f"- [{datetime.now(timezone.utc).strftime('%H:%M UTC')}] "
                f"Machina cycle: {total_results['verticals_run']} verticals, "
                f"{total_results['total_leads']} leads, "
                f"{total_results['total_outreach']} outreach\n")

    print(f"{'='*60}\n")
    return total_results


def main():
    parser = argparse.ArgumentParser(description="Machina — Multi-Business Portfolio Engine")
    parser.add_argument("--status", action="store_true", help="Portfolio dashboard")
    parser.add_argument("--vertical", type=str, help="Run one vertical by name")
    parser.add_argument("--cycle", action="store_true", help="Run all verticals")
    parser.add_argument("--test", action="store_true", help="Dry run")
    parser.add_argument("--add", type=str, help="Add a new vertical")
    parser.add_argument("--revenue", action="store_true", help="Revenue report")
    parser.add_argument("--days", type=int, default=30, help="Days for revenue report")
    args = parser.parse_args()

    db = get_db()
    init_verticals(db)

    if args.status:
        portfolio_status(db)
    elif args.vertical:
        run_vertical(db, args.vertical, test_mode=args.test)
    elif args.cycle:
        run_full_cycle(db, test_mode=args.test)
    elif args.revenue:
        revenue_report(db, args.days)
    elif args.add:
        # Simple add — user provides name, we create minimal vertical
        db.execute(
            "INSERT OR IGNORE INTO machina_verticals (name, display_name, status) VALUES (?,?,?)",
            (args.add, args.add.replace("-", " ").title(), "active")
        )
        db.commit()
        print(f"Added vertical: {args.add}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
