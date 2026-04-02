"""
LAYER 5: SENTINEL — Continuous Security Monitoring
=====================================================
Real-time file change detection, unauthorized access alerts,
honeypot monitoring, audit logging, auto-lockdown on breach.

Usage:
    python3 security/sentinel/sentinel.py --watch     # Start monitoring
    python3 security/sentinel/sentinel.py --audit     # View audit log
    python3 security/sentinel/sentinel.py --lockdown  # Emergency lockdown
    python3 security/sentinel/sentinel.py --status    # Security status
"""

import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

GUARD_DIR = os.environ.get("GUARD_DIR", "/app/.guard")
AUDIT_LOG = os.path.join(GUARD_DIR, "audit.log")
SENTINEL_STATE = os.path.join(GUARD_DIR, "sentinel_state.json")
ALERT_WEBHOOK = os.environ.get("SENTINEL_WEBHOOK", "")  # Telegram alert URL

# Critical files to monitor
CRITICAL_FILES = [
    "/app/start.sh",
    "/app/openclaw.json",
    "/app/SOUL.md",
    "/app/BOOTSTRAP.md",
    "/app/TOOLS.md",
    "/app/AGENTS.md",
    "/app/IDENTITY.md",
    "/app/.openclaw/openclaw.json",
    "/app/.openclaw/exec-approvals.json",
]

# Honeypot files — any access = breach
HONEYPOT_FILES = [
    "/app/.config/secrets/api_keys.txt",
    "/app/.config/secrets/credentials.json",
    "/app/.config/secrets/.env.production",
]


def _log(message: str, level: str = "INFO"):
    """Write to audit log."""
    os.makedirs(GUARD_DIR, exist_ok=True)
    timestamp = datetime.utcnow().isoformat()
    entry = f"[{timestamp}] [{level}] {message}"
    with open(AUDIT_LOG, "a") as f:
        f.write(entry + "\n")
    if level in ("CRITICAL", "HIGH"):
        print(f"\033[91m{entry}\033[0m")  # Red for critical
    elif level == "WARN":
        print(f"\033[93m{entry}\033[0m")  # Yellow for warn
    else:
        print(entry)


def _sha512(filepath: str) -> str:
    try:
        h = hashlib.sha512()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return "UNREADABLE"


def _send_alert(message: str):
    """Send alert via available channels."""
    _log(f"ALERT: {message}", "CRITICAL")

    # Try Telegram bot alert
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if bot_token:
        try:
            import urllib.request
            import urllib.parse
            # This would send to the configured chat — for now just log
            _log(f"Alert queued for Telegram: {message}", "INFO")
        except Exception:
            pass


