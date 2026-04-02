"""
Autonomous Scheduler — Runs the Right Task at the Right Time
==============================================================
Called on every heartbeat. Checks UTC hour and runs the appropriate
revenue cycle automatically.

This is what makes the bot ACTUALLY autonomous like:
- Stormy.ai ($25/mo SDR)
- Oliver's Larry ($671 MRR)
- Felix Craft ($14K in 2.5 weeks)

Usage:
    python3 scheduler.py --run          # Run the scheduled task for current hour
    python3 scheduler.py --schedule     # Show the full schedule
    python3 scheduler.py --force sdr    # Force run a specific task
    python3 scheduler.py --force content
    python3 scheduler.py --force audit
    python3 scheduler.py --force brief
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("NEVERMISS_DATA_DIR", "/app/data"))
DAILY_NOTES = DATA_DIR / "ceo_memory" / "daily_notes"
ENGINE = Path("/app/skills/revenue-engine/revenue_engine.py")
SDR = Path("/app/skills/ai-sdr/sdr_engine.py")
CONTENT = Path("/app/skills/social-content/content_engine.py")
QUEUE = Path("/app/skills/content-queue/content_queue.py")
FELIX = Path("/app/skills/felix-craft/felix_craft.py")
MACHINA = Path("/app/skills/machina-portfolio/machina_portfolio.py")
SIDE_GIGS = Path("/app/skills/side-gigs/side_gigs.py")

# Target markets to rotate through
TARGETS = [
    "plumbers in Dallas TX",
    "plumbers in Houston TX",
    "plumbers in Austin TX",
    "HVAC contractors in Dallas TX",
    "HVAC contractors in Houston TX",
    "electricians in Dallas TX",
    "electricians in Houston TX",
    "roofers in Dallas TX",
    "roofers in Houston TX",
    "general contractors in Dallas TX",
]


def get_today_target() -> str:
    """Rotate through target markets based on day of year."""
    day = datetime.now(timezone.utc).timetuple().tm_yday
    return TARGETS[day % len(TARGETS)]


def log_action(action: str, result: str):
    """Log to daily notes."""
    DAILY_NOTES.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note_path = DAILY_NOTES / f"{today}.md"
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    with open(note_path, "a") as f:
        f.write(f"- [{time_str}] {action}: {result}\n")


def run_skill(script: Path, args: list, timeout: int = 60) -> str:
    """Run a skill script and return output."""
    if not script.exists():
        return f"SKIP: {script.name} not found"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)] + args,
            capture_output=True, text=True, timeout=timeout
        )
        output = proc.stdout[-500:] if proc.stdout else ""
        if proc.returncode != 0:
            output += f"\nSTDERR: {proc.stderr[-200:]}"
        return output
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {str(e)}"


def task_sdr():
    """AI SDR cycle — find and research leads."""
    target = get_today_target()
    print(f"[AUTO] SDR cycle: {target}")
    result = run_skill(SDR, ["--target", target, "--max-leads", "10"])
    log_action("SDR", f"Target: {target} | {result[:100]}")
    return result


def task_content():
    """Content creation cycle — generate and post/queue."""
    print("[AUTO] Content cycle")
    result = run_skill(CONTENT, ["--niche", "contractor marketing", "--weekly"])
    log_action("Content", f"Generated weekly content | {result[:100]}")

    # Export queue for manual platforms
    if QUEUE.exists():
        queue_result = run_skill(QUEUE, ["--export"])
        if "manual" in queue_result.lower():
            print("[AUTO] Manual posts queued — check /app/data/content_queue/")

    return result


def task_felix_craft():
    """Felix Craft cycle — build and sell digital products."""
    print("[AUTO] Felix Craft cycle")
    result = run_skill(FELIX, ["--auto"])
    log_action("FelixCraft", f"Product cycle | {result[:100]}")
    return result


def task_machina():
    """Machina cycle — run all business verticals."""
    print("[AUTO] Machina portfolio cycle")
    result = run_skill(MACHINA, ["--cycle"])
    log_action("Machina", f"Portfolio cycle | {result[:100]}")
    return result


def task_side_gigs():
    """Side gigs cycle — run all active money-making gigs."""
    print("[AUTO] Side gigs cycle")
    result = run_skill(SIDE_GIGS, ["--run"])
    log_action("SideGigs", f"Gig cycle | {result[:100]}")
    return result


def task_audit():
    """Audit cycle — check CRM, replies, metrics."""
    print("[AUTO] Audit cycle")
    result = run_skill(ENGINE, ["--report"])
    log_action("Audit", f"Status report generated | {result[:100]}")
    return result


def task_morning_brief() -> str:
    """Generate morning brief for Quenton."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note_path = DAILY_NOTES / f"{today}.md"

    brief = "MORNING BRIEF:\n"
    # Check what happened yesterday
    yesterday = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if note_path.exists():
        with open(note_path, "r") as f:
            notes = f.read()
        brief += f"Yesterday: {len(notes.splitlines())} actions logged\n"
    else:
        brief += "Yesterday: No activity logged\n"

    target = get_today_target()
    brief += f"Today's target: {target}\n"
    brief += f"Plan: SDR cycle at 10:00, Content at 14:00, Audit at 18:00"

    log_action("Brief", "Morning brief sent")
    print(brief)
    return brief


