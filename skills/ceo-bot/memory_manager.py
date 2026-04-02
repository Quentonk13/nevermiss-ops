#!/usr/bin/env python3
"""
Memory Manager — 3-Layer Memory System for CEO-Bot
Layer 1: Knowledge Graph (data/ceo_memory/knowledge/*.md)
Layer 2: Daily Notes (data/ceo_memory/daily_notes/)
Layer 3: Tacit Knowledge (data/ceo_memory/tacit/*.md)
Plus improvement and delegation logging.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CEO_MEMORY_DIR = os.path.join(DATA_DIR, "ceo_memory")
KNOWLEDGE_DIR = os.path.join(CEO_MEMORY_DIR, "knowledge")
DAILY_NOTES_DIR = os.path.join(CEO_MEMORY_DIR, "daily_notes")
TACIT_DIR = os.path.join(CEO_MEMORY_DIR, "tacit")
IMPROVEMENTS_LOG = os.path.join(CEO_MEMORY_DIR, "improvements_log.jsonl")
DELEGATIONS_LOG = os.path.join(CEO_MEMORY_DIR, "delegations_log.jsonl")
LOG_PATH = os.path.join(DATA_DIR, "system_log.jsonl")

CRM_ENGINE = None


def _get_crm_engine():
    """Lazy-load CRM engine module to avoid import issues at module level."""
    global CRM_ENGINE
    if CRM_ENGINE is None:
        import importlib.util
        crm_path = os.path.join(PROJECT_ROOT, "skills", "crm-engine", "crm_engine.py")
        spec = importlib.util.spec_from_file_location("crm_engine", crm_path)
        crm_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(crm_module)
        CRM_ENGINE = crm_module
    return CRM_ENGINE


def _log(action: str, result: str, details: str) -> None:
    """Append structured log entry to system_log.jsonl."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "ceo-bot",
        "action": action,
        "lead_id": None,
        "result": result,
        "details": details,
        "llm_used": "none",
        "tokens_estimated": 0,
        "cost_estimated": 0.0,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _ensure_dirs() -> None:
    """Create all memory directories if they do not exist."""
    for d in [KNOWLEDGE_DIR, DAILY_NOTES_DIR, TACIT_DIR,
              os.path.dirname(IMPROVEMENTS_LOG), os.path.dirname(DELEGATIONS_LOG)]:
        os.makedirs(d, exist_ok=True)


# ── Layer 1: Knowledge Graph ──────────────────────────────────────────

def update_knowledge(topic: str, content: str) -> str:
    """Write or overwrite a knowledge file for *topic*.

    The topic is slugified to form the filename. Content is structured markdown
    capturing durable business facts (e.g., competitor analysis, pricing model,
    ideal customer profile).

    Returns the path to the written file.
    """
    _ensure_dirs()
    slug = topic.lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
    path = os.path.join(KNOWLEDGE_DIR, f"{slug}.md")

    now = datetime.now(timezone.utc).isoformat()
    header = f"# {topic}\n\n_Last updated: {now}_\n\n"

    with open(path, "w") as f:
        f.write(header + content + "\n")

    _log("memory_update_knowledge", "success", f"topic={topic} path={path} bytes={len(content)}")
    return path


# ── Layer 2: Daily Notes ──────────────────────────────────────────────

def write_daily_note(date: str, content: str) -> str:
    """Write the daily note for a given date (YYYY-MM-DD).

    Content should include decisions made, learnings, key events, and any
    anomalies observed during the nightly review cycle.

    Returns the path to the written file.
    """
    _ensure_dirs()
    path = os.path.join(DAILY_NOTES_DIR, f"{date}.md")

    header = f"# Daily Note — {date}\n\n"

    # Append if the file already exists (morning brief + nightly can both write)
    if os.path.exists(path):
        with open(path, "a") as f:
            f.write(f"\n---\n\n_Appended at {datetime.now(timezone.utc).isoformat()}_\n\n")
            f.write(content + "\n")
    else:
        with open(path, "w") as f:
            f.write(header + content + "\n")

    _log("memory_write_daily_note", "success", f"date={date} path={path}")
    return path


# ── Layer 3: Tacit Knowledge ─────────────────────────────────────────