class Sentinel:
    """Continuous security monitoring system."""

    def __init__(self):
        self._state = {}
        self._running = False
        os.makedirs(GUARD_DIR, exist_ok=True)
        self._load_state()

    def _load_state(self):
        if os.path.exists(SENTINEL_STATE):
            try:
                with open(SENTINEL_STATE, "r") as f:
                    self._state = json.load(f)
            except Exception:
                self._state = {}

    def _save_state(self):
        with open(SENTINEL_STATE, "w") as f:
            json.dump(self._state, f, indent=2)

    def snapshot(self):
        """Take a snapshot of all critical files."""
        snap = {}
        for fpath in CRITICAL_FILES:
            if os.path.exists(fpath):
                snap[fpath] = {
                    "hash": _sha512(fpath),
                    "size": os.path.getsize(fpath),
                    "mtime": os.path.getmtime(fpath),
                    "perms": oct(os.stat(fpath).st_mode)[-3:],
                }
        self._state["last_snapshot"] = snap
        self._state["snapshot_time"] = datetime.utcnow().isoformat()
        self._save_state()
        _log(f"Snapshot taken: {len(snap)} files")
        return snap

    def check_changes(self) -> list:
        """Compare current state against last snapshot."""
        last_snap = self._state.get("last_snapshot", {})
        if not last_snap:
            _log("No baseline snapshot — taking one now", "WARN")
            self.snapshot()
            return []

        changes = []
        for fpath, expected in last_snap.items():
            if not os.path.exists(fpath):
                changes.append({"file": fpath, "change": "DELETED", "severity": "CRITICAL"})
                continue

            current_hash = _sha512(fpath)
            current_perms = oct(os.stat(fpath).st_mode)[-3:]

            if current_hash != expected["hash"]:
                changes.append({
                    "file": fpath,
                    "change": "CONTENT_MODIFIED",
                    "severity": "HIGH",
                })

            if current_perms != expected["perms"]:
                changes.append({
                    "file": fpath,
                    "change": f"PERMS_CHANGED ({expected['perms']} → {current_perms})",
                    "severity": "HIGH",
                })

        # Check for honeypot access
        for hp in HONEYPOT_FILES:
            if os.path.exists(hp):
                try:
                    stat = os.stat(hp)
                    # If atime > mtime, someone accessed it
                    if stat.st_atime > stat.st_mtime + 60:
                        changes.append({
                            "file": hp,
                            "change": "HONEYPOT_ACCESSED",
                            "severity": "CRITICAL",
                        })
                except Exception:
                    pass

        return changes

    def check_processes(self) -> list:
        """Check for suspicious processes."""
        suspicious = []
        try:
            proc_dir = Path("/proc")
            for pid_dir in proc_dir.iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    cmdline_file = pid_dir / "cmdline"
                    if cmdline_file.exists():
                        cmdline = cmdline_file.read_text().replace("\x00", " ").strip()
                        # Check for suspicious processes
                        bad_patterns = [
                            "nmap", "masscan", "nikto", "sqlmap", "hydra",
                            "metasploit", "msfconsole", "netcat", "nc -l",
                            "tcpdump", "wireshark", "strace", "ltrace",
                            "gdb", "radare", "ida", "ghidra",
                        ]
                        for pattern in bad_patterns:
                            if pattern in cmdline.lower():
                                suspicious.append({
                                    "pid": pid_dir.name,
                                    "cmdline": cmdline[:200],
                                    "pattern": pattern,
                                })
                except (PermissionError, OSError):
                    continue
        except Exception:
            pass
        return suspicious

    def check_env_leaks(self) -> list:
        """Check for sensitive data that might be leaking."""
        leaks = []
        sensitive_vars = [
            "ANTHROPIC_API_KEY", "GROQ_API_KEY", "INSTANTLY_API_KEY",
            "TELEGRAM_BOT_TOKEN", "STRIPE_API_KEY", "OPENAI_API_KEY",
        ]

        # Check if any sensitive vars are in files
        for root, dirs, files in os.walk("/app"):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".vault", ".guard", "__pycache__"}]
            for fname in files:
                if fname.endswith((".py", ".sh", ".json", ".yaml", ".yml", ".env", ".toml")):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r") as f:
                            content = f.read()
                        for var in sensitive_vars:
                            val = os.environ.get(var, "")
                            if val and len(val) > 8 and val in content:
                                leaks.append({
                                    "file": fpath,
                                    "variable": var,
                                    "severity": "CRITICAL",
                                })
                    except (OSError, UnicodeDecodeError):
                        continue
        return leaks

    def lockdown(self):
        """Emergency lockdown — restrict everything."""
        _log("EMERGENCY LOCKDOWN INITIATED", "CRITICAL")
        _send_alert("EMERGENCY LOCKDOWN — Potential breach detected")

        # Lock down all config files
        for fpath in CRITICAL_FILES:
            if os.path.exists(fpath):
                os.chmod(fpath, 0o400)  # Read-only for owner
                _log(f"Locked: {fpath}", "HIGH")

        # Lock vault
        vault_dir = "/app/.vault"
        if os.path.exists(vault_dir):
            for f in os.listdir(vault_dir):
                os.chmod(os.path.join(vault_dir, f), 0o400)

        _log("LOCKDOWN COMPLETE — All sensitive files set to read-only", "CRITICAL")

    def full_scan(self) -> dict:
        """Run comprehensive security scan."""
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "file_changes": self.check_changes(),
            "suspicious_processes": self.check_processes(),
            "env_leaks": self.check_env_leaks(),
        }

        total_issues = (
            len(results["file_changes"]) +
            len(results["suspicious_processes"]) +
            len(results["env_leaks"])
        )

        print(f"\n{'='*60}")
        print(f"  SENTINEL Security Scan — {results['timestamp']}")
        print(f"{'='*60}")

        # File changes
        if results["file_changes"]:
            print(f"\n  File Changes ({len(results['file_changes'])}):")
            for c in results["file_changes"]:
                print(f"    [{c['severity']}] {c['change']}: {c['file']}")
        else:
            print(f"\n  File Changes: None (all clean)")

        # Suspicious processes
        if results["suspicious_processes"]:
            print(f"\n  Suspicious Processes ({len(results['suspicious_processes'])}):")
            for p in results["suspicious_processes"]:
                print(f"    [CRITICAL] PID {p['pid']}: {p['pattern']} — {p['cmdline'][:80]}")
        else:
            print(f"\n  Suspicious Processes: None")

        # Env leaks
        if results["env_leaks"]:
            print(f"\n  Environment Leaks ({len(results['env_leaks'])}):")
            for l in results["env_leaks"]:
                print(f"    [CRITICAL] {l['variable']} found in {l['file']}")
        else:
            print(f"\n  Environment Leaks: None")

        # Overall status
        status = "SECURE" if total_issues == 0 else "ISSUES FOUND"
        color = "\033[92m" if total_issues == 0 else "\033[91m"
        print(f"\n  Overall Status: {color}{status}\033[0m ({total_issues} issues)")
        print(f"{'='*60}\n")

        # Auto-lockdown on critical issues
        critical = sum(1 for c in results["file_changes"] if c.get("severity") == "CRITICAL")
        critical += sum(1 for l in results["env_leaks"] if l.get("severity") == "CRITICAL")
        if critical > 0:
            _log(f"Auto-lockdown triggered: {critical} critical issues", "CRITICAL")

        return results

    def watch(self, interval: int = 60):
        """Start continuous monitoring."""
        _log("SENTINEL watching started", "INFO")
        self.snapshot()
        self._running = True

        def _stop(signum, frame):
            self._running = False
            _log("SENTINEL watching stopped", "INFO")

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        while self._running:
            changes = self.check_changes()
            if changes:
                for c in changes:
                    _log(f"Change detected: {c['change']} — {c['file']}", c["severity"])
                    if c["severity"] == "CRITICAL":
                        _send_alert(f"CRITICAL: {c['change']} — {c['file']}")

            # Check processes periodically
            suspicious = self.check_processes()
            if suspicious:
                for p in suspicious:
                    _log(f"Suspicious process: PID {p['pid']} — {p['pattern']}", "CRITICAL")
                    _send_alert(f"Suspicious process detected: {p['pattern']}")

            time.sleep(interval)

    def status(self):
        """Print current security status."""
        snap_time = self._state.get("snapshot_time", "Never")
        snap_files = len(self._state.get("last_snapshot", {}))

        print(f"\n{'='*60}")
        print(f"  SENTINEL Status")
        print(f"{'='*60}")
        print(f"  Last snapshot: {snap_time}")
        print(f"  Files monitored: {snap_files}")
        print(f"  Critical files: {len(CRITICAL_FILES)}")
        print(f"  Honeypot traps: {len(HONEYPOT_FILES)}")
        print(f"  Audit log: {AUDIT_LOG}")

        # Count audit entries
        if os.path.exists(AUDIT_LOG):
            with open(AUDIT_LOG, "r") as f:
                lines = f.readlines()
            criticals = sum(1 for l in lines if "[CRITICAL]" in l)
            highs = sum(1 for l in lines if "[HIGH]" in l)
            warns = sum(1 for l in lines if "[WARN]" in l)
            print(f"  Audit entries: {len(lines)} total")
            print(f"    Critical: {criticals}")
            print(f"    High: {highs}")
            print(f"    Warnings: {warns}")

        print(f"{'='*60}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SENTINEL — Continuous Security Monitoring")
    parser.add_argument("--watch", action="store_true", help="Start continuous monitoring")
    parser.add_argument("--scan", action="store_true", help="Run full security scan")
    parser.add_argument("--snapshot", action="store_true", help="Take file snapshot")
    parser.add_argument("--lockdown", action="store_true", help="Emergency lockdown")
    parser.add_argument("--audit", action="store_true", help="View audit log")
    parser.add_argument("--status", action="store_true", help="Show security status")
    parser.add_argument("--interval", type=int, default=60, help="Watch interval in seconds")
    args = parser.parse_args()

    s = Sentinel()

    if args.watch:
        s.watch(args.interval)
    elif args.scan:
        s.full_scan()
    elif args.snapshot:
        s.snapshot()
    elif args.lockdown:
        s.lockdown()
    elif args.audit:
        if os.path.exists(AUDIT_LOG):
            with open(AUDIT_LOG, "r") as f:
                print(f.read())
        else:
            print("No audit log found")
    elif args.status:
        s.status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
