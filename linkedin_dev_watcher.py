"""
linkedin_dev_watcher.py
Dev-mode watcher for LinkedIn post processing.
Checks vault/linkedin/intake/ every INTERVAL seconds until stopped with Ctrl+C.
Prevents duplicate instances via a PID lock file.
Started automatically by watchers/launcher.py — do NOT start directly from VS Code tasks.
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR  = Path(__file__).resolve().parent
LOCK_FILE = BASE_DIR / "vault" / "linkedin" / "dev_watcher.pid"
PROCESSOR  = BASE_DIR / "processors" / "linkedin_processor.py"
APPROVER   = BASE_DIR / "processors" / "linkedin_approver.py"
DASHBOARD  = BASE_DIR / "scripts" / "generate_dashboard.py"
PYTHON    = sys.executable

sys.path.insert(0, str(BASE_DIR))
from watchers.watcher_config import INTERVALS   # noqa: E402
INTERVAL = INTERVALS["linkedin"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _update_dashboard() -> None:
    if not DASHBOARD.exists():
        _log("Dashboard script not found — skipping.")
        return
    try:
        r = subprocess.run([PYTHON, str(DASHBOARD)], cwd=str(BASE_DIR),
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            _log("Dashboard updated.")
        else:
            _log(f"Dashboard update failed (code {r.returncode}).")
    except Exception as e:
        _log(f"Dashboard update error: {e}")


def _write_lock() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _clear_lock() -> None:
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


def _already_running() -> bool:
    """Return True if a live watcher process is already running."""
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True
    )
    return str(pid) in result.stdout


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    if _already_running():
        _log("Already running — exiting. (delete vault/linkedin/dev_watcher.pid to force restart)")
        sys.exit(1)

    _write_lock()
    _log(f"LinkedIn dev watcher started. PID={os.getpid()} | interval={INTERVAL}s")

    if not PROCESSOR.exists():
        _log(f"WARNING: Processor not found at {PROCESSOR} — will retry each cycle.")

    _log("Press Ctrl+C to stop.\n")

    try:
        while True:
            _update_dashboard()
            if PROCESSOR.exists():
                _log("Processing LinkedIn intake...")
                result = subprocess.run([PYTHON, str(PROCESSOR)], cwd=str(BASE_DIR))
                if result.returncode == 0:
                    _log("Processor completed successfully.")
                else:
                    _log(f"Processor exited with code {result.returncode}.")
            else:
                _log("Processor not found — skipping this cycle.")

            _log("Running LinkedIn approver...")
            if APPROVER.exists():
                ap = subprocess.run([PYTHON, str(APPROVER)], cwd=str(BASE_DIR))
                if ap.returncode != 0:
                    _log(f"Approver exited with code {ap.returncode}.")
            else:
                _log("Approver not found — skipping.")

            _update_dashboard()

            _log(f"Sleeping {INTERVAL}s ({INTERVAL // 60}m {INTERVAL % 60}s)...\n")
            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        _log("Stopped by user (Ctrl+C).")
    finally:
        _clear_lock()
        _log("Lock file removed. Watcher exited cleanly.")


if __name__ == "__main__":
    run()
