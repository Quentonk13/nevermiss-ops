"""
NeverMiss Analytics Engine
==========================
Generates formatted reports from the SQLite database for Telegram delivery.
Covers daily/weekly metrics, funnel analysis, API costs, template performance,
and revenue forecasting.

Usage:
    python3 analytics_engine.py --daily
    python3 analytics_engine.py --weekly
    python3 analytics_engine.py --funnel
    python3 analytics_engine.py --api-costs
    python3 analytics_engine.py --templates
    python3 analytics_engine.py --forecast
    python3 analytics_engine.py --all
"""

import argparse
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_DIR = os.environ.get("NEVERMISS_DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "nevermiss.db")
REPORTS_DIR = os.path.join(DB_DIR, "reports")
PRODUCT_PRICE = 297  # $/month


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _cursor():
    conn = _connect()
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()
        conn.close()


def _q(query: str, params: tuple = ()) -> list[dict]:
    with _cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def _q1(query: str, params: tuple = ()) -> Optional[dict]:
    rows = _q(query, params)
    return rows[0] if rows else None


def _scalar(query: str, params: tuple = ()):
    with _cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.utcnow() - timedelta(days=n)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def daily_report() -> str:
    """Today's metrics snapshot."""
    today = _today()

    leads = _scalar(
        "SELECT COUNT(*) FROM leads WHERE date(created_at) = ?", (today,)
    )
    emails = _scalar(
        "SELECT COUNT(*) FROM emails_sent WHERE date(sent_at) = ?", (today,)
    )
    opens = _scalar(
        "SELECT COUNT(*) FROM emails_sent WHERE date(opened_at) = ?", (today,)
    )
    replies = _scalar(
        "SELECT COUNT(*) FROM emails_sent WHERE date(replied_at) = ?", (today,)
    )
    demos = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status = 'demo_booked' AND date(updated_at) = ?",
        (today,),
    )
    closed = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status = 'closed_won' AND date(updated_at) = ?",
        (today,),
    )
    revenue = _scalar(
        "SELECT COALESCE(SUM(amount), 0) FROM revenue WHERE date(created_at) = ?",
        (today,),
    )
    api_cost = _scalar(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE date(created_at) = ?",
        (today,),
    )

    open_rate = f"{opens / emails * 100:.1f}%" if emails else "N/A"
    reply_rate = f"{replies / emails * 100:.1f}%" if emails else "N/A"

    return (
        f"DAILY REPORT — {today}\n"
        f"{'=' * 35}\n"
        f"Leads sourced:  {leads}\n"
        f"Emails sent:    {emails}\n"
        f"Opens:          {opens} ({open_rate})\n"
        f"Replies:        {replies} ({reply_rate})\n"
        f"Demos booked:   {demos}\n"
        f"Deals closed:   {closed}\n"
        f"Revenue:        ${revenue:,.2f}\n"
        f"API cost:       ${api_cost:.2f}\n"
        f"{'=' * 35}"
    )