def add_tacit_knowledge(category: str, rule: str) -> str:
    """Append a tacit-knowledge rule under *category*.

    Tacit knowledge captures hard-won lessons: owner preferences, things that
    don't work, edge cases, and behavioral constraints learned from experience.

    Each category is a markdown file; rules are appended as bullet points with
    timestamps so we can track when they were learned.

    Returns the path to the updated file.
    """
    _ensure_dirs()
    slug = category.lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
    path = os.path.join(TACIT_DIR, f"{slug}.md")

    now = datetime.now(timezone.utc).isoformat()

    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(f"# Tacit Knowledge — {category}\n\n")

    with open(path, "a") as f:
        f.write(f"- [{now}] {rule}\n")

    _log("memory_add_tacit", "success", f"category={category} rule_len={len(rule)}")
    return path


# ── Knowledge Summary ─────────────────────────────────────────────────

def get_knowledge_summary() -> dict:
    """Aggregate all three memory layers into a context dict for Claude.

    Returns a dictionary with keys: knowledge, daily_notes, tacit, stats.
    The CRM pipeline snapshot is included via crm-engine for completeness.
    """
    _ensure_dirs()
    summary: dict = {"knowledge": {}, "daily_notes": [], "tacit": {}, "stats": {}}

    # Layer 1: knowledge files
    if os.path.isdir(KNOWLEDGE_DIR):
        for fname in sorted(os.listdir(KNOWLEDGE_DIR)):
            if fname.endswith(".md"):
                with open(os.path.join(KNOWLEDGE_DIR, fname), "r") as f:
                    summary["knowledge"][fname.replace(".md", "")] = f.read()

    # Layer 2: last 7 daily notes
    if os.path.isdir(DAILY_NOTES_DIR):
        notes = sorted(
            [n for n in os.listdir(DAILY_NOTES_DIR) if n.endswith(".md")],
            reverse=True,
        )
        for fname in notes[:7]:
            with open(os.path.join(DAILY_NOTES_DIR, fname), "r") as f:
                summary["daily_notes"].append({"date": fname.replace(".md", ""), "content": f.read()})

    # Layer 3: tacit knowledge files
    if os.path.isdir(TACIT_DIR):
        for fname in sorted(os.listdir(TACIT_DIR)):
            if fname.endswith(".md"):
                with open(os.path.join(TACIT_DIR, fname), "r") as f:
                    summary["tacit"][fname.replace(".md", "")] = f.read()

    # CRM pipeline snapshot
    try:
        crm = _get_crm_engine()
        pipeline = crm.get_pipeline_data()
        summary["stats"]["crm_metrics"] = pipeline.get("metrics", {})
        summary["stats"]["total_leads"] = len(pipeline.get("leads", {}))
    except Exception as exc:
        summary["stats"]["crm_error"] = str(exc)

    # Recent improvements
    summary["stats"]["recent_improvements"] = _read_recent_jsonl(IMPROVEMENTS_LOG, 10)

    # Recent delegations
    summary["stats"]["recent_delegations"] = _read_recent_jsonl(DELEGATIONS_LOG, 10)

    _log("memory_get_summary", "success",
         f"knowledge={len(summary['knowledge'])} notes={len(summary['daily_notes'])} "
         f"tacit={len(summary['tacit'])}")
    return summary


# ── Improvement Log ───────────────────────────────────────────────────

def log_improvement(improvement: dict) -> None:
    """Append an improvement entry to improvements_log.jsonl.

    Expected keys in *improvement*: description, skill_affected, change_made,
    expected_impact, reversible (bool), measurement_metric.
    """
    _ensure_dirs()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **improvement,
    }
    with open(IMPROVEMENTS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    _log("memory_log_improvement", "success",
         f"description={improvement.get('description', 'n/a')[:120]}")


# ── Delegation Log ────────────────────────────────────────────────────

def log_delegation(delegation: dict) -> None:
    """Append a delegation entry to delegations_log.jsonl.

    Expected keys in *delegation*: target_skill, task_description, priority,
    status, triggered_by, outcome.
    """
    _ensure_dirs()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **delegation,
    }
    with open(DELEGATIONS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    _log("memory_log_delegation", "success",
         f"target={delegation.get('target_skill', 'n/a')} "
         f"task={delegation.get('task_description', 'n/a')[:100]}")


# ── Helpers ───────────────────────────────────────────────────────────

def _read_recent_jsonl(path: str, count: int) -> list:
    """Read the last *count* entries from a JSONL file."""
    if not os.path.exists(path):
        return []
    entries: list = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-count:]
