import os
import sys
import time
import subprocess

# ---------------------------------------------------------------------------
# Paths — all derived from this file's location, never hardcoded elsewhere
# ---------------------------------------------------------------------------
BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHERS_DIR    = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE         = os.path.join(WATCHERS_DIR, "watcher.lock")
LAUNCHER_LOCK_FILE = os.path.join(WATCHERS_DIR, "launcher.lock")

WATCHER_SCRIPT  = os.path.join(WATCHERS_DIR, "main_watcher.py")
GMAIL_SCRIPT    = os.path.join(BASE_DIR, "gmail_dev_watcher.py")
LINKEDIN_SCRIPT = os.path.join(BASE_DIR, "linkedin_dev_watcher.py")

LINKEDIN_DELAY  = 120   # seconds to wait after Gmail before starting LinkedIn

TASKKILL = r"C:\Windows\System32\taskkill.exe"
PYTHON   = sys.executable   # single consistent Python path — never "python"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg):
    print(f"[launcher] {msg}", flush=True)


def _launcher_already_running():
    """Return True if another launcher process is already running."""
    if not os.path.exists(LAUNCHER_LOCK_FILE):
        return False
    try:
        with open(LAUNCHER_LOCK_FILE, "r") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        return False
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True
    )
    return str(pid) in result.stdout


def _write_launcher_lock():
    with open(LAUNCHER_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def _clear_launcher_lock():
    if os.path.exists(LAUNCHER_LOCK_FILE):
        os.remove(LAUNCHER_LOCK_FILE)


def _running_pids(script_name):
    """Return PIDs of python/pythonw processes running the given script filename."""
    try:
        r = subprocess.run(
            'wmic process where "name=\'python.exe\' or name=\'pythonw.exe\'"'
            ' get ProcessId,CommandLine',
            shell=True, capture_output=True, text=True, timeout=10
        )
        pids = []
        for line in r.stdout.split("\n"):
            if script_name in line:
                parts = line.strip().rsplit(None, 1)
                if parts and parts[-1].isdigit():
                    pids.append(int(parts[-1]))
        return pids
    except Exception:
        return []


def _running_watcher_pids():
    return _running_pids(os.path.basename(WATCHER_SCRIPT))

def _running_gmail_pids():
    return _running_pids(os.path.basename(GMAIL_SCRIPT))

def _running_linkedin_pids():
    return _running_pids(os.path.basename(LINKEDIN_SCRIPT))


def write_lock(pid):
    with open(LOCK_FILE, "w") as f:
        f.write(str(pid))


def remove_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


# ---------------------------------------------------------------------------
# kill_all — used for manual cleanup only
# ---------------------------------------------------------------------------

def kill_all():
    """Kill every running watcher instance and remove the lock file."""
    killed = 0
    for pids, label in (
        (_running_watcher_pids(),  "main_watcher"),
        (_running_gmail_pids(),    "gmail_watcher"),
        (_running_linkedin_pids(), "linkedin_watcher"),
    ):
        if not pids:
            _log(f"No running {label} processes found.")
        for pid in pids:
            r = subprocess.run(
                [TASKKILL, "/PID", str(pid), "/F"],
                capture_output=True, text=True
            )
            msg = (r.stdout + r.stderr).strip()
            _log(f"Kill {label} PID {pid}: {msg}")
            killed += 1
    remove_lock()
    return killed


# ---------------------------------------------------------------------------
# main — single entry point, sequential startup
# ---------------------------------------------------------------------------

def main():
    if _launcher_already_running():
        _log("Launcher already running — exiting. (delete watchers/launcher.lock to force restart)")
        return

    _write_launcher_lock()
    try:
        _run()
    finally:
        _clear_launcher_lock()


def _run():
    _log("Launcher started.")

    # ── 1. Main watcher ──────────────────────────────────────────────────────
    running = _running_watcher_pids()
    if running:
        _log(f"Main watcher already running (PID(s): {running}).")
        write_lock(running[0])
    else:
        _log("Starting main watcher...")
        remove_lock()
        try:
            proc = subprocess.Popen(
                [PYTHON, WATCHER_SCRIPT],
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
            )
            write_lock(proc.pid)
            _log(f"Main watcher started (PID {proc.pid}).")
        except Exception as e:
            _log(f"ERROR: Failed to start main watcher: {e}")

    # ── 2. Gmail watcher ─────────────────────────────────────────────────────
    gmail_running = _running_gmail_pids()
    gmail_fresh   = False

    if gmail_running:
        _log(f"Gmail watcher already running (PID(s): {gmail_running}).")
    else:
        _log("Starting Gmail watcher...")
        try:
            gmail_proc = subprocess.Popen(
                [PYTHON, GMAIL_SCRIPT],
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
            )
            _log(f"Gmail watcher started (PID {gmail_proc.pid}).")
            gmail_fresh = True
        except Exception as e:
            _log(f"ERROR: Failed to start Gmail watcher: {e}")
            _log("LinkedIn watcher will NOT start because Gmail watcher failed.")
            return

    # ── 3. LinkedIn watcher ──────────────────────────────────────────────────
    linkedin_running = _running_linkedin_pids()
    if linkedin_running:
        _log(f"LinkedIn watcher already running (PID(s): {linkedin_running}).")
        return

    if gmail_fresh:
        _log(f"Waiting {LINKEDIN_DELAY}s before starting LinkedIn watcher...")
        time.sleep(LINKEDIN_DELAY)

    if not os.path.exists(LINKEDIN_SCRIPT):
        _log(f"ERROR: LinkedIn watcher script not found at {LINKEDIN_SCRIPT}")
        return

    _log("Starting LinkedIn watcher...")
    try:
        li_proc = subprocess.Popen(
            [PYTHON, LINKEDIN_SCRIPT],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
        _log(f"LinkedIn watcher started (PID {li_proc.pid}).")
    except Exception as e:
        _log(f"ERROR: Failed to start LinkedIn watcher: {e}")


if __name__ == "__main__":
    main()