def weekly_report() -> str:
    """7-day trends with day-over-day comparison."""
    today = _today()
    week_ago = _days_ago(7)
    prev_week_start = _days_ago(14)

    # This week
    tw = _q1(
        """SELECT
            COALESCE(SUM(leads_sourced), 0) as leads,
            COALESCE(SUM(emails_sent), 0) as emails,
            COALESCE(SUM(replies), 0) as replies,
            COALESCE(SUM(demos_booked), 0) as demos,
            COALESCE(SUM(deals_closed), 0) as closed,
            COALESCE(SUM(revenue), 0) as revenue,
            COALESCE(SUM(api_cost), 0) as cost
        FROM daily_metrics WHERE date >= ?""",
        (week_ago,),
    ) or {}

    # Previous week
    pw = _q1(
        """SELECT
            COALESCE(SUM(leads_sourced), 0) as leads,
            COALESCE(SUM(emails_sent), 0) as emails,
            COALESCE(SUM(replies), 0) as replies,
            COALESCE(SUM(demos_booked), 0) as demos,
            COALESCE(SUM(deals_closed), 0) as closed,
            COALESCE(SUM(revenue), 0) as revenue,
            COALESCE(SUM(api_cost), 0) as cost
        FROM daily_metrics WHERE date >= ? AND date < ?""",
        (prev_week_start, week_ago),
    ) or {}

    def _delta(curr, prev):
        if not prev:
            return "+NEW"
        pct = ((curr - prev) / prev) * 100 if prev else 0
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.0f}%"

    tl = tw.get("leads", 0)
    te = tw.get("emails", 0)
    tr = tw.get("replies", 0)
    td = tw.get("demos", 0)
    tc = tw.get("closed", 0)
    trev = tw.get("revenue", 0)
    tcost = tw.get("cost", 0)

    pl = pw.get("leads", 0)
    pe = pw.get("emails", 0)
    pr = pw.get("replies", 0)
    pd = pw.get("demos", 0)
    pc = pw.get("closed", 0)

    reply_rate = f"{tr / te * 100:.1f}%" if te else "N/A"

    lines = [
        f"WEEKLY REPORT — {week_ago} to {today}",
        "=" * 40,
        f"Leads:    {tl:>5}  ({_delta(tl, pl)} vs prev week)",
        f"Emails:   {te:>5}  ({_delta(te, pe)})",
        f"Replies:  {tr:>5}  ({_delta(tr, pr)})  Rate: {reply_rate}",
        f"Demos:    {td:>5}  ({_delta(td, pd)})",
        f"Closed:   {tc:>5}  ({_delta(tc, pc)})",
        f"Revenue:  ${trev:>8,.2f}",
        f"API cost: ${tcost:>8,.2f}",
        "=" * 40,
    ]

    # Top trades this week
    trades = _q(
        """SELECT trade, COUNT(*) as cnt FROM leads
        WHERE date(created_at) >= ? AND trade != ''
        GROUP BY trade ORDER BY cnt DESC LIMIT 5""",
        (week_ago,),
    )
    if trades:
        lines.append("\nTop trades:")
        for t in trades:
            lines.append(f"  {t['trade']}: {t['cnt']} leads")

    # Top cities
    cities = _q(
        """SELECT city, COUNT(*) as cnt FROM leads
        WHERE date(created_at) >= ? AND city != ''
        GROUP BY city ORDER BY cnt DESC LIMIT 5""",
        (week_ago,),
    )
    if cities:
        lines.append("\nTop cities:")
        for c in cities:
            lines.append(f"  {c['city']}: {c['cnt']} leads")

    return "\n".join(lines)


def funnel_analysis() -> str:
    """Conversion funnel: lead -> email -> reply -> demo -> close."""
    total_leads = _scalar("SELECT COUNT(*) FROM leads")
    emailed = _scalar(
        "SELECT COUNT(DISTINCT lead_id) FROM emails_sent WHERE sent_at IS NOT NULL"
    )
    replied = _scalar(
        "SELECT COUNT(DISTINCT lead_id) FROM emails_sent WHERE replied_at IS NOT NULL"
    )
    demos = _scalar("SELECT COUNT(*) FROM leads WHERE status IN ('demo_booked', 'demo_done', 'closed_won', 'closed_lost')")
    closed = _scalar("SELECT COUNT(*) FROM leads WHERE status = 'closed_won'")

    def _rate(num, denom):
        return f"{num / denom * 100:.1f}%" if denom else "N/A"

    lines = [
        "CONVERSION FUNNEL",
        "=" * 35,
        f"Total leads:     {total_leads}",
        f"  -> Emailed:    {emailed}  ({_rate(emailed, total_leads)})",
        f"  -> Replied:    {replied}  ({_rate(replied, emailed)})",
        f"  -> Demo:       {demos}  ({_rate(demos, replied)})",
        f"  -> Closed:     {closed}  ({_rate(closed, demos)})",
        "",
        f"Overall close rate: {_rate(closed, total_leads)}",
        f"Email-to-close:     {_rate(closed, emailed)}",
        "=" * 35,
    ]

    # Funnel by trade
    trades = _q(
        """SELECT trade, COUNT(*) as cnt FROM leads
        WHERE trade != '' GROUP BY trade ORDER BY cnt DESC LIMIT 5"""
    )
    if trades:
        lines.append("\nBy trade:")
        for t in trades:
            trade_closed = _scalar(
                "SELECT COUNT(*) FROM leads WHERE trade = ? AND status = 'closed_won'",
                (t["trade"],),
            )
            trade_emailed = _scalar(
                """SELECT COUNT(DISTINCT e.lead_id) FROM emails_sent e
                JOIN leads l ON l.id = e.lead_id
                WHERE l.trade = ? AND e.sent_at IS NOT NULL""",
                (t["trade"],),
            )
            lines.append(
                f"  {t['trade']}: {t['cnt']} leads, {trade_emailed} emailed, {trade_closed} closed ({_rate(trade_closed, t['cnt'])})"
            )

    return "\n".join(lines)


