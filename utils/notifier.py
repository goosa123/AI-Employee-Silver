"""
utils/notifier.py
Windows desktop notifications for AI Employee Silver.
Called from generate_dashboard.py each cycle.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).resolve().parent.parent
STATE_FILE  = BASE_DIR / "vault" / "Dashboard" / "notifier_state.json"
TOKEN_FILE  = BASE_DIR / "credentials" / "linkedin_token.json"

# Notify when token expires within this many days
TOKEN_WARN_DAYS = 7


# ---------------------------------------------------------------------------
# Toast helper
# ---------------------------------------------------------------------------

def _toast(title: str, message: str, duration: str = "short") -> None:
    try:
        from winotify import Notification, audio
        n = Notification(
            app_id="AI Employee Silver",
            title=title,
            msg=message,
            duration=duration,
        )
        n.set_audio(audio.Default, loop=False)
        n.show()
    except Exception as e:
        log.warning(f"NOTIFICATION_FAILED | reason={e}")


# ---------------------------------------------------------------------------
# State — track what we've already notified about
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"last_pending_total": 0, "token_warned": False}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"STATE_SAVE_FAILED | reason={e}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_pending(state: dict, pending_total: int) -> dict:
    """Notify if new items arrived in Pending_Approval."""
    last = state.get("last_pending_total", 0)

    if pending_total > last:
        new_count = pending_total - last
        _toast(
            title="AI Employee — Approval Needed",
            msg=f"{new_count} new item(s) waiting in Pending_Approval.\nOpen vault to review.",
            duration="long",
        )
        log.info(f"NOTIFY | pending_approval | new={new_count} | total={pending_total}")

    state["last_pending_total"] = pending_total
    return state


def _check_token(state: dict) -> dict:
    """Notify if LinkedIn token is expiring soon."""
    if not TOKEN_FILE.exists():
        return state

    try:
        data       = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        saved_at   = data.get("saved_at")
        expires_in = int(data.get("expires_in", 0))

        if not saved_at or not expires_in:
            return state

        saved_dt   = datetime.fromisoformat(saved_at)
        now        = datetime.now(timezone.utc)
        elapsed    = (now - saved_dt).total_seconds()
        remaining  = expires_in - elapsed
        days_left  = int(remaining / 86400)

        if days_left <= TOKEN_WARN_DAYS and not state.get("token_warned"):
            _toast(
                title="AI Employee — LinkedIn Token Expiring",
                msg=f"LinkedIn token expires in {days_left} day(s).\nRun: python scripts/linkedin_auth.py",
                duration="long",
            )
            log.info(f"NOTIFY | linkedin_token_expiring | days_left={days_left}")
            state["token_warned"] = True

        # Reset warning flag if token was refreshed
        if days_left > TOKEN_WARN_DAYS:
            state["token_warned"] = False

    except Exception as e:
        log.warning(f"TOKEN_CHECK_FAILED | reason={e}")

    return state


# ---------------------------------------------------------------------------
# Main entry point — call this every dashboard cycle
# ---------------------------------------------------------------------------

def run_checks(pending_total: int) -> None:
    state = _load_state()
    state = _check_pending(state, pending_total)
    state = _check_token(state)
    _save_state(state)
