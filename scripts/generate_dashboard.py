"""
scripts/generate_dashboard.py
Generates vault/Dashboard/dashboard.md — a live snapshot of the AI Employee Silver system.
Run standalone or called from watchers each cycle.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent.parent
VAULT      = BASE_DIR / "vault"
DASHBOARD  = VAULT / "Dashboard" / "dashboard.md"
TOKEN_FILE = BASE_DIR / "credentials" / "linkedin_token.json"

sys.path.insert(0, str(BASE_DIR))

PENDING_DIR  = VAULT / "Pending_Approval"
GMAIL_DONE   = VAULT / "Done" / "gmail"
LI_DONE      = VAULT / "Done" / "linkedin"
WATCHER_LOG  = VAULT / "Logs" / "watcher.log"
GMAIL_PID    = VAULT / "gmail" / "dev_watcher.pid"
LI_PID       = VAULT / "linkedin" / "dev_watcher.pid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pid_alive(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        import subprocess
        pid = pid_file.read_text(encoding="utf-8").strip()
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True
        )
        return pid in r.stdout
    except Exception:
        return False


def _pending_counts() -> dict:
    counts = {"gmail": 0, "linkedin": 0, "total": 0}
    if not PENDING_DIR.exists():
        return counts
    for p in PENDING_DIR.glob("*.json"):
        d = _read_json_safe(p)
        src = d.get("source", "unknown")
        if src == "gmail":
            counts["gmail"] += 1
        elif src == "linkedin":
            counts["linkedin"] += 1
        counts["total"] += 1
    return counts


def _gmail_done_counts() -> dict:
    counts = {"sent": 0, "skipped": 0, "total": 0}
    if not GMAIL_DONE.exists():
        return counts
    for p in GMAIL_DONE.glob("*.json"):
        d = _read_json_safe(p)
        status = d.get("status", "")
        if status == "sent":
            counts["sent"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        counts["total"] += 1
    return counts


def _linkedin_done_count() -> int:
    if not LI_DONE.exists():
        return 0
    return len(list(LI_DONE.glob("*.json")))


def _latest_log_lines(n: int = 5) -> list[str]:
    if not WATCHER_LOG.exists():
        return ["Log file not found."]
    try:
        lines = WATCHER_LOG.read_text(encoding="utf-8").splitlines()
        return [l for l in lines if l.strip()][-n:]
    except Exception:
        return ["Could not read log."]


def _watcher_status() -> dict:
    return {
        "main":     _pid_alive(BASE_DIR / "watchers" / "watcher.lock"),
        "gmail":    _pid_alive(GMAIL_PID),
        "linkedin": _pid_alive(LI_PID),
    }


def _icon(alive: bool) -> str:
    return "RUNNING" if alive else "STOPPED"


def _linkedin_token_info() -> dict:
    """Return days remaining and expiry date for LinkedIn token."""
    if not TOKEN_FILE.exists():
        return {"status": "NO TOKEN", "days_left": None, "expires": "—"}
    try:
        data       = _read_json_safe(TOKEN_FILE)
        saved_at   = data.get("saved_at")
        expires_in = int(data.get("expires_in", 0))
        if not saved_at or not expires_in:
            return {"status": "UNKNOWN", "days_left": None, "expires": "—"}

        saved_dt  = datetime.fromisoformat(saved_at)
        now       = datetime.now(timezone.utc)
        elapsed   = (now - saved_dt).total_seconds()
        remaining = expires_in - elapsed
        days_left = int(remaining / 86400)

        expiry_dt = saved_dt.timestamp() + expires_in
        expiry_str = datetime.fromtimestamp(expiry_dt).strftime("%Y-%m-%d")

        if days_left <= 0:
            status = "EXPIRED — run linkedin_auth.py"
        elif days_left <= 7:
            status = f"EXPIRING SOON ({days_left}d)"
        else:
            status = f"OK ({days_left} days left)"

        return {"status": status, "days_left": days_left, "expires": expiry_str}
    except Exception:
        return {"status": "ERROR", "days_left": None, "expires": "—"}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate():
    now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pending  = _pending_counts()
    gmail    = _gmail_done_counts()
    li_done  = _linkedin_done_count()
    watchers = _watcher_status()
    log_tail = _latest_log_lines(5)
    token    = _linkedin_token_info()

    lines = [
        "# AI Employee Silver — Dashboard",
        f"> Last updated: {now}",
        "",
        "---",
        "",
        "## Pending Approvals",
        "",
        "| Source   | Count |",
        "|----------|-------|",
        f"| Gmail    | {pending['gmail']} |",
        f"| LinkedIn | {pending['linkedin']} |",
        f"| **Total**| **{pending['total']}** |",
        "",
        "---",
        "",
        "## Gmail — Done",
        "",
        "| Status  | Count |",
        "|---------|-------|",
        f"| Sent    | {gmail['sent']} |",
        f"| Skipped | {gmail['skipped']} |",
        f"| Total   | {gmail['total']} |",
        "",
        "---",
        "",
        "## LinkedIn — Done",
        "",
        "| Status | Count |",
        "|--------|-------|",
        f"| Posted | {li_done} |",
        "",
        "---",
        "",
        "## Watcher Health",
        "",
        "| Watcher  | Status |",
        "|----------|--------|",
        f"| Main     | {_icon(watchers['main'])} |",
        f"| Gmail    | {_icon(watchers['gmail'])} |",
        f"| LinkedIn | {_icon(watchers['linkedin'])} |",
        "",
        "---",
        "",
        "## LinkedIn Token",
        "",
        "| Field        | Value |",
        "|--------------|-------|",
        f"| Status       | {token['status']} |",
        f"| Expires On   | {token['expires']} |",
        "",
        "---",
        "",
        "## Latest Watcher Log",
        "",
        "```",
    ] + log_tail + [
        "```",
        "",
    ]

    DASHBOARD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[dashboard] Updated: {DASHBOARD}")

    # Desktop notifications
    try:
        from utils.notifier import run_checks
        run_checks(pending_total=pending["total"])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    generate()