def api_cost_report() -> str:
    """API spend breakdown by provider."""
    today = _today()
    week_ago = _days_ago(7)
    month_ago = _days_ago(30)

    # Today
    today_costs = _q(
        """SELECT provider, SUM(cost_usd) as cost, SUM(tokens_in + tokens_out) as tokens
        FROM api_usage WHERE date(created_at) = ?
        GROUP BY provider ORDER BY cost DESC""",
        (today,),
    )

    # This week
    week_costs = _q(
        """SELECT provider, SUM(cost_usd) as cost, SUM(tokens_in + tokens_out) as tokens
        FROM api_usage WHERE date(created_at) >= ?
        GROUP BY provider ORDER BY cost DESC""",
        (week_ago,),
    )

    # This month
    month_total = _scalar(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE date(created_at) >= ?",
        (month_ago,),
    )

    lines = [
        "API COST REPORT",
        "=" * 40,
        f"\nToday ({today}):",
    ]

    day_total = 0
    for row in today_costs:
        cost = row["cost"] or 0
        tokens = row["tokens"] or 0
        day_total += cost
        lines.append(f"  {row['provider']:>12}: ${cost:.4f}  ({tokens:,} tokens)")
    lines.append(f"  {'TOTAL':>12}: ${day_total:.4f}")

    lines.append(f"\nThis week:")
    week_total = 0
    for row in week_costs:
        cost = row["cost"] or 0
        week_total += cost
        lines.append(f"  {row['provider']:>12}: ${cost:.4f}")
    lines.append(f"  {'TOTAL':>12}: ${week_total:.4f}")

    lines.append(f"\n30-day total: ${month_total:.2f}")

    # Daily burn rate
    days_with_data = _scalar(
        "SELECT COUNT(DISTINCT date(created_at)) FROM api_usage WHERE date(created_at) >= ?",
        (month_ago,),
    )
    if days_with_data:
        daily_avg = month_total / days_with_data
        lines.append(f"Avg daily burn: ${daily_avg:.2f}")
        lines.append(f"Projected monthly: ${daily_avg * 30:.2f}")

    lines.append("=" * 40)
    return "\n".join(lines)


def top_performing_templates() -> str:
    """Best email templates by open and reply rates."""
    templates = _q(
        """SELECT
            c.template_id,
            c.name,
            c.sent_count,
            c.open_count,
            c.reply_count
        FROM campaigns c
        WHERE c.sent_count > 0
        ORDER BY c.reply_count * 1.0 / c.sent_count DESC
        LIMIT 10"""
    )

    if not templates:
        return "TEMPLATE PERFORMANCE\n====================\nNo campaigns with data yet."

    lines = ["TEMPLATE PERFORMANCE", "=" * 50]
    for i, t in enumerate(templates, 1):
        sent = t["sent_count"]
        opens = t["open_count"] or 0
        replies = t["reply_count"] or 0
        open_rate = f"{opens / sent * 100:.1f}%" if sent else "N/A"
        reply_rate = f"{replies / sent * 100:.1f}%" if sent else "N/A"
        lines.append(
            f"{i}. {t['name'] or t['template_id']}\n"
            f"   Sent: {sent}  Opens: {opens} ({open_rate})  "
            f"Replies: {replies} ({reply_rate})"
        )

    lines.append("=" * 50)
    return "\n".join(lines)