def task_evening_summary() -> str:
    """Generate evening summary for Quenton."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note_path = DAILY_NOTES / f"{today}.md"

    summary = "EVENING SUMMARY:\n"
    if note_path.exists():
        with open(note_path, "r") as f:
            lines = f.readlines()
        summary += f"Actions today: {len(lines)}\n"
        for line in lines[-5:]:  # Last 5 entries
            summary += line
    else:
        summary += "No actions logged today.\n"

    # Check API access
    access = {
        "brevo": bool(os.environ.get("BREVO_API_KEY")),
        "twitter": bool(os.environ.get("TWITTER_API_KEY")),
    }
    missing = [k for k, v in access.items() if not v]
    if missing:
        summary += f"\nStill need: {', '.join(missing)} for full autonomy"

    log_action("Summary", "Evening summary sent")
    print(summary)
    return summary


# Schedule: UTC hour → task
# Runs 6 revenue tasks + 2 briefings across 24h cycle
SCHEDULE = {
    2: ("sleep", None),                         # 7pm PT — sleep
    6: ("morning_brief", task_morning_brief),   # 11pm PT — brief
    8: ("machina", task_machina),               # 1am PT — run all verticals
    10: ("sdr", task_sdr),                      # 3am PT — find leads
    12: ("felix_craft", task_felix_craft),       # 5am PT — build/sell products
    13: ("side_gigs", task_side_gigs),           # 6am PT — run all side gigs
    14: ("content", task_content),               # 7am PT — create content
    18: ("audit", task_audit),                   # 11am PT — check metrics
    22: ("evening_summary", task_evening_summary),  # 3pm PT — summary
}


def run_scheduled():
    """Run the task scheduled for the current UTC hour."""
    hour = datetime.now(timezone.utc).hour

    # Find the closest scheduled hour
    best_task = None
    best_name = "heartbeat_ok"
    min_diff = 24

    for sched_hour, (name, func) in SCHEDULE.items():
        diff = abs(hour - sched_hour)
        if diff < min_diff:
            min_diff = diff
            best_task = func
            best_name = name

    # Only run if within 2 hours of scheduled time
    if min_diff > 2 or best_task is None:
        print("HEARTBEAT_OK")
        log_action("Heartbeat", "No task scheduled, all clear")
        return

    print(f"[AUTO] Running scheduled task: {best_name} (UTC hour: {hour})")
    result = best_task()
    print(f"[AUTO] Task complete: {best_name}")


def show_schedule():
    """Show the full autonomous schedule."""
    print(f"\n{'='*60}")
    print(f"  AUTONOMOUS SCHEDULE")
    print(f"{'='*60}")
    for hour, (name, func) in sorted(SCHEDULE.items()):
        pt_hour = (hour - 7) % 24
        status = "ACTIVE" if func else "SLEEP"
        print(f"  {hour:02d}:00 UTC ({pt_hour:02d}:00 PT) — {name:20s} [{status}]")
    print(f"\n  Current UTC: {datetime.now(timezone.utc).strftime('%H:%M')}")
    print(f"  Today's target: {get_today_target()}")
    print(f"{'='*60}\n")


def force_run(task_name: str):
    """Force run a specific task."""
    tasks = {
        "sdr": task_sdr,
        "content": task_content,
        "audit": task_audit,
        "brief": task_morning_brief,
        "summary": task_evening_summary,
        "felix": task_felix_craft,
        "machina": task_machina,
        "gigs": task_side_gigs,
    }
    func = tasks.get(task_name)
    if func:
        print(f"[FORCE] Running: {task_name}")
        func()
    else:
        print(f"Unknown task: {task_name}. Options: {list(tasks.keys())}")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Scheduler")
    parser.add_argument("--run", action="store_true", help="Run scheduled task for current hour")
    parser.add_argument("--schedule", action="store_true", help="Show full schedule")
    parser.add_argument("--force", help="Force run a task: sdr, content, audit, brief, summary")
    args = parser.parse_args()

    if args.run:
        run_scheduled()
    elif args.schedule:
        show_schedule()
    elif args.force:
        force_run(args.force)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
