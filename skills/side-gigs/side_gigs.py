"""
Side Gig Engine — Fast Money Autonomous Runner
=================================================
Runs multiple income streams simultaneously, prioritized by
speed-to-revenue. These run alongside NeverMiss as extra income.

Gigs ranked by speed to first dollar:
1. Digital products (Felix Craft) — $19-49, instant delivery
2. Freelance lead gen — sell leads to other agencies, $50-200/batch
3. SEO audits — automated site audits, $97-297 per report
4. Content packages — 30 days of posts, $500-2K/mo per client
5. Review response service — manage Google reviews, $200-500/mo
6. Website builds — AI-generated contractor sites, $1-5K each
7. Cold outreach agency — run outreach for other businesses, $500-2K/mo
8. Gov contracting consulting — FAR advisor, $150/hr

Usage:
    python3 side_gigs.py --run           # Run all active gigs
    python3 side_gigs.py --status        # Dashboard
    python3 side_gigs.py --prospect      # Find prospects for all gigs
    python3 side_gigs.py --activate GIG  # Activate a specific gig
    python3 side_gigs.py --test          # Dry run
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("NEVERMISS_DB", "/app/data/nevermiss.db")
DATA_DIR = Path(os.environ.get("NEVERMISS_DATA_DIR", "/app/data"))
GIGS_DIR = DATA_DIR / "side_gigs"
SKILLS_DIR = Path(__file__).parent.parent


def ensure_dirs():
    GIGS_DIR.mkdir(parents=True, exist_ok=True)
    for gig in GIGS:
        (GIGS_DIR / gig["id"]).mkdir(parents=True, exist_ok=True)


def get_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS side_gigs (
        id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT DEFAULT 'inactive',
        price_low INTEGER DEFAULT 0,
        price_high INTEGER DEFAULT 0,
        revenue_cents INTEGER DEFAULT 0,
        clients INTEGER DEFAULT 0,
        prospects INTEGER DEFAULT 0,
        last_run TEXT,
        notes TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gig_prospects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gig_id TEXT,
        business_name TEXT,
        contact TEXT,
        email TEXT,
        status TEXT DEFAULT 'new',
        outreach_sent INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


# ── Gig Definitions ──────────────────────────────────────────

GIGS = [
    {
        "id": "digital_products",
        "name": "Digital Products (Felix Craft)",
        "price_low": 19,
        "price_high": 49,
        "speed": "1-3 days to first sale",
        "description": "Build and sell ebooks, templates, guides via Stripe",
        "auto_tasks": ["build_product", "create_payment_link", "promote_content"],
        "requires": ["STRIPE_API_KEY"],
    },
    {
        "id": "lead_gen_agency",
        "name": "Lead Gen as a Service",
        "price_low": 500,
        "price_high": 2000,
        "speed": "1-2 weeks to first client",
        "description": "Sell lead lists and outreach campaigns to other businesses",
        "auto_tasks": ["find_prospects", "pitch_outreach", "deliver_leads"],
        "requires": ["BREVO_API_KEY"],
    },
    {
        "id": "seo_audits",
        "name": "Automated SEO Audits",
        "price_low": 97,
        "price_high": 297,
        "speed": "1 week to first sale",
        "description": "AI-generated site audits with actionable recommendations",
        "auto_tasks": ["find_prospects", "run_audit", "deliver_report", "pitch_followup"],
        "requires": [],
    },
    {
        "id": "content_packages",
        "name": "Social Media Content Packages",
        "price_low": 500,
        "price_high": 2000,
        "speed": "1-2 weeks to first client",
        "description": "30-day content calendars + posts for businesses",
        "auto_tasks": ["find_prospects", "create_sample", "pitch_outreach"],
        "requires": ["POSTIZ_API_KEY"],
    },
    {
        "id": "review_management",
        "name": "Google Review Response Service",
        "price_low": 200,
        "price_high": 500,
        "speed": "1 week to first client",
        "description": "Manage and respond to Google reviews for businesses",
        "auto_tasks": ["find_prospects", "pitch_outreach", "respond_reviews"],
        "requires": [],
    },
    {
        "id": "website_builds",
        "name": "AI Website Builds",
        "price_low": 1000,
        "price_high": 5000,
        "speed": "2-3 weeks to first client",
        "description": "Build contractor websites using AI design tools",
        "auto_tasks": ["find_prospects", "create_mockup", "pitch_outreach"],
        "requires": [],
    },
    {
        "id": "cold_outreach_agency",
        "name": "Cold Outreach Agency",
        "price_low": 500,
        "price_high": 2000,
        "speed": "1-2 weeks to first client",
        "description": "Run cold email campaigns for other businesses",
        "auto_tasks": ["find_prospects", "pitch_outreach", "run_campaigns"],
        "requires": ["INSTANTLY_API_KEY", "BREVO_API_KEY"],
    },
    {
        "id": "gov_consulting",
        "name": "Gov Contracting Consulting",
        "price_low": 150,
        "price_high": 150,
        "speed": "2-4 weeks to first client (hourly)",
        "description": "FAR advisor and proposal writing for gov contractors",
        "auto_tasks": ["find_prospects", "pitch_outreach"],
        "requires": [],
    },
]


def init_gigs():
    """Initialize gig records in DB."""
    db = get_db()
    for gig in GIGS:
        existing = db.execute("SELECT id FROM side_gigs WHERE id = ?", (gig["id"],)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO side_gigs (id, name, price_low, price_high, notes) VALUES (?,?,?,?,?)",
                (gig["id"], gig["name"], gig["price_low"], gig["price_high"],
                 json.dumps({"requires": gig["requires"], "speed": gig["speed"]}))
            )
    db.commit()


# ── Gig Tasks ────────────────────────────────────────────────

def run_gig_task(gig: dict, task: str, test_mode: bool = False):
    """Execute a specific task for a gig."""

    if task == "build_product":
        felix = SKILLS_DIR / "felix-craft" / "felix_craft.py"
        if felix.exists():
            args = ["--auto"] if not test_mode else ["--test"]
            return _run_script(felix, args)
        return "Felix Craft not found"

    elif task == "find_prospects":
        search = SKILLS_DIR / "free-search" / "free_search.py"
        target = _gig_search_target(gig["id"])
        if search.exists():
            return _run_script(search, ["--query", target, "--max", "10"])
        return f"Would search: {target}"

    elif task == "pitch_outreach":
        sdr = SKILLS_DIR / "ai-sdr" / "sdr_engine.py"
        target = _gig_outreach_target(gig["id"])
        if sdr.exists() and not test_mode:
            return _run_script(sdr, ["--target", target, "--max-leads", "5"])
        return f"Would pitch: {target}"

    elif task == "create_payment_link":
        has_stripe = bool(os.environ.get("STRIPE_API_KEY"))
        if has_stripe and not test_mode:
            return "Stripe ready — payment link creation available"
        return "Would create Stripe payment link" if test_mode else "Need STRIPE_API_KEY"

    elif task == "promote_content":
        content = SKILLS_DIR / "social-content" / "content_engine.py"
        if content.exists():
            return _run_script(content, ["--hooks", gig["name"], "--count", "5"])
        return "Would generate promo content"

    elif task == "run_audit":
        return "SEO audit: would crawl target site and generate report"

    elif task == "create_sample":
        content = SKILLS_DIR / "social-content" / "content_engine.py"
        if content.exists():
            return _run_script(content, ["--niche", "contractor marketing", "--platform", "twitter", "--count", "5"])
        return "Would create sample content"

    elif task == "deliver_leads":
        return "Would package and deliver lead batch"

    elif task == "deliver_report":
        return "Would generate and deliver SEO report"

    elif task == "respond_reviews":
        return "Would draft review responses"

    elif task == "run_campaigns":
        return "Would execute outreach campaign"

    elif task == "create_mockup":
        return "Would generate website mockup"

    elif task == "pitch_followup":
        return "Would send followup sequence"

    return f"Unknown task: {task}"


def _gig_search_target(gig_id: str) -> str:
    targets = {
        "lead_gen_agency": "marketing agencies looking for lead generation help",
        "seo_audits": "businesses with outdated websites in Dallas TX",
        "content_packages": "businesses without active social media in Houston TX",
        "review_management": "contractors with bad Google reviews in Texas",
        "website_builds": "contractors without websites in Dallas TX",
        "cold_outreach_agency": "B2B companies needing sales pipeline in Texas",
        "gov_consulting": "small businesses with SAM registration in Texas",
    }
    return targets.get(gig_id, "businesses needing help in Texas")


def _gig_outreach_target(gig_id: str) -> str:
    targets = {
        "lead_gen_agency": "marketing agency owners in Dallas TX",
        "seo_audits": "business owners with poor SEO in Houston TX",
        "content_packages": "businesses posting less than once a week on social",
        "review_management": "contractors with 3-star or lower Google rating",
        "website_builds": "contractors with no website or outdated website",
        "cold_outreach_agency": "B2B SaaS companies needing outbound sales",
        "gov_consulting": "veteran-owned businesses interested in gov contracts",
    }
    return targets.get(gig_id, "business owners in Texas")


def _run_script(script: Path, args: list, timeout: int = 120) -> str:
    try:
        proc = subprocess.run(
            [sys.executable, str(script)] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return proc.stdout[-300:] if proc.stdout else "OK"
    except subprocess.TimeoutExpired:
        return f"Timeout after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


# ── Run All Active Gigs ──────────────────────────────────────

def run_all_gigs(test_mode: bool = False):
    """Run one cycle across all active gigs."""
    db = get_db()
    init_gigs()

    active = db.execute("SELECT * FROM side_gigs WHERE status = 'active'").fetchall()

    if not active:
        # Auto-activate gigs that have their required keys
        print(f"  No active gigs. Auto-activating eligible ones...")
        activated = 0
        for gig in GIGS:
            has_keys = all(bool(os.environ.get(k)) for k in gig["requires"])
            if has_keys:
                db.execute("UPDATE side_gigs SET status = 'active' WHERE id = ?", (gig["id"],))
                print(f"    [+] Activated: {gig['name']}")
                activated += 1
            else:
                missing = [k for k in gig["requires"] if not os.environ.get(k)]
                print(f"    [-] Skipped: {gig['name']} (need {', '.join(missing)})")
        db.commit()
        active = db.execute("SELECT * FROM side_gigs WHERE status = 'active'").fetchall()
        print(f"  Activated {activated} gigs\n")

    print(f"\n{'='*60}")
    print(f"  SIDE GIG ENGINE — {'TEST' if test_mode else 'LIVE'}")
    print(f"  Active gigs: {len(active)}")
    print(f"{'='*60}")

    for row in active:
        gig_def = next((g for g in GIGS if g["id"] == row["id"]), None)
        if not gig_def:
            continue

        print(f"\n{'─'*60}")
        print(f"  GIG: {gig_def['name']}")
        print(f"  Price: ${gig_def['price_low']}-${gig_def['price_high']}")
        print(f"  Speed: {gig_def['speed']}")

        for task in gig_def["auto_tasks"]:
            print(f"\n    Task: {task}")
            result = run_gig_task(gig_def, task, test_mode=test_mode)
            print(f"    Result: {result[:150]}")

        db.execute(
            "UPDATE side_gigs SET last_run = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), row["id"])
        )

    db.commit()

    print(f"\n{'='*60}")
    print(f"  SIDE GIG CYCLE COMPLETE")
    print(f"  Ran {len(active)} gigs")
    print(f"{'='*60}\n")


# ── Dashboard ────────────────────────────────────────────────

def show_status():
    """Show side gig dashboard."""
    db = get_db()
    init_gigs()

    gigs = db.execute("SELECT * FROM side_gigs ORDER BY revenue_cents DESC").fetchall()
    total_revenue = sum(g["revenue_cents"] or 0 for g in gigs) / 100
    total_clients = sum(g["clients"] or 0 for g in gigs)
    active_count = sum(1 for g in gigs if g["status"] == "active")

    print(f"\n{'='*60}")
    print(f"  SIDE GIG DASHBOARD")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"  Total gigs:     {len(gigs)} ({active_count} active)")
    print(f"  Total revenue:  ${total_revenue:,.2f}")
    print(f"  Total clients:  {total_clients}")

    for g in gigs:
        rev = (g["revenue_cents"] or 0) / 100
        status = "[ACTIVE]" if g["status"] == "active" else "[------]"
        print(f"\n  {status} {g['name']}")
        print(f"    Price: ${g['price_low']}-${g['price_high']} | Revenue: ${rev:,.2f} | Clients: {g['clients'] or 0}")
        if g["last_run"]:
            print(f"    Last run: {g['last_run'][:16]}")

    # Check what can be activated
    inactive = [g for g in gigs if g["status"] != "active"]
    if inactive:
        print(f"\n  INACTIVE GIGS (activate with --activate <id>):")
        for g in inactive:
            gig_def = next((gd for gd in GIGS if gd["id"] == g["id"]), None)
            if gig_def:
                has_keys = all(bool(os.environ.get(k)) for k in gig_def["requires"])
                ready = "READY" if has_keys else f"Need: {', '.join(k for k in gig_def['requires'] if not os.environ.get(k))}"
                print(f"    {g['id']}: {ready}")

    print(f"{'='*60}\n")


def activate_gig(gig_id: str):
    """Activate a specific gig."""
    db = get_db()
    init_gigs()
    db.execute("UPDATE side_gigs SET status = 'active' WHERE id = ?", (gig_id,))
    db.commit()
    print(f"  Activated: {gig_id}")


def prospect_all(test_mode: bool = False):
    """Find prospects for all active gigs."""
    db = get_db()
    init_gigs()
    active = db.execute("SELECT * FROM side_gigs WHERE status = 'active'").fetchall()

    print(f"\n{'='*60}")
    print(f"  PROSPECTING — Finding leads for {len(active)} gigs")
    print(f"{'='*60}")

    for row in active:
        gig_def = next((g for g in GIGS if g["id"] == row["id"]), None)
        if not gig_def:
            continue
        print(f"\n  {gig_def['name']}:")
        result = run_gig_task(gig_def, "find_prospects", test_mode=test_mode)
        print(f"    {result[:200]}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Side Gig Engine — Fast Money Runner")
    parser.add_argument("--run", action="store_true", help="Run all active gigs")
    parser.add_argument("--status", action="store_true", help="Dashboard")
    parser.add_argument("--prospect", action="store_true", help="Find prospects for all gigs")
    parser.add_argument("--activate", help="Activate a gig by ID")
    parser.add_argument("--test", action="store_true", help="Dry run")
    args = parser.parse_args()

    if args.run:
        run_all_gigs(test_mode=args.test)
    elif args.status:
        show_status()
    elif args.prospect:
        prospect_all(test_mode=args.test)
    elif args.activate:
        activate_gig(args.activate)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