def revenue_forecast() -> str:
    """MRR projection based on current pipeline and close rates."""
    # Current MRR
    active_customers = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status = 'closed_won'"
    )
    current_mrr = active_customers * PRODUCT_PRICE

    # Pipeline
    demos_pending = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status = 'demo_booked'"
    )
    interested = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status = 'interested'"
    )
    emailed = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status IN ('emailed', 'followed_up')"
    )

    # Historical close rates
    total_demos = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status IN ('demo_booked', 'demo_done', 'closed_won', 'closed_lost')"
    )
    total_closed = _scalar(
        "SELECT COUNT(*) FROM leads WHERE status = 'closed_won'"
    )
    demo_close_rate = total_closed / total_demos if total_demos else 0.25  # default 25%

    total_replied = _scalar(
        "SELECT COUNT(DISTINCT lead_id) FROM emails_sent WHERE replied_at IS NOT NULL"
    )
    reply_to_demo = total_demos / total_replied if total_replied else 0.30  # default 30%

    # Projections
    expected_from_demos = demos_pending * demo_close_rate * PRODUCT_PRICE
    expected_from_interested = interested * reply_to_demo * demo_close_rate * PRODUCT_PRICE
    expected_from_pipeline = emailed * 0.05 * reply_to_demo * demo_close_rate * PRODUCT_PRICE

    projected_mrr = current_mrr + expected_from_demos + expected_from_interested + expected_from_pipeline

    lines = [
        "REVENUE FORECAST",
        "=" * 40,
        f"Current customers:   {active_customers}",
        f"Current MRR:         ${current_mrr:,.2f}",
        "",
        "Pipeline:",
        f"  Demos pending:     {demos_pending} (est ${expected_from_demos:,.0f})",
        f"  Interested leads:  {interested} (est ${expected_from_interested:,.0f})",
        f"  In outreach:       {emailed} (est ${expected_from_pipeline:,.0f})",
        "",
        f"Projected MRR:       ${projected_mrr:,.2f}",
        f"Projected ARR:       ${projected_mrr * 12:,.2f}",
        "",
        "Assumptions:",
        f"  Demo close rate:   {demo_close_rate * 100:.0f}%",
        f"  Reply-to-demo:     {reply_to_demo * 100:.0f}%",
        f"  Email reply rate:  5% (default)",
        "=" * 40,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save reports
# ---------------------------------------------------------------------------

def _save_report(name: str, content: str):
    """Save report to /app/data/reports/."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = _today()
    path = os.path.join(REPORTS_DIR, f"{today}_{name}.txt")
    with open(path, "w") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NeverMiss Analytics")
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--weekly", action="store_true")
    parser.add_argument("--funnel", action="store_true")
    parser.add_argument("--api-costs", action="store_true")
    parser.add_argument("--templates", action="store_true")
    parser.add_argument("--forecast", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    reports = []

    if args.daily or args.all:
        r = daily_report()
        _save_report("daily", r)
        reports.append(r)

    if args.weekly or args.all:
        r = weekly_report()
        _save_report("weekly", r)
        reports.append(r)

    if args.funnel or args.all:
        r = funnel_analysis()
        _save_report("funnel", r)
        reports.append(r)

    if args.api_costs or args.all:
        r = api_cost_report()
        _save_report("api_costs", r)
        reports.append(r)

    if args.templates or args.all:
        r = top_performing_templates()
        _save_report("templates", r)
        reports.append(r)

    if args.forecast or args.all:
        r = revenue_forecast()
        _save_report("forecast", r)
        reports.append(r)

    if not reports:
        parser.print_help()
        return

    print("\n\n".join(reports))


if __name__ == "__main__":
    main()
