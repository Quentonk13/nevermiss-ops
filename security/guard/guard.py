"""
LAYER 3: GUARD — Runtime Protection & Integrity Verification
===============================================================
Tamper detection, code integrity verification, anti-debugging,
import hooks, and process isolation.

Usage:
    from security.guard.guard import Guard
    g = Guard()
    g.verify_integrity()     # Check all files against known hashes
    g.enable_protection()    # Enable runtime protections
    g.scan()                 # Full security scan
"""

import ctypes
import hashlib
import json
import os
import signal
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

GUARD_DIR = os.environ.get("GUARD_DIR", "/app/.guard")
HASH_DB = os.path.join(GUARD_DIR, "integrity.json")
ALERT_LOG = os.path.join(GUARD_DIR, "alerts.log")
SKILLS_DIR = "/app/skills"


def _sha512(filepath: str) -> str:
    """Compute SHA-512 hash of a file."""
    h = hashlib.sha512()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return "UNREADABLE"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _alert(message: str, severity: str = "WARN"):
    """Log a security alert."""
    os.makedirs(GUARD_DIR, exist_ok=True)
    timestamp = datetime.utcnow().isoformat()
    entry = f"[{timestamp}] [{severity}] {message}\n"
    with open(ALERT_LOG, "a") as f:
        f.write(entry)
    print(f"[GUARD:{severity}] {message}")


class IntegrityDB:
    """Manages file integrity hashes."""

    def __init__(self):
        self._db = {}
        os.makedirs(GUARD_DIR, exist_ok=True)
        if os.path.exists(HASH_DB):
            with open(HASH_DB, "r") as f:
                self._db = json.load(f)

    def baseline(self, directories: list = None):
        """Create integrity baseline of all critical files."""
        if directories is None:
            directories = [
                "/app/skills",
                "/app/security",
                "/app",
            ]

        extensions = {".py", ".sh", ".js", ".json", ".md", ".yaml", ".yml", ".toml"}
        file_count = 0

        for directory in directories:
            if not os.path.exists(directory):
                continue
            for root, dirs, files in os.walk(directory):
                # Skip hidden dirs and node_modules
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in extensions:
                        fpath = os.path.join(root, fname)
                        self._db[fpath] = {
                            "hash": _sha512(fpath),
                            "size": os.path.getsize(fpath),
                            "mtime": os.path.getmtime(fpath),
                            "baselined_at": datetime.utcnow().isoformat(),
                        }
                        file_count += 1

        with open(HASH_DB, "w") as f:
            json.dump(self._db, f, indent=2)
        os.chmod(HASH_DB, 0o600)

        print(f"[GUARD] Baselined {file_count} files across {len(directories)} directories")
        return file_count

    def verify(self) -> list:
        """Verify all files against baseline. Returns list of violations."""
        violations = []

        for fpath, expected in self._db.items():
            if not os.path.exists(fpath):
                violations.append({
                    "file": fpath,
                    "type": "DELETED",
                    "severity": "CRITICAL",
                })
                _alert(f"File DELETED: {fpath}", "CRITICAL")
                continue

            current_hash = _sha512(fpath)
            current_size = os.path.getsize(fpath)

            if current_hash != expected["hash"]:
                violations.append({
                    "file": fpath,
                    "type": "MODIFIED",
                    "severity": "HIGH",
                    "expected_hash": expected["hash"][:16] + "...",
                    "actual_hash": current_hash[:16] + "...",
                })
                _alert(f"File MODIFIED: {fpath}", "HIGH")

            if current_size != expected["size"]:
                violations.append({
                    "file": fpath,
                    "type": "SIZE_CHANGED",
                    "severity": "MEDIUM",
                    "expected_size": expected["size"],
                    "actual_size": current_size,
                })

        # Check for NEW files that weren't in baseline
        for directory in set(os.path.dirname(f) for f in self._db.keys()):
            if not os.path.exists(directory):
                continue
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
                for fname in files:
                    fpath = os.path.join(root, fname)
                    if fpath not in self._db and os.path.splitext(fname)[1] in {".py", ".sh", ".js"}:
                        violations.append({
                            "file": fpath,
                            "type": "NEW_EXECUTABLE",
                            "severity": "HIGH",
                        })
                        _alert(f"New executable file: {fpath}", "HIGH")

        return violations


class AntiDebug:
    """Anti-debugging and anti-reverse-engineering protections."""

    @staticmethod
    def check_debugger() -> bool:
        """Detect if a debugger is attached."""
        # Check /proc/self/status for TracerPid
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("TracerPid:"):
                        tracer_pid = int(line.split(":")[1].strip())
                        if tracer_pid != 0:
                            _alert(f"Debugger detected! TracerPid: {tracer_pid}", "CRITICAL")
                            return True
        except Exception:
            pass

        # Check for common debugger env vars
        debug_vars = ["PYTHONDONTWRITEBYTECODE", "PYTHONBREAKPOINT", "PYDEVD_USE_CYTHON"]
        for var in debug_vars:
            if var in os.environ and var != "PYTHONDONTWRITEBYTECODE":
                _alert(f"Debug env var detected: {var}", "WARN")

        return False

    @staticmethod
    def check_ptrace() -> bool:
        """Check if ptrace is being used (Linux)."""
        try:
            with open(f"/proc/{os.getpid()}/status", "r") as f:
                content = f.read()
                if "TracerPid:\t0" not in content:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def detect_vm() -> dict:
        """Detect if running in a VM/container (informational)."""
        indicators = {
            "docker": os.path.exists("/.dockerenv"),
            "kubernetes": "KUBERNETES_SERVICE_HOST" in os.environ,
            "railway": "RAILWAY_ENVIRONMENT" in os.environ,
            "container": os.path.exists("/run/.containerenv"),
        }
        # Check for hypervisor
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read().lower()
                indicators["vmware"] = "vmware" in cpuinfo
                indicators["virtualbox"] = "vbox" in cpuinfo
                indicators["kvm"] = "kvm" in cpuinfo
        except Exception:
            pass

        return {k: v for k, v in indicators.items() if v}


