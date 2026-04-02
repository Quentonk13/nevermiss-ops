"""
Social Content Engine — Autonomous Content Creation
=====================================================
Based on Oliver's "Larry" agent pattern: $671 MRR, 8M views in 1 week.
Generates viral content for any platform without manual effort.

Usage:
    python3 content_engine.py --niche "HVAC contractors" --platform twitter --count 10
    python3 content_engine.py --niche "plumbing tips" --weekly
    python3 content_engine.py --hooks "contractor marketing" --count 20
    python3 content_engine.py --calendar --weeks 4
"""

import argparse
import json
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.environ.get("NEVERMISS_DB", "/app/data/nevermiss.db")
DATA_DIR = os.environ.get("NEVERMISS_DATA_DIR", "/app/data")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS content_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT,
        niche TEXT,
        content_type TEXT,
        hook TEXT,
        body TEXT,
        cta TEXT,
        hashtags TEXT,
        scheduled_for TEXT,
        posted_at TEXT,
        views INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0,
        comments INTEGER DEFAULT 0,
        shares INTEGER DEFAULT 0,
        status TEXT DEFAULT 'draft',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


# Proven viral hook frameworks (based on top-performing content patterns)
HOOK_FRAMEWORKS = [
    "Stop {doing_wrong} if you want {desired_result}",
    "I spent {time} studying {topic}. Here's what nobody tells you:",
    "The #1 mistake {audience} make with {topic} (and how to fix it)",
    "{Number} {topic} tips that took me from {before} to {after}",
    "Why {common_belief} is completely wrong about {topic}",
    "If you're a {audience}, you NEED to know this about {topic}",
    "I asked {number} {audience} their biggest {topic} secret. #3 blew my mind.",
    "Here's why {competitor} charges ${price} for something you can do free",
    "POV: You just discovered {topic} and now everything changes",
    "{Audience}: Are you making this ${cost} mistake?",
    "The {topic} hack that {authority} doesn't want you to know",
    "In {year}, {audience} who don't {action} will be left behind",
    "I replaced my {old_thing} with {new_thing}. Here's what happened:",
    "This {topic} trick saves {audience} {time/money} every {period}",
    "Nobody talks about this {topic} strategy (it works in {timeframe})",
]

CONTENT_TYPES = {
    "twitter": {
        "thread": {"min_posts": 5, "max_posts": 12, "chars": 280},
        "single": {"chars": 280},
        "poll": {"chars": 280, "options": 4},
    },
    "tiktok": {
        "script": {"min_seconds": 15, "max_seconds": 60},
        "hook_only": {"seconds": 3},
    },
    "linkedin": {
        "post": {"chars": 3000},
        "article": {"chars": 10000},
    },
    "instagram": {
        "caption": {"chars": 2200},
        "reel_script": {"min_seconds": 15, "max_seconds": 90},
    },
}

CTA_TEMPLATES = [
    "Follow for more {topic} tips",
    "Save this for later",
    "Share with a {audience} who needs this",
    "Drop a {emoji} if you agree",
    "Link in bio for the full guide",
    "Comment '{keyword}' and I'll send you the free template",
    "DM me '{keyword}' for the cheat sheet",
    "What's your experience with this? Comment below",
]

HASHTAG_SETS = {
    "contractor": ["#contractor #construction #hvac #plumbing #electrician #trades #bluecollar #smallbusiness #contractorlife #tradesman"],
    "marketing": ["#marketing #digitalmarketing #sales #leadgen #socialmedia #business #entrepreneur #growth #startup #hustle"],
    "ai": ["#ai #artificialintelligence #automation #tech #future #aitools #machinelearning #productivity #nocode #saas"],
    "business": ["#business #entrepreneur #startup #smallbusiness #hustle #money #success #motivation #ceo #founder"],
}


