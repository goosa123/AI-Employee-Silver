"""
processors/linkedin_approver.py
Scans vault/Pending_Approval/ for LinkedIn artifacts (source == "linkedin")
with status == "approved", then moves them to vault/Done/linkedin/.

No auto-posting. Human approval required before this runs any action.
"""

import sys
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.plan_writer import update_plan
from integrations.linkedin.poster import post_to_linkedin

log = logging.getLogger(__name__)

BASE_DIR         = Path(__file__).resolve().parent.parent
PENDING_APPROVAL = BASE_DIR / "vault" / "Pending_Approval"
DONE_LINKEDIN    = BASE_DIR / "vault" / "Done" / "linkedin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(text: str, maxlen: int = 40) -> str:
    import re
    text = re.sub(r"[^\w\s-]", "", str(text)).strip()
    return re.sub(r"\s+", "_", text)[:maxlen].strip("_").lower()


def _done_filename(data: dict) -> str:
    dt    = datetime.now().strftime("%Y-%m-%d_%H-%M")
    topic = _clean(data.get("topic", "no_topic"), 40)
    return f"{dt}_linkedin_{topic}.json"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_approved() -> list[str]:
    """
    Find all approved LinkedIn artifacts in Pending_Approval/,
    mark them done, and move to vault/Done/linkedin/.

    Returns list of moved artifact filenames.
    """
    if not PENDING_APPROVAL.exists():
        return []

    try:
        candidates = [
            p for p in PENDING_APPROVAL.glob("linkedin_*.json")
            if _is_approved_linkedin(p)
        ]
    except Exception as e:
        log.error(f"SCAN_ERROR | reason={e}")
        return []

    if not candidates:
        log.info("No approved LinkedIn artifacts to process.")
        return []

    DONE_LINKEDIN.mkdir(parents=True, exist_ok=True)
    moved = []

    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error(f"READ_ERROR | file={path.name} | reason={e}")
            continue

        # Re-check after re-read (concurrent run guard)
        if data.get("status") != "approved" or data.get("source") != "linkedin":
            continue

        # Scheduled posting: skip if scheduled_at is in the future
        scheduled_at = data.get("scheduled_at", "")
        if scheduled_at:
            try:
                sched_dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                now_utc  = datetime.now(timezone.utc)
                if sched_dt > now_utc:
                    remaining = sched_dt - now_utc
                    hours, rem = divmod(int(remaining.total_seconds()), 3600)
                    mins = rem // 60
                    log.info(f"SCHEDULED_WAIT | file={path.name} | posts_at={scheduled_at} | in={hours}h {mins}m")
                    continue
            except Exception as e:
                log.warning(f"SCHEDULE_PARSE_ERROR | file={path.name} | scheduled_at={scheduled_at!r} | reason={e} | posting_now")

        # Post to LinkedIn
        post_text = data.get("post", "")
        if not post_text:
            log.error(f"EMPTY_POST | file={path.name} | skipping")
            continue

        result = post_to_linkedin(post_text)
        if not result["success"]:
            log.error(f"POST_FAILED | file={path.name} | reason={result['error']}")
            continue

        data["status"]       = "done"
        data["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["linkedin_post_id"] = result["post_id"]

        done_name = _done_filename(data)
        done_path = DONE_LINKEDIN / done_name

        try:
            done_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            path.unlink()
            # Update plan using source_file stem as task_id
            source_stem = Path(data.get("source_file", "")).stem
            if source_stem:
                update_plan(source_stem, "Done", "approved")
            log.info(f"DONE | file={path.name} | moved_to={done_name} | post_id={result['post_id']}")
            print(f"  >>> POSTED: {path.name} -> LinkedIn (post_id={result['post_id']}) -> Done/linkedin/{done_name}")
            moved.append(done_name)
        except Exception as e:
            log.error(f"MOVE_ERROR | file={path.name} | reason={e}")

    return moved


def _is_approved_linkedin(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("source") == "linkedin" and data.get("status") == "approved"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [LINKEDIN_APPROVER] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("LinkedIn approver started.")
    moved = process_approved()
    log.info(f"Done. Moved {len(moved)} artifact(s) to Done/linkedin/.")


if __name__ == "__main__":
    main()
