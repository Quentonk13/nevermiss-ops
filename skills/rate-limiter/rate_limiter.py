"""
API Rate Limiter for NeverMiss autonomous revenue engine.

Tracks per-provider API call rates, enforces configurable limits,
persists state to JSON, and implements adaptive backoff when limits are hit.
Thread-safe with file locking.
"""

import json
import os
import time
import threading
import fcntl
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_LIMITS = {
    "anthropic": 15,
    "groq": 30,
    "apollo": 20,
    "instantly": 10,
    "google": 5,
}

STATE_FILE = Path("/app/data/rate_limits.json")
DAILY_NOTES_DIR = Path("/app/data/ceo_memory/daily_notes")
BACKOFF_DURATION_S = 600  # 10 minutes
LOG_EVERY_N = 50          # write a daily-note log line every N calls

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_dirs():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_NOTES_DIR.mkdir(parents=True, exist_ok=True)


def _blank_provider(provider: str) -> dict:
    return {
        "calls": [],           # list of unix-epoch floats within the window
        "total_calls": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_cost": 0.0,
        "limit_rpm": DEFAULT_LIMITS.get(provider, 10),
        "backoff_until": 0,    # epoch; if > now, limit is halved
        "original_limit": DEFAULT_LIMITS.get(provider, 10),
    }


def _load_state() -> dict:
    """Load state from disk with a shared (read) lock."""
    _ensure_dirs()
    if not STATE_FILE.exists():
        return {"providers": {}, "global_call_count": 0}
    try:
        with open(STATE_FILE, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return data
    except (json.JSONDecodeError, IOError):
        return {"providers": {}, "global_call_count": 0}


def _save_state(state: dict):
    """Save state to disk with an exclusive (write) lock."""
    _ensure_dirs()
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, STATE_FILE)


def _prune_window(calls: list, now: float) -> list:
    """Remove call timestamps older than 60 seconds."""
    cutoff = now - 60.0
    return [t for t in calls if t > cutoff]


def _effective_limit(prov: dict, now: float) -> int:
    """Return current RPM limit, halved during backoff."""
    if now < prov.get("backoff_until", 0):
        return max(1, prov["limit_rpm"] // 2)
    return prov["limit_rpm"]


def _log_to_daily_notes(message: str):
    """Append a line to today's daily note file."""
    _ensure_dirs()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DAILY_NOTES_DIR / f"{today}.md"
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"- [{ts}] [rate-limiter] {message}\n"
    try:
        with open(path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(line)
            fcntl.flock(f, fcntl.LOCK_UN)
    except IOError:
        pass  # best-effort logging


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def can_call(provider: str) -> bool:
    """Return True if we can make a call to *provider* right now."""
    provider = provider.lower()
    with _lock:
        state = _load_state()
        prov = state["providers"].get(provider)
        if prov is None:
            return True  # no history => allowed
        now = time.time()
        calls = _prune_window(prov["calls"], now)
        limit = _effective_limit(prov, now)
        return len(calls) < limit


def record_call(
    provider: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost: float = 0.0,
):
    """Record a completed API call for *provider*."""
    provider = provider.lower()
    with _lock:
        state = _load_state()
        now = time.time()

        if provider not in state["providers"]:
            state["providers"][provider] = _blank_provider(provider)

        prov = state["providers"][provider]
        prov["calls"] = _prune_window(prov["calls"], now)
        prov["calls"].append(now)
        prov["total_calls"] += 1
        prov["total_tokens_in"] += tokens_in
        prov["total_tokens_out"] += tokens_out
        prov["total_cost"] += cost

        # Check if we just hit the limit -> trigger backoff
        limit = _effective_limit(prov, now)
        if len(prov["calls"]) >= limit:
            prov["backoff_until"] = now + BACKOFF_DURATION_S

        state["global_call_count"] = state.get("global_call_count", 0) + 1

        _save_state(state)

        # Log every N calls
        if state["global_call_count"] % LOG_EVERY_N == 0:
            summary_parts = []
            for name, p in state["providers"].items():
                summary_parts.append(
                    f"{name}: {p['total_calls']} calls, ${p['total_cost']:.4f}"
                )
            _log_to_daily_notes(
                f"Milestone {state['global_call_count']} calls. "
                + " | ".join(summary_parts)
            )


def wait_if_needed(provider: str):
    """Block until a call to *provider* is allowed."""
    provider = provider.lower()
    while not can_call(provider):
        # Calculate sleep: find earliest call that will expire
        with _lock:
            state = _load_state()
            prov = state["providers"].get(provider)
        if prov is None:
            return
        now = time.time()
        calls = _prune_window(prov["calls"], now)
        if not calls:
            return
        earliest = min(calls)
        wait = max(0.1, (earliest + 60.0) - now)
        time.sleep(min(wait, 5.0))  # cap sleep at 5s to re-check


def get_usage_stats() -> dict:
    """Return a summary dict of usage across all providers."""
    with _lock:
        state = _load_state()
    now = time.time()
    result = {}
    for name, prov in state.get("providers", {}).items():
        calls_in_window = _prune_window(prov["calls"], now)
        limit = _effective_limit(prov, now)
        in_backoff = now < prov.get("backoff_until", 0)
        result[name] = {
            "calls_this_minute": len(calls_in_window),
            "effective_limit_rpm": limit,
            "nominal_limit_rpm": prov["limit_rpm"],
            "in_backoff": in_backoff,
            "backoff_remaining_s": (
                round(prov["backoff_until"] - now, 1) if in_backoff else 0
            ),
            "total_calls": prov["total_calls"],
            "total_tokens_in": prov["total_tokens_in"],
            "total_tokens_out": prov["total_tokens_out"],
            "total_cost": round(prov["total_cost"], 6),
        }
    result["_global_call_count"] = state.get("global_call_count", 0)
    return result


def reset_provider(provider: str):
    """Reset all counters and history for *provider*."""
    provider = provider.lower()
    with _lock:
        state = _load_state()
        state["providers"][provider] = _blank_provider(provider)
        _save_state(state)


def set_limit(provider: str, rpm: int):
    """Override the RPM limit for *provider*."""
    provider = provider.lower()
    with _lock:
        state = _load_state()
        if provider not in state["providers"]:
            state["providers"][provider] = _blank_provider(provider)
        state["providers"][provider]["limit_rpm"] = rpm
        state["providers"][provider]["original_limit"] = rpm
        _save_state(state)


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python rate_limiter.py [status|reset <provider>|test]")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        stats = get_usage_stats()
        for name, info in sorted(stats.items()):
            if name.startswith("_"):
                continue
            flag = " [BACKOFF]" if info["in_backoff"] else ""
            print(
                f"  {name:12s}  "
                f"{info['calls_this_minute']:3d}/{info['effective_limit_rpm']} rpm  "
                f"total={info['total_calls']}  "
                f"cost=${info['total_cost']:.4f}{flag}"
            )
        print(f"  Global calls: {stats.get('_global_call_count', 0)}")

    elif cmd == "reset" and len(sys.argv) >= 3:
        reset_provider(sys.argv[2])
        print(f"Reset {sys.argv[2]}")

    elif cmd == "test":
        print("Recording 3 test calls to 'anthropic'...")
        for i in range(3):
            record_call("anthropic", tokens_in=100, tokens_out=50, cost=0.002)
        print(f"can_call('anthropic') = {can_call('anthropic')}")
        stats = get_usage_stats()
        print(f"anthropic stats: {json.dumps(stats.get('anthropic', {}), indent=2)}")

    else:
        print(f"Unknown command: {cmd}")
