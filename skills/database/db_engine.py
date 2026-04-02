"""
NeverMiss Database Layer
========================
SQLite-backed persistence for leads, campaigns, emails, conversations,
revenue tracking, API usage, and daily metrics.

Tables are auto-created on import. DB file lives at /app/data/nevermiss.db
(falls back to ./data/nevermiss.db locally).
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, date
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_DIR = os.environ.get("NEVERMISS_DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "nevermiss.db")

_local = threading.local()

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return a thread-local connection with row-factory enabled."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


@contextmanager
def _cursor():
    """Yield a cursor that auto-commits or rolls back."""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    email       TEXT,
    phone       TEXT,
    company     TEXT,
    trade       TEXT,
    city        TEXT,
    state       TEXT,
    source      TEXT,
    score       INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'new',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS campaigns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    template_id TEXT,
    status      TEXT DEFAULT 'draft',
    sent_count  INTEGER DEFAULT 0,
    open_count  INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS emails_sent (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER REFERENCES leads(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    subject     TEXT,
    status      TEXT DEFAULT 'queued',
    sent_at     TEXT,
    opened_at   TEXT,
    replied_at  TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id       INTEGER REFERENCES leads(id),
    channel       TEXT,
    messages_json TEXT DEFAULT '[]',
    status        TEXT DEFAULT 'open',
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS revenue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id    INTEGER REFERENCES leads(id),
    amount     REAL NOT NULL,
    type       TEXT,
    status     TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    provider   TEXT,
    endpoint   TEXT,
    tokens_in  INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd   REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT UNIQUE NOT NULL,
    leads_sourced INTEGER DEFAULT 0,
    emails_sent   INTEGER DEFAULT 0,
    replies       INTEGER DEFAULT 0,
    demos_booked  INTEGER DEFAULT 0,
    deals_closed  INTEGER DEFAULT 0,
    revenue       REAL DEFAULT 0.0,
    api_cost      REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_leads_email   ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads(status);
CREATE INDEX IF NOT EXISTS idx_emails_lead   ON emails_sent(lead_id);
CREATE INDEX IF NOT EXISTS idx_conv_lead     ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_api_created   ON api_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_metrics_date  ON daily_metrics(date);
"""


def _init_db():
    """Create all tables if they don't already exist."""
    conn = _get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# Lead helpers
# ---------------------------------------------------------------------------

def add_lead(
    name: str,
    email: str,
    phone: str = "",
    company: str = "",
    trade: str = "",
    city: str = "",
    state: str = "",
    source: str = "",
    score: int = 0,
    status: str = "new",
) -> int:
    """Insert a lead and return its id."""
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO leads
               (name, email, phone, company, trade, city, state, source, score, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, email, phone, company, trade, city, state, source, score, status),
        )
        return cur.lastrowid


def get_leads(
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Fetch leads with optional filters. Returns list of dicts."""
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params += [limit, offset]
    with _cursor() as cur:
        cur.execute(
            f"SELECT * FROM leads {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def update_lead_status(lead_id: int, status: str) -> bool:
    """Update a lead's status. Returns True if a row was changed."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE leads SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, lead_id),
        )
        return cur.rowcount > 0


def get_lead_by_email(email: str) -> Optional[dict]:
    """Look up a single lead by email."""
    with _cursor() as cur:
        cur.execute("SELECT * FROM leads WHERE email = ?", (email,))
        row = cur.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Email / campaign helpers
# ---------------------------------------------------------------------------

