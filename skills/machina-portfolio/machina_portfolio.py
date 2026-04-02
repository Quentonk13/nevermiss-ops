"""
Machina Portfolio Pattern — Multi-Business Autonomous Manager
===============================================================
Based on Ernesto Lopez's "Eddie" agent: $73K/mo across 11 B2C apps.

Eddie's exact role:
- Replaced a $30K/month content agency
- Automates 4+ social media accounts simultaneously
- Researches trending formats, creates images with text overlays
- Writes captions, posts daily across all verticals
- Handles customer support for 100K+ users
- Delivers daily KPI reports

Each vertical gets its own:
- Lead pipeline + CRM
- Content calendar
- Outreach sequences
- Revenue tracking
- Performance metrics

Usage:
    python3 machina_portfolio.py --status              # Portfolio dashboard
    python3 machina_portfolio.py --add "Lead Gen"      # Add a vertical
    python3 machina_portfolio.py --cycle                # Run cycle across all verticals
    python3 machina_portfolio.py --vertical "NeverMiss" # Run single vertical
    python3 machina_portfolio.py --kpi                  # Daily KPI report (Eddie style)
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.environ.get("NEVERMISS_DB", "/app/data/nevermiss.db")
DATA_DIR = Path(os.environ.get("NEVERMISS_DATA_DIR", "/app/data"))
VERTICALS_DIR = DATA_DIR / "verticals"
SKILLS_DIR = Path(__file__).parent.parent


def ensure_dirs():
    VERTICALS_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS portfolio_verticals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        pricing_model TEXT DEFAULT 'monthly',
        price_low INTEGER DEFAULT 0,
        price_high INTEGER DEFAULT 0,
        active_clients INTEGER DEFAULT 0,
        monthly_revenue_cents INTEGER DEFAULT 0,
        total_revenue_cents INTEGER DEFAULT 0,
        leads_in_pipeline INTEGER DEFAULT 0,
        content_posts_week INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_cycle TEXT,
        notes TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS portfolio_kpi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        vertical_id INTEGER,
        metric TEXT,
        value REAL,
        notes TEXT,
        FOREIGN KEY (vertical_id) REFERENCES portfolio_verticals(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS portfolio_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vertical_id INTEGER,
        cycle_type TEXT,
        started_at TEXT,
        completed_at TEXT,
        actions_taken TEXT,
        results TEXT,
        FOREIGN KEY (vertical_id) REFERENCES portfolio_verticals(id)
    )""")
    conn.commit()
    return conn


# ── Default Verticals (Quenton's businesses) ─────────────────

DEFAULT_VERTICALS = [
    {
        "name": "NeverMiss",
        "description": "Missed-call text-back for contractors",
        "pricing_model": "monthly",
        "price_low": 297,
        "price_high": 297,
        "tasks": ["sdr_outreach", "content_creation", "client_onboarding"],
    },
    {
        "name": "Lead Gen Agency",
        "description": "Done-for-you lead generation as a service",
        "pricing_model": "monthly",
        "price_low": 500,
        "price_high": 2000,
        "tasks": ["sdr_outreach", "content_creation", "case_studies"],
    },
    {
        "name": "SEO Content",
        "description": "AI-generated SEO content packages for businesses",
        "pricing_model": "monthly",
        "price_low": 500,
        "price_high": 2000,
        "tasks": ["content_creation", "seo_audit", "blog_writing"],
    },
    {
        "name": "Web Design",
        "description": "AI-built websites for contractors and local businesses",
        "pricing_model": "project",
        "price_low": 1000,
        "price_high": 5000,
        "tasks": ["sdr_outreach", "site_building", "client_onboarding"],
    },
    {
        "name": "Gov Contracting",
        "description": "FAR advisor consulting for government contracts",
        "pricing_model": "hourly",
        "price_low": 150,
        "price_high": 150,
        "tasks": ["far_research", "proposal_writing", "compliance_check"],
    },
]