def generate_hooks(niche: str, count: int = 10) -> list[dict]:
    """Generate viral hooks based on proven frameworks."""
    hooks = []

    # Niche-specific fills
    niche_data = {
        "audience": f"{niche} professionals",
        "topic": niche,
        "desired_result": f"growing your {niche} business",
        "doing_wrong": f"ignoring {niche} marketing",
        "before": "$0", "after": "$10K/mo",
        "number": random.choice(["50", "100", "200", "500"]),
        "time": random.choice(["6 months", "1 year", "3 years"]),
        "competitor": "the big guys",
        "price": random.choice(["500", "1000", "2000", "5000"]),
        "cost": random.choice(["500", "1000", "5000"]),
        "authority": "the industry",
        "year": "2026",
        "action": "adapt to AI",
        "old_thing": "manual processes",
        "new_thing": "AI automation",
        "common_belief": "everyone",
        "timeframe": "30 days",
        "period": "month",
    }

    for i in range(count):
        framework = random.choice(HOOK_FRAMEWORKS)
        # Fill in template
        hook = framework
        for key, val in niche_data.items():
            hook = hook.replace(f"{{{key}}}", val)
            hook = hook.replace(f"{{{key.title()}}}", val.title())

        hooks.append({
            "hook": hook,
            "framework": framework,
            "niche": niche,
        })

    return hooks


def generate_twitter_thread(niche: str, topic: str = None) -> dict:
    """Generate a Twitter thread."""
    hook = generate_hooks(niche, 1)[0]["hook"]
    topic = topic or niche

    thread = {
        "platform": "twitter",
        "type": "thread",
        "hook": hook,
        "posts": [
            f"🧵 {hook}",
            f"First, let's talk about why most {niche} businesses struggle with growth.",
            f"The problem isn't your service quality — it's that nobody knows you exist.",
            f"Here's the 3-step system that changed everything:",
            f"Step 1: Stop relying on word-of-mouth alone. It's 2026. Your customers are online.",
            f"Step 2: Automate your outreach. Every day you don't reach out is money left on the table.",
            f"Step 3: Follow up relentlessly. 80% of deals happen after the 5th touch.",
            f"The best {niche} businesses I've seen implement this and see results in 2-3 weeks.",
            f"Want the full playbook? Follow me and I'll break it down this week.",
        ],
        "cta": random.choice(CTA_TEMPLATES).replace("{topic}", niche).replace("{audience}", f"{niche} pro").replace("{emoji}", "🔥").replace("{keyword}", "PLAYBOOK"),
    }
    return thread


def generate_tiktok_script(niche: str) -> dict:
    """Generate a TikTok/Reels script."""
    hook = generate_hooks(niche, 1)[0]["hook"]

    script = {
        "platform": "tiktok",
        "type": "script",
        "hook": hook,
        "script": f"""[HOOK - First 3 seconds]
"{hook}"

[PROBLEM - Seconds 3-10]
"Most {niche} businesses are leaving money on the table because they're still doing things the old way."

[AGITATE - Seconds 10-20]
"While you're waiting for the phone to ring, your competitors are using AI to find and close deals automatically."

[SOLUTION - Seconds 20-40]
"Here's what the top {niche} companies are doing differently in 2026..."
"They're using automated outreach to find leads, personalize every message, and follow up without lifting a finger."

[CTA - Last 5 seconds]
"Follow for more {niche} growth tips. Link in bio for the free guide."
""",
        "duration_estimate": "45 seconds",
        "hashtags": " ".join(random.choice(list(HASHTAG_SETS.values()))),
    }
    return script


def generate_linkedin_post(niche: str) -> dict:
    """Generate a LinkedIn post."""
    hook = generate_hooks(niche, 1)[0]["hook"]

    post = {
        "platform": "linkedin",
        "type": "post",
        "hook": hook,
        "body": f"""{hook}

I've been studying {niche} businesses for the past year, and the pattern is clear:

The ones growing fastest all share 3 things in common:

1️⃣ They automate lead generation (not just rely on referrals)
2️⃣ They personalize every touchpoint (not blast generic templates)
3️⃣ They follow up systematically (not "when they remember")

The technology to do all 3 exists today. Most {niche} businesses just don't know about it yet.

If you're in the {niche} space and want to grow without hiring a sales team, I'd love to chat.

What's your biggest growth challenge right now? 👇

#business #growth #{niche.replace(' ', '')} #automation #ai""",
    }
    return post