class ImportGuard:
    """Custom import hook that monitors and blocks unauthorized imports."""

    BLOCKED_MODULES = [
        "pdb",        # Debugger
        "code",       # Interactive console
        "cProfile",   # Profiler (can leak timing info)
        "trace",      # Tracing
        "bdb",        # Base debugger
    ]

    MONITORED_MODULES = [
        "subprocess",  # Shell commands
        "socket",      # Network access
        "http",        # HTTP requests
        "urllib",      # URL fetching
        "ftplib",      # FTP
        "smtplib",     # Email sending
        "ctypes",      # C interop (dangerous)
    ]

    class _Finder:
        def find_module(self, name, path=None):
            if name in ImportGuard.BLOCKED_MODULES:
                _alert(f"Blocked import: {name}", "HIGH")
                return self
            if name in ImportGuard.MONITORED_MODULES:
                _alert(f"Monitored import: {name}", "INFO")
            return None

        def load_module(self, name):
            raise ImportError(f"[GUARD] Import of '{name}' is blocked for security")

    @classmethod
    def enable(cls):
        """Enable import monitoring."""
        sys.meta_path.insert(0, cls._Finder())
        print("[GUARD] Import monitoring enabled")

    @classmethod
    def disable(cls):
        sys.meta_path = [f for f in sys.meta_path if not isinstance(f, cls._Finder)]


class ProcessGuard:
    """Process-level security measures."""

    @staticmethod
    def set_resource_limits():
        """Set process resource limits to prevent abuse."""
        try:
            import resource
            # Max 512MB memory
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            # Max 100 open files
            resource.setrlimit(resource.RLIMIT_NOFILE, (100, 100))
            # Max 50 child processes
            resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
            print("[GUARD] Resource limits set")
        except Exception as e:
            _alert(f"Could not set resource limits: {e}", "WARN")

    @staticmethod
    def set_signal_handlers():
        """Set up signal handlers to prevent crash-based attacks."""
        def _handle_signal(signum, frame):
            _alert(f"Signal received: {signum}", "WARN")

        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(sig, _handle_signal)


class Guard:
    """Main security guard — orchestrates all protections."""

    def __init__(self):
        self._integrity = IntegrityDB()
        self._anti_debug = AntiDebug()
        self._process_guard = ProcessGuard()
        os.makedirs(GUARD_DIR, exist_ok=True)

    def baseline(self, directories: list = None):
        """Create integrity baseline."""
        return self._integrity.baseline(directories)

    def verify_integrity(self) -> list:
        """Verify file integrity."""
        return self._integrity.verify()

    def enable_protection(self):
        """Enable all runtime protections."""
        print(f"\n{'='*50}")
        print(f"  GUARD — Enabling Runtime Protection")
        print(f"{'='*50}")

        # Check for debuggers
        if self._anti_debug.check_debugger():
            print("  [!] Debugger detected — operating in restricted mode")

        # Detect environment
        env = self._anti_debug.detect_vm()
        if env:
            print(f"  [i] Environment: {', '.join(env.keys())}")

        # Set resource limits
        self._process_guard.set_resource_limits()
        self._process_guard.set_signal_handlers()

        print(f"{'='*50}\n")

    def scan(self) -> dict:
        """Run a full security scan."""
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "debugger_detected": self._anti_debug.check_debugger(),
            "ptrace_detected": self._anti_debug.check_ptrace(),
            "environment": self._anti_debug.detect_vm(),
            "integrity_violations": [],
        }

        # Integrity check
        violations = self.verify_integrity()
        results["integrity_violations"] = violations

        # Print report
        print(f"\n{'='*50}")
        print(f"  GUARD Security Scan Report")
        print(f"{'='*50}")
        print(f"  Time: {results['timestamp']}")
        print(f"  Debugger: {'DETECTED' if results['debugger_detected'] else 'Clean'}")
        print(f"  Ptrace: {'DETECTED' if results['ptrace_detected'] else 'Clean'}")
        print(f"  Environment: {results['environment'] or 'Standard'}")
        print(f"  Integrity violations: {len(violations)}")
        for v in violations:
            print(f"    [{v['severity']}] {v['type']}: {v['file']}")
        print(f"{'='*50}\n")

        return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GUARD — Runtime Protection")
    parser.add_argument("--baseline", action="store_true", help="Create integrity baseline")
    parser.add_argument("--verify", action="store_true", help="Verify file integrity")
    parser.add_argument("--scan", action="store_true", help="Full security scan")
    parser.add_argument("--protect", action="store_true", help="Enable runtime protection")
    args = parser.parse_args()

    g = Guard()
    if args.baseline:
        g.baseline()
    elif args.verify:
        violations = g.verify_integrity()
        if not violations:
            print("[GUARD] All files intact")
    elif args.scan:
        g.scan()
    elif args.protect:
        g.enable_protection()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