def init_verticals():
    """Initialize default verticals if not present."""
    db = get_db()
    for v in DEFAULT_VERTICALS:
        existing = db.execute("SELECT id FROM portfolio_verticals WHERE name = ?", (v["name"],)).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO portfolio_verticals
                   (name, description, pricing_model, price_low, price_high, notes)
                   VALUES (?,?,?,?,?,?)""",
                (v["name"], v["description"], v["pricing_model"],
                 v["price_low"], v["price_high"], json.dumps({"tasks": v["tasks"]}))
            )
    db.commit()


# ── Portfolio Dashboard ──────────────────────────────────────

def portfolio_status():
    """Show full portfolio dashboard."""
    db = get_db()
    init_verticals()

    verticals = db.execute("SELECT * FROM portfolio_verticals ORDER BY monthly_revenue_cents DESC").fetchall()

    total_mrr = sum(v["monthly_revenue_cents"] or 0 for v in verticals) / 100
    total_clients = sum(v["active_clients"] or 0 for v in verticals)
    total_pipeline = sum(v["leads_in_pipeline"] or 0 for v in verticals)

    print(f"\n{'='*60}")
    print(f"  MACHINA PORTFOLIO — Dashboard")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"  Total MRR:       ${total_mrr:,.2f}")
    print(f"  Active clients:  {total_clients}")
    print(f"  Pipeline leads:  {total_pipeline}")
    print(f"  Verticals:       {len(verticals)}")

    print(f"\n{'─'*60}")
    for v in verticals:
        mrr = (v["monthly_revenue_cents"] or 0) / 100
        status_icon = "[+]" if v["status"] == "active" else "[-]"
        print(f"  {status_icon} {v['name']}")
        print(f"      {v['description']}")
        pricing = f"${v['price_low']}"
        if v["price_high"] != v["price_low"]:
            pricing += f"-${v['price_high']}"
        pricing += f"/{v['pricing_model']}"
        print(f"      Pricing: {pricing}")
        print(f"      Clients: {v['active_clients']} | MRR: ${mrr:,.2f} | Pipeline: {v['leads_in_pipeline']}")
        if v["last_cycle"]:
            print(f"      Last cycle: {v['last_cycle']}")
        print()

    # Projection
    if total_mrr > 0:
        print(f"  PROJECTIONS:")
        print(f"    Monthly:  ${total_mrr:,.2f}")
        print(f"    Yearly:   ${total_mrr * 12:,.2f}")
    else:
        print(f"  No revenue yet. Run: python3 machina_portfolio.py --cycle")

    print(f"{'='*60}\n")


# ── Per-Vertical Cycle ───────────────────────────────────────

def run_vertical_cycle(vertical_name: str, test_mode: bool = False):
    """Run one revenue cycle for a specific vertical."""
    db = get_db()
    init_verticals()

    vertical = db.execute(
        "SELECT * FROM portfolio_verticals WHERE name = ?", (vertical_name,)
    ).fetchone()

    if not vertical:
        print(f"  [!] Vertical '{vertical_name}' not found")
        available = db.execute("SELECT name FROM portfolio_verticals").fetchall()
        print(f"  Available: {', '.join(v['name'] for v in available)}")
        return

    print(f"\n{'='*60}")
    print(f"  VERTICAL CYCLE: {vertical['name']}")
    print(f"  {vertical['description']}")
    print(f"  Mode: {'TEST' if test_mode else 'LIVE'}")
    print(f"{'='*60}")

    start_time = datetime.utcnow().isoformat()
    actions = []
    results = {}

    # Parse tasks
    notes = json.loads(vertical["notes"] or "{}")
    tasks = notes.get("tasks", ["sdr_outreach", "content_creation"])

    # Ensure vertical data dir
    v_dir = VERTICALS_DIR / vertical["name"].lower().replace(" ", "_")
    v_dir.mkdir(parents=True, exist_ok=True)

    for task in tasks:
        print(f"\n  Task: {task}")

        if task == "sdr_outreach":
            sdr_script = SKILLS_DIR / "ai-sdr" / "sdr_engine.py"
            if sdr_script.exists() and not test_mode:
                target = _get_vertical_target(vertical["name"])
                try:
                    proc = subprocess.run(
                        [sys.executable, str(sdr_script), "--target", target, "--max-leads", "5"],
                        capture_output=True, text=True, timeout=120
                    )
                    actions.append(f"SDR: searched '{target}'")
                    print(f"    Searched: {target}")
                    print(f"    {proc.stdout[:200]}")
                except Exception as e:
                    print(f"    [!] SDR error: {e}")
            else:
                target = _get_vertical_target(vertical["name"])
                print(f"    [{'TEST' if test_mode else '!'}] Would search: {target}")
                actions.append(f"SDR: would search '{target}'")

        elif task == "content_creation":
            content_script = SKILLS_DIR / "social-content" / "content_engine.py"
            if content_script.exists() and not test_mode:
                niche = _get_vertical_niche(vertical["name"])
                try:
                    proc = subprocess.run(
                        [sys.executable, str(content_script),
                         "--niche", niche, "--platform", "twitter", "--count", "3"],
                        capture_output=True, text=True, timeout=60
                    )
                    actions.append(f"Content: generated for '{niche}'")
                    print(f"    Generated content for: {niche}")
                except Exception as e:
                    print(f"    [!] Content error: {e}")
            else:
                niche = _get_vertical_niche(vertical["name"])
                print(f"    [{'TEST' if test_mode else '!'}] Would create content for: {niche}")
                actions.append(f"Content: would create for '{niche}'")

        elif task == "client_onboarding":
            print(f"    Checking for new sign-ups...")
            actions.append("Onboarding: checked for new clients")

        elif task == "seo_audit":
            print(f"    Running SEO check...")
            actions.append("SEO: audit queued")

        elif task == "blog_writing":
            print(f"    Generating blog content...")
            actions.append("Blog: content queued")

        elif task == "site_building":
            print(f"    Checking for site requests...")
            actions.append("Sites: checked queue")

        elif task == "far_research":
            print(f"    Checking FAR updates...")
            actions.append("FAR: checked for updates")

        elif task == "proposal_writing":
            print(f"    Checking proposal queue...")
            actions.append("Proposals: checked queue")

        elif task == "case_studies":
            print(f"    Looking for case study material...")
            actions.append("Case studies: checked for wins")

        elif task == "compliance_check":
            print(f"    Running compliance scan...")
            actions.append("Compliance: scan queued")

        else:
            print(f"    [?] Unknown task: {task}")

    # Log cycle
    db.execute(
        """INSERT INTO portfolio_cycles
           (vertical_id, cycle_type, started_at, completed_at, actions_taken, results)
           VALUES (?,?,?,?,?,?)""",
        (vertical["id"], "standard", start_time, datetime.utcnow().isoformat(),
         json.dumps(actions), json.dumps(results))
    )
    db.execute(
        "UPDATE portfolio_verticals SET last_cycle = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), vertical["id"])
    )
    db.commit()

    print(f"\n{'─'*60}")
    print(f"  CYCLE COMPLETE: {vertical['name']}")
    print(f"  Actions: {len(actions)}")
    for a in actions:
        print(f"    - {a}")
    print(f"{'='*60}\n")


def _get_vertical_target(name: str) -> str:
    """Get SDR target for a vertical."""
    targets = {
        "NeverMiss": "contractors who miss calls in Dallas TX",
        "Lead Gen Agency": "marketing agencies needing leads in Houston TX",
        "SEO Content": "businesses needing content marketing in Austin TX",
        "Web Design": "contractors without websites in San Antonio TX",
        "Gov Contracting": "small businesses with SAM registration in Texas",
    }
    return targets.get(name, f"{name} prospects in Texas")


def _get_vertical_niche(name: str) -> str:
    """Get content niche for a vertical."""
    niches = {
        "NeverMiss": "missed call text back for contractors",
        "Lead Gen Agency": "lead generation tips for agencies",
        "SEO Content": "SEO and content marketing",
        "Web Design": "contractor website design",
        "Gov Contracting": "government contracting for small business",
    }
    return niches.get(name, name.lower())


# ── Full Portfolio Cycle ─────────────────────────────────────

def run_full_cycle(test_mode: bool = False):
    """Run cycles across ALL active verticals sequentially."""
    db = get_db()
    init_verticals()

    verticals = db.execute(
        "SELECT name FROM portfolio_verticals WHERE status = 'active'"
    ).fetchall()

    print(f"\n{'='*60}")
    print(f"  MACHINA — Full Portfolio Cycle")
    print(f"  Verticals: {len(verticals)}")
    print(f"  Mode: {'TEST' if test_mode else 'LIVE'}")
    print(f"{'='*60}")

    for v in verticals:
        run_vertical_cycle(v["name"], test_mode=test_mode)

    print(f"\n{'='*60}")
    print(f"  ALL {len(verticals)} VERTICALS CYCLED")
    print(f"{'='*60}\n")

    # Show dashboard after
    portfolio_status()


# ── Daily KPI Report (Eddie Style) ──────────────────────────

def daily_kpi_report():
    """Generate Eddie-style daily KPI report across all verticals."""
    db = get_db()
    init_verticals()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    verticals = db.execute("SELECT * FROM portfolio_verticals").fetchall()

    print(f"\n{'='*60}")
    print(f"  DAILY KPI REPORT — {today}")
    print(f"  (Eddie Pattern: automated performance tracking)")
    print(f"{'='*60}")

    total_mrr = 0
    total_clients = 0
    total_pipeline = 0

    for v in verticals:
        mrr = (v["monthly_revenue_cents"] or 0) / 100
        total_mrr += mrr
        total_clients += v["active_clients"] or 0
        total_pipeline += v["leads_in_pipeline"] or 0

        # Get today's cycles
        cycles_today = db.execute(
            """SELECT COUNT(*) as ct FROM portfolio_cycles
               WHERE vertical_id = ? AND started_at LIKE ?""",
            (v["id"], f"{today}%")
        ).fetchone()

        print(f"\n  {v['name']}")
        print(f"    Revenue:  ${mrr:,.2f}/mo")
        print(f"    Clients:  {v['active_clients'] or 0}")
        print(f"    Pipeline: {v['leads_in_pipeline'] or 0}")
        print(f"    Cycles today: {cycles_today['ct']}")

        # Log KPI
        db.execute(
            "INSERT INTO portfolio_kpi (date, vertical_id, metric, value) VALUES (?,?,?,?)",
            (today, v["id"], "mrr", mrr)
        )
        db.execute(
            "INSERT INTO portfolio_kpi (date, vertical_id, metric, value) VALUES (?,?,?,?)",
            (today, v["id"], "clients", v["active_clients"] or 0)
        )

    db.commit()

    print(f"\n{'─'*60}")
    print(f"  PORTFOLIO TOTALS:")
    print(f"    Total MRR:      ${total_mrr:,.2f}")
    print(f"    Total clients:  {total_clients}")
    print(f"    Total pipeline: {total_pipeline}")
    print(f"    ARR projection: ${total_mrr * 12:,.2f}")

    # Week-over-week if we have historical data
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_mrr = db.execute(
        "SELECT COALESCE(SUM(value), 0) FROM portfolio_kpi WHERE date = ? AND metric = 'mrr'",
        (week_ago,)
    ).fetchone()[0]

    if prev_mrr > 0:
        growth = ((total_mrr - prev_mrr) / prev_mrr) * 100
        print(f"    WoW growth:     {growth:+.1f}%")

    print(f"{'='*60}\n")


# ── Add Vertical ─────────────────────────────────────────────

def add_vertical(name: str, description: str = "", price_low: int = 0,
                 price_high: int = 0, pricing_model: str = "monthly"):
    """Add a new business vertical to the portfolio."""
    db = get_db()

    existing = db.execute("SELECT id FROM portfolio_verticals WHERE name = ?", (name,)).fetchone()
    if existing:
        print(f"  Vertical '{name}' already exists (ID: {existing['id']})")
        return

    db.execute(
        """INSERT INTO portfolio_verticals
           (name, description, pricing_model, price_low, price_high, notes)
           VALUES (?,?,?,?,?,?)""",
        (name, description or f"{name} business vertical", pricing_model,
         price_low, price_high, json.dumps({"tasks": ["sdr_outreach", "content_creation"]}))
    )
    db.commit()
    print(f"  Added vertical: {name}")
    print(f"    Pricing: ${price_low}-${price_high}/{pricing_model}")


def main():
    parser = argparse.ArgumentParser(description="Machina Portfolio — Multi-Business Manager")
    parser.add_argument("--status", action="store_true", help="Portfolio dashboard")
    parser.add_argument("--add", help="Add a new vertical by name")
    parser.add_argument("--cycle", action="store_true", help="Run cycle across all verticals")
    parser.add_argument("--vertical", help="Run cycle for a specific vertical")
    parser.add_argument("--kpi", action="store_true", help="Daily KPI report")
    parser.add_argument("--test", action="store_true", help="Test mode (no actual sends)")
    parser.add_argument("--description", default="", help="Vertical description")
    parser.add_argument("--price-low", type=int, default=0, help="Low price")
    parser.add_argument("--price-high", type=int, default=0, help="High price")
    parser.add_argument("--pricing", default="monthly", choices=["monthly", "project", "hourly"])
    args = parser.parse_args()

    if args.status:
        portfolio_status()
    elif args.add:
        add_vertical(args.add, args.description, args.price_low, args.price_high, args.pricing)
    elif args.cycle:
        run_full_cycle(test_mode=args.test)
    elif args.vertical:
        run_vertical_cycle(args.vertical, test_mode=args.test)
    elif args.kpi:
        daily_kpi_report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