def generate_weekly_content(niche: str) -> list[dict]:
    """Generate a full week of content across platforms."""
    db = get_db()
    content = []
    today = datetime.utcnow()

    schedule = [
        ("monday", "twitter", "thread"),
        ("tuesday", "tiktok", "script"),
        ("wednesday", "linkedin", "post"),
        ("thursday", "twitter", "thread"),
        ("friday", "tiktok", "script"),
        ("saturday", "linkedin", "post"),
        ("sunday", "twitter", "thread"),
    ]

    for i, (day, platform, ctype) in enumerate(schedule):
        scheduled = today + timedelta(days=i)

        if platform == "twitter":
            post = generate_twitter_thread(niche)
        elif platform == "tiktok":
            post = generate_tiktok_script(niche)
        else:
            post = generate_linkedin_post(niche)

        # Store in DB
        db.execute(
            """INSERT INTO content_posts (platform, niche, content_type, hook, body, scheduled_for, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (platform, niche, ctype, post.get("hook", ""),
             json.dumps(post), scheduled.strftime("%Y-%m-%d"), "scheduled")
        )
        content.append({**post, "scheduled_for": scheduled.strftime("%Y-%m-%d (%A)")})

    db.commit()
    return content


def generate_content_calendar(niche: str, weeks: int = 4) -> list[dict]:
    """Generate a full content calendar."""
    all_content = []
    for week in range(weeks):
        weekly = generate_weekly_content(niche)
        all_content.extend(weekly)
        print(f"[Content] Week {week + 1}: {len(weekly)} posts generated")
    return all_content


def analyze_performance() -> dict:
    """Analyze content performance."""
    db = get_db()

    stats = {
        "total_posts": db.execute("SELECT COUNT(*) FROM content_posts").fetchone()[0],
        "posted": db.execute("SELECT COUNT(*) FROM content_posts WHERE status = 'posted'").fetchone()[0],
        "scheduled": db.execute("SELECT COUNT(*) FROM content_posts WHERE status = 'scheduled'").fetchone()[0],
        "drafts": db.execute("SELECT COUNT(*) FROM content_posts WHERE status = 'draft'").fetchone()[0],
        "total_views": db.execute("SELECT COALESCE(SUM(views), 0) FROM content_posts").fetchone()[0],
        "total_likes": db.execute("SELECT COALESCE(SUM(likes), 0) FROM content_posts").fetchone()[0],
        "total_comments": db.execute("SELECT COALESCE(SUM(comments), 0) FROM content_posts").fetchone()[0],
    }

    # Top performing posts
    top = db.execute(
        "SELECT hook, platform, views, likes FROM content_posts WHERE views > 0 ORDER BY views DESC LIMIT 5"
    ).fetchall()
    stats["top_posts"] = [dict(row) for row in top]

    print(f"\n{'='*50}")
    print(f"  Content Performance Report")
    print(f"{'='*50}")
    print(f"  Total posts: {stats['total_posts']}")
    print(f"  Posted: {stats['posted']} | Scheduled: {stats['scheduled']} | Drafts: {stats['drafts']}")
    print(f"  Total views: {stats['total_views']:,}")
    print(f"  Total likes: {stats['total_likes']:,}")
    print(f"  Total comments: {stats['total_comments']:,}")
    if stats["top_posts"]:
        print(f"\n  Top Posts:")
        for p in stats["top_posts"]:
            print(f"    [{p['platform']}] {p['hook'][:60]}... — {p['views']:,} views")
    print(f"{'='*50}\n")

    return stats


def larry_loop(niche: str = "contractor marketing"):
    """
    The Larry Loop — Oliver Henry's self-improving content feedback mechanism.
    3 stages:
      1. ANALYZE: Pull performance data (views + conversions)
      2. ITERATE: Classify failure type (hook failure vs CTA failure)
      3. EXECUTE: Generate 3-5 variations targeting the failure point

    - High views + low engagement = CTA FAILURE (call-to-action needs fixing)
    - Low views = HOOK FAILURE (opening needs fixing)
    - High views + high engagement = WINNER (make more like this)
    """
    db = get_db()

    print(f"\n{'='*60}")
    print(f"  LARRY LOOP — Self-Improving Content Cycle")
    print(f"  Niche: {niche}")
    print(f"{'='*60}")

    # Stage 1: ANALYZE
    print(f"\n  Stage 1: ANALYZE")
    posts = db.execute("""
        SELECT id, hook, body, platform, views, likes, comments, shares, content_type
        FROM content_posts WHERE status = 'posted' AND views > 0
        ORDER BY created_at DESC LIMIT 20
    """).fetchall()

    if not posts:
        print(f"  No posted content with analytics yet.")
        print(f"  Generating fresh content batch instead...")
        content = generate_weekly_content(niche)
        print(f"  Created {len(content)} posts. Post them, then run --larry-loop again.")
        return

    avg_views = sum(p["views"] for p in posts) / len(posts) if posts else 0
    avg_engagement = sum((p["likes"] or 0) + (p["comments"] or 0) + (p["shares"] or 0) for p in posts) / len(posts) if posts else 0

    print(f"  Analyzed {len(posts)} posts")
    print(f"  Avg views: {avg_views:.0f}")
    print(f"  Avg engagement: {avg_engagement:.0f}")

    # Stage 2: ITERATE — Classify each post
    print(f"\n  Stage 2: ITERATE — Classifying failures")
    winners = []
    hook_failures = []
    cta_failures = []

    for p in posts:
        views = p["views"] or 0
        engagement = (p["likes"] or 0) + (p["comments"] or 0) + (p["shares"] or 0)
        engagement_rate = engagement / views if views > 0 else 0

        if views >= avg_views * 1.5 and engagement_rate >= 0.03:
            winners.append(p)
        elif views < avg_views * 0.5:
            hook_failures.append(p)
        elif views >= avg_views and engagement_rate < 0.02:
            cta_failures.append(p)

    print(f"  Winners:       {len(winners)} (high views + high engagement)")
    print(f"  Hook failures: {len(hook_failures)} (low views — bad opening)")
    print(f"  CTA failures:  {len(cta_failures)} (high views, low engagement — bad CTA)")

    # Stage 3: EXECUTE — Generate variations
    print(f"\n  Stage 3: EXECUTE — Generating improved variations")

    new_content = []

    # Learn from winners — make more like them
    if winners:
        print(f"\n  Learning from {len(winners)} winners:")
        for w in winners[:3]:
            print(f"    WINNER: [{w['platform']}] {w['hook'][:60]}... ({w['views']} views)")
            # Generate 2 variations of each winner
            for i in range(2):
                hook = w["hook"]
                # Remix the winning hook with different angles
                remixed = _remix_winning_hook(hook, niche, i)
                new_content.append({
                    "platform": w["platform"],
                    "hook": remixed,
                    "based_on": w["id"],
                    "strategy": "winner_remix",
                })

    # Fix hook failures — try different openings
    if hook_failures:
        print(f"\n  Fixing {len(hook_failures)} hook failures:")
        for hf in hook_failures[:3]:
            print(f"    HOOK FAIL: [{hf['platform']}] {hf['hook'][:60]}... ({hf['views']} views)")
            # Generate new hook for same content
            new_hooks = generate_hooks(niche, count=3)
            for nh in new_hooks:
                new_content.append({
                    "platform": hf["platform"],
                    "hook": nh["hook"],
                    "based_on": hf["id"],
                    "strategy": "hook_fix",
                })

    # Fix CTA failures — try different calls-to-action
    if cta_failures:
        print(f"\n  Fixing {len(cta_failures)} CTA failures:")
        ctas = [
            "Save this for later — you'll need it.",
            "Tag someone who needs to see this.",
            "Follow for more tips like this.",
            "DM me '{niche}' for the free guide.",
            "Link in bio — grab it before I take it down.",
            "Drop a comment if you want the full breakdown.",
        ]
        for cf in cta_failures[:3]:
            print(f"    CTA FAIL: [{cf['platform']}] {cf['hook'][:60]}... ({cf['views']} views, low engage)")
            cta = random.choice(ctas).replace("{niche}", niche.split()[0])
            new_content.append({
                "platform": cf["platform"],
                "hook": cf["hook"],  # Keep the hook (it worked)
                "cta": cta,
                "based_on": cf["id"],
                "strategy": "cta_fix",
            })

    # Save new content to DB
    for c in new_content:
        db.execute(
            "INSERT INTO content_posts (platform, niche, hook, cta, status) VALUES (?,?,?,?,?)",
            (c["platform"], niche, c["hook"], c.get("cta", ""), "draft")
        )
    db.commit()

    print(f"\n{'─'*60}")
    print(f"  LARRY LOOP COMPLETE")
    print(f"  Generated: {len(new_content)} new variations")
    print(f"    - {sum(1 for c in new_content if c['strategy'] == 'winner_remix')} winner remixes")
    print(f"    - {sum(1 for c in new_content if c['strategy'] == 'hook_fix')} hook fixes")
    print(f"    - {sum(1 for c in new_content if c['strategy'] == 'cta_fix')} CTA fixes")
    print(f"  Next: Post them, collect data, run --larry-loop again")
    print(f"{'='*60}\n")


def _remix_winning_hook(hook: str, niche: str, variant: int) -> str:
    """Remix a winning hook with a different angle."""
    remixes = [
        lambda h, n: h.replace(n.split()[0], n.split()[-1]) if len(n.split()) > 1 else f"Updated: {h}",
        lambda h, n: f"Part 2: {h}" if "Part" not in h else f"The sequel: {h}",
        lambda h, n: f"Everyone asked about this: {h[:50]}...",
        lambda h, n: f"I got 100 DMs about this. Here's the update: {h[:40]}...",
        lambda h, n: h.replace("mistake", "secret").replace("wrong", "backwards") if "mistake" in h.lower() or "wrong" in h.lower() else f"New angle: {h}",
    ]
    return remixes[variant % len(remixes)](hook, niche)


def main():
    parser = argparse.ArgumentParser(description="Social Content Engine")
    parser.add_argument("--niche", help="Content niche (e.g., 'HVAC contractors')")
    parser.add_argument("--platform", choices=["twitter", "tiktok", "linkedin", "instagram"], help="Target platform")
    parser.add_argument("--count", type=int, default=10, help="Number of items to generate")
    parser.add_argument("--hooks", help="Generate viral hooks for a topic")
    parser.add_argument("--weekly", action="store_true", help="Generate a week of content")
    parser.add_argument("--calendar", action="store_true", help="Generate full content calendar")
    parser.add_argument("--weeks", type=int, default=4, help="Number of weeks for calendar")
    parser.add_argument("--analyze", action="store_true", help="Analyze content performance")
    parser.add_argument("--larry-loop", action="store_true", dest="larry_loop",
                        help="Run Larry Loop: analyze → classify failures → generate variations")
    args = parser.parse_args()

    if args.hooks:
        hooks = generate_hooks(args.hooks, args.count)
        print(f"\n🔥 {len(hooks)} Viral Hooks for '{args.hooks}':\n")
        for i, h in enumerate(hooks, 1):
            print(f"  {i}. {h['hook']}")
        print()

    elif args.weekly and args.niche:
        content = generate_weekly_content(args.niche)
        print(f"\n📅 Weekly Content Plan for '{args.niche}':\n")
        for c in content:
            print(f"  {c['scheduled_for']}: [{c['platform']}] {c.get('hook', '')[:80]}")
        print(f"\n  Total: {len(content)} posts scheduled\n")

    elif args.calendar and args.niche:
        content = generate_content_calendar(args.niche, args.weeks)
        print(f"\n📅 {args.weeks}-Week Calendar: {len(content)} posts generated\n")

    elif args.analyze:
        analyze_performance()

    elif args.larry_loop:
        larry_loop(args.niche or "contractor marketing")

    elif args.niche and args.platform:
        if args.platform == "twitter":
            for _ in range(args.count):
                thread = generate_twitter_thread(args.niche)
                print(f"\n📝 Thread: {thread['hook']}")
                for j, post in enumerate(thread['posts'], 1):
                    print(f"  {j}. {post}")
                print()
        elif args.platform == "tiktok":
            for _ in range(args.count):
                script = generate_tiktok_script(args.niche)
                print(f"\n🎬 TikTok Script:")
                print(script["script"])
        elif args.platform == "linkedin":
            for _ in range(args.count):
                post = generate_linkedin_post(args.niche)
                print(f"\n💼 LinkedIn Post:")
                print(post["body"])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
