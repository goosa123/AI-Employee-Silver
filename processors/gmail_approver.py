"""
processors/gmail_approver.py
Scans vault/Done/gmail/ for approved email drafts, sends the reply,
archives the original, and marks the artifact as sent.

Safety guards:
- Re-checks status after re-read (concurrent run protection)
- Persistent sent_ids registry prevents double-send if artifact write fails
- Artifact write failure after send is logged clearly without masking the send
"""

import sys
import re
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.gmail.auth import get_gmail_service
from integrations.gmail.sender import send_reply, archive_message
from utils.plan_writer import update_plan

log = logging.getLogger(__name__)

BASE_DIR         = Path(__file__).resolve().parent.parent
PENDING_APPROVAL = BASE_DIR / "vault" / "Pending_Approval"
DONE_GMAIL       = BASE_DIR / "vault" / "Done" / "gmail"
SENT_IDS_FILE    = BASE_DIR / "vault" / "gmail" / "sent_ids.txt"


# ---------------------------------------------------------------------------
# Sent IDs registry  (idempotency guard)
# ---------------------------------------------------------------------------

def _load_sent_ids() -> set[str]:
    if not SENT_IDS_FILE.exists():
        return set()
    return set(SENT_IDS_FILE.read_text(encoding="utf-8").splitlines())


def _register_sent_id(msg_id: str) -> None:
    """Append message_id to sent registry immediately after a successful send."""
    SENT_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SENT_IDS_FILE.open("a", encoding="utf-8") as f:
        f.write(msg_id + "\n")


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

def process_approved() -> list[str]:
    """
    Find all approved gmail artifacts in Done/gmail/, send the draft reply,
    archive the original, and update status to 'sent'.

    Returns list of sent message IDs.
    """
    # Scan both Pending_Approval and Done/gmail for approved artifacts
    candidates = []
    for scan_dir in (PENDING_APPROVAL, DONE_GMAIL):
        if not scan_dir.exists():
            continue
        try:
            for p in scan_dir.glob("gmail_*.json"):
                try:
                    if json.loads(p.read_text(encoding="utf-8")).get("status") == "approved":
                        candidates.append(p)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"SCAN_ERROR | dir={scan_dir} | reason={e}")

    if not candidates:
        log.info("No approved Gmail drafts to send.")
        return []

    sent_ids_registry = _load_sent_ids()

    try:
        service = get_gmail_service()
    except Exception as e:
        log.error(f"GMAIL_AUTH_FAILED | reason={e}")
        return []

    sent_ids = []

    for path in candidates:
        # --- Re-read and re-check status (concurrent run guard) ---
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error(f"READ_ERROR | file={path.name} | reason={e}")
            continue

        if data.get("status") != "approved":
            log.info(f"SKIP_ALREADY_PROCESSED | file={path.name} | status={data.get('status')}")
            continue

        message_id = data.get("message_id", "")
        thread_id  = data.get("thread_id", "")
        to         = data.get("from", "")
        subject    = data.get("subject", "")
        draft      = data.get("draft")

        # --- Idempotency: skip if already sent in a previous run ---
        if message_id and message_id in sent_ids_registry:
            log.warning(f"SKIP_DUPLICATE | file={path.name} | message_id={message_id} | already_in_registry=true")
            data["status"]  = "sent"
            data["sent_at"] = "recovered_from_registry"
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            continue

        if not draft:
            log.warning(f"SKIP_NO_DRAFT | file={path.name}")
            data["status"] = "skipped"
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                log.error(f"WRITE_ERROR | file={path.name} | reason={e}")
            continue

        # --- Send ---
        try:
            sent_id = send_reply(service, to=to, subject=subject, body=draft, thread_id=thread_id)
        except Exception as e:
            log.error(f"SEND_FAILED | file={path.name} | message_id={message_id} | reason={e} | status=not_sent")
            continue

        # --- Register immediately after send (before anything else) ---
        try:
            _register_sent_id(message_id)
            sent_ids_registry.add(message_id)
        except Exception as e:
            log.error(f"REGISTRY_WRITE_FAILED | file={path.name} | sent_id={sent_id} | reason={e} | WARNING=duplicate_send_possible_on_next_run")

        # --- Archive original ---
        try:
            archive_message(service, message_id)
        except Exception as e:
            log.warning(f"ARCHIVE_FAILED | file={path.name} | reason={e} | reply_was_sent=true")

        # --- Move artifact to Done/gmail and mark sent ---
        data["status"]  = "sent"
        data["sent_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["sent_id"] = sent_id
        DONE_GMAIL.mkdir(parents=True, exist_ok=True)

        def _clean(text, maxlen=30):
            text = re.sub(r'[^\w\s-]', '', str(text)).strip()
            return re.sub(r'\s+', '_', text)[:maxlen].strip('_').lower()

        def _sender_name(from_str, maxlen=15):
            m = re.match(r'^([^<]+)', from_str)
            return _clean(m.group(1).strip() if m else from_str, maxlen)

        dt_str   = datetime.now().strftime("%Y-%m-%d_%H-%M")
        fname    = f"{dt_str}_{_sender_name(to)}_{_clean(subject, 35)}.json"
        done_path = DONE_GMAIL / fname
        try:
            done_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if path.parent != DONE_GMAIL:
                path.unlink(missing_ok=True)
        except Exception as e:
            log.error(
                f"ARTIFACT_WRITE_FAILED | file={path.name} | sent_id={sent_id} | reason={e} "
                f"| reply_was_sent=true | idempotency=protected_by_registry"
            )

        update_plan(message_id, "Sent", "approved")
        update_plan(message_id, "Done")
        log.info(f"DONE | file={path.name} | sent_id={sent_id} | to={to}")
        print(f"  >>> SENT: {path.name} -> {to}")
        sent_ids.append(sent_id)

    return sent_ids


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [GMAIL_APPROVER] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("Gmail approver started.")
    sent = process_approved()
    log.info(f"Done. Sent {len(sent)} reply(s).")


if __name__ == "__main__":
    main()