def log_email(
    lead_id: int,
    campaign_id: Optional[int],
    subject: str,
    status: str = "sent",
) -> int:
    """Record an outbound email. Returns the email row id."""
    sent_at = datetime.utcnow().isoformat() if status == "sent" else None
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO emails_sent (lead_id, campaign_id, subject, status, sent_at)
               VALUES (?, ?, ?, ?, ?)""",
            (lead_id, campaign_id, subject, status, sent_at),
        )
        return cur.lastrowid


def update_email_event(email_id: int, event: str) -> bool:
    """Mark an email as opened or replied. event = 'opened' | 'replied'."""
    col = "opened_at" if event == "opened" else "replied_at"
    with _cursor() as cur:
        cur.execute(
            f"UPDATE emails_sent SET {col} = datetime('now'), status = ? WHERE id = ?",
            (event, email_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# API usage tracking
# ---------------------------------------------------------------------------

def log_api_usage(
    provider: str,
    endpoint: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> int:
    """Log a single API call for cost tracking."""
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO api_usage (provider, endpoint, tokens_in, tokens_out, cost_usd)
               VALUES (?, ?, ?, ?, ?)""",
            (provider, endpoint, tokens_in, tokens_out, cost_usd),
        )
        return cur.lastrowid


def get_api_cost_today() -> float:
    """Sum of API costs for the current UTC day."""
    today = date.today().isoformat()
    with _cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE date(created_at) = ?",
            (today,),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

def log_revenue(
    lead_id: int,
    amount: float,
    type_: str = "deal",
    status: str = "pending",
) -> int:
    """Record a revenue event."""
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO revenue (lead_id, amount, type, status) VALUES (?, ?, ?, ?)",
            (lead_id, amount, type_, status),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Daily metrics
# ---------------------------------------------------------------------------

def get_daily_metrics(day: Optional[str] = None) -> Optional[dict]:
    """Return metrics row for a given date (YYYY-MM-DD). Defaults to today."""
    day = day or date.today().isoformat()
    with _cursor() as cur:
        cur.execute("SELECT * FROM daily_metrics WHERE date = ?", (day,))
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_daily_metrics(day: Optional[str] = None, **kwargs) -> None:
    """Increment daily metric counters. Accepts any column name from daily_metrics.

    Example: upsert_daily_metrics(emails_sent=5, api_cost=0.03)
    """
    day = day or date.today().isoformat()
    allowed = {
        "leads_sourced", "emails_sent", "replies",
        "demos_booked", "deals_closed", "revenue", "api_cost",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return

    set_clause = ", ".join(f"{k} = {k} + ?" for k in updates)
    vals = list(updates.values())

    with _cursor() as cur:
        # Try update first
        cur.execute(
            f"UPDATE daily_metrics SET {set_clause} WHERE date = ?",
            vals + [day],
        )
        if cur.rowcount == 0:
            # Insert with defaults then apply
            cur.execute(
                "INSERT INTO daily_metrics (date) VALUES (?)", (day,)
            )
            cur.execute(
                f"UPDATE daily_metrics SET {set_clause} WHERE date = ?",
                vals + [day],
            )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

def add_conversation(lead_id: int, channel: str, messages: list | None = None) -> int:
    """Start a new conversation thread."""
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO conversations (lead_id, channel, messages_json)
               VALUES (?, ?, ?)""",
            (lead_id, channel, json.dumps(messages or [])),
        )
        return cur.lastrowid


def append_message(conversation_id: int, role: str, text: str) -> None:
    """Append a message to an existing conversation's JSON array."""
    with _cursor() as cur:
        cur.execute(
            "SELECT messages_json FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Conversation {conversation_id} not found")
        msgs = json.loads(row["messages_json"])
        msgs.append({"role": role, "text": text, "ts": datetime.utcnow().isoformat()})
        cur.execute(
            """UPDATE conversations
               SET messages_json = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (json.dumps(msgs), conversation_id),
        )


# ---------------------------------------------------------------------------
# Generic query escape hatch
# ---------------------------------------------------------------------------

def execute(sql: str, params: tuple = ()) -> list[dict]:
    """Run arbitrary read SQL. Returns list of dicts."""
    with _cursor() as cur:
        cur.execute(sql, params)
        if cur.description:
            return [dict(r) for r in cur.fetchall()]
        return []


# ---------------------------------------------------------------------------
# Auto-init on import
# ---------------------------------------------------------------------------
_init_db()
