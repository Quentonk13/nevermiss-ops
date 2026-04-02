"""
Content Queue — Bridge Between Bot and Manual Posting
=======================================================
For platforms the bot CAN'T auto-post to (Facebook, LinkedIn,
Craigslist, Instagram, TikTok), content goes here.

The bot creates the content, saves it to the queue, and notifies
Quenton via Telegram with the content ready to copy-paste.

For platforms the bot CAN auto-post to (Twitter, Bluesky, email),
it posts directly and logs the result.

Usage:
    python3 content_queue.py --add --platform facebook --content "post text here"
    python3 content_queue.py --list                    # Show pending queue
    python3 content_queue.py --done 3                  # Mark item #3 as posted
    python3 content_queue.py --export                  # Export all pending as text
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("NEVERMISS_DB", "/app/data/nevermiss.db")
QUEUE_DIR = "/app/data/content_queue"


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS content_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        content TEXT NOT NULL,
        content_type TEXT DEFAULT 'post',
        status TEXT DEFAULT 'pending',
        auto_postable INTEGER DEFAULT 0,
        posted_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    )""")
    conn.commit()
    return conn


# Which platforms can be auto-posted to
AUTO_PLATFORMS = {
    "telegram": True,
    "twitter": True,   # If TWITTER_API_KEY is set
    "bluesky": True,   # If BLUESKY_APP_PASSWORD is set
    "email": True,     # If BREVO_API_KEY is set
}

MANUAL_PLATFORMS = {
    "facebook": "Copy-paste to Facebook. No API access.",
    "linkedin": "Copy-paste to LinkedIn. No free posting API.",
    "craigslist": "Post manually on craigslist.org. No API exists.",
    "instagram": "Post via Instagram app. No free API.",
    "tiktok": "Post via TikTok app. No free API.",
}


def add_to_queue(platform: str, content: str, content_type: str = "post", notes: str = ""):
    db = get_db()
    auto = 1 if platform.lower() in AUTO_PLATFORMS else 0
    db.execute(
        "INSERT INTO content_queue (platform, content, content_type, auto_postable, notes) VALUES (?,?,?,?,?)",
        (platform.lower(), content, content_type, auto, notes)
    )
    db.commit()

    # Also save to file for easy access
    os.makedirs(QUEUE_DIR, exist_ok=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    filepath = os.path.join(QUEUE_DIR, f"{today}_{platform.lower()}.txt")
    with open(filepath, "a") as f:
        f.write(f"\n--- {content_type} ({datetime.utcnow().strftime('%H:%M')}) ---\n")
        f.write(content)
        f.write("\n")

    status = "AUTO-POSTABLE" if auto else "MANUAL — needs Quenton to post"
    print(f"[queue] Added {platform} {content_type}: {status}")
    if not auto:
        print(f"[queue] Instructions: {MANUAL_PLATFORMS.get(platform.lower(), 'Post manually')}")
    return auto


def list_queue(status: str = "pending"):
    db = get_db()
    items = db.execute(
        "SELECT * FROM content_queue WHERE status = ? ORDER BY created_at DESC",
        (status,)
    ).fetchall()

    if not items:
        print(f"[queue] No {status} items")
        return []

    print(f"\n{'='*60}")
    print(f"  Content Queue — {len(items)} {status} items")
    print(f"{'='*60}")
    for item in items:
        auto = "AUTO" if item["auto_postable"] else "MANUAL"
        preview = item["content"][:80].replace("\n", " ")
        print(f"  #{item['id']} [{auto}] {item['platform']:12s} | {item['content_type']:8s} | {preview}...")
    print(f"{'='*60}\n")
    return [dict(i) for i in items]


def mark_done(item_id: int):
    db = get_db()
    db.execute(
        "UPDATE content_queue SET status = 'posted', posted_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), item_id)
    )
    db.commit()
    print(f"[queue] Item #{item_id} marked as posted")


def export_pending():
    db = get_db()
    items = db.execute(
        "SELECT * FROM content_queue WHERE status = 'pending' AND auto_postable = 0 ORDER BY platform, created_at"
    ).fetchall()

    if not items:
        print("[queue] No manual items pending")
        return ""

    output = []
    current_platform = ""
    for item in items:
        if item["platform"] != current_platform:
            current_platform = item["platform"]
            output.append(f"\n=== {current_platform.upper()} ===\n")
            if current_platform in MANUAL_PLATFORMS:
                output.append(f"Instructions: {MANUAL_PLATFORMS[current_platform]}\n")

        output.append(f"--- #{item['id']} ({item['content_type']}) ---")
        output.append(item["content"])
        output.append("")

    text = "\n".join(output)
    print(text)

    # Save export
    os.makedirs(QUEUE_DIR, exist_ok=True)
    export_path = os.path.join(QUEUE_DIR, f"export_{datetime.utcnow().strftime('%Y-%m-%d_%H%M')}.txt")
    with open(export_path, "w") as f:
        f.write(text)
    print(f"\n[queue] Exported to {export_path}")
    return text


def main():
    parser = argparse.ArgumentParser(description="Content Queue Manager")
    parser.add_argument("--add", action="store_true", help="Add to queue")
    parser.add_argument("--platform", help="Platform name")
    parser.add_argument("--content", help="Content text")
    parser.add_argument("--type", default="post", help="Content type")
    parser.add_argument("--list", action="store_true", help="List pending queue")
    parser.add_argument("--done", type=int, help="Mark item as posted")
    parser.add_argument("--export", action="store_true", help="Export manual items")
    parser.add_argument("--all", action="store_true", help="List all items")
    args = parser.parse_args()

    if args.add and args.platform and args.content:
        add_to_queue(args.platform, args.content, args.type)
    elif args.list:
        list_queue("pending")
    elif args.all:
        list_queue("pending")
        list_queue("posted")
    elif args.done:
        mark_done(args.done)
    elif args.export:
        export_pending()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
