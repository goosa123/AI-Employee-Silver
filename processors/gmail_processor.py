"""
processors/gmail_processor.py
Orchestrates the Gmail intake pipeline:
  fetch -> dedup -> classify -> draft (if reply_needed) -> save artifact -> mark processed.
No sending. No Done move yet.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
import re
import subprocess
from datetime import datetime, timezone

from integrations.gmail.reader import fetch_unread_inbox
from integrations.gmail.sender import send_reply, archive_message
from skills.email_classifier.skill import classify_email
from skills.email_drafter.skill import draft_email_reply
from utils.plan_writer import create_plan, update_plan

log = logging.getLogger(__name__)

BASE_DIR         = Path(__file__).resolve().parent.parent
PENDING_APPROVAL = BASE_DIR / "vault" / "Pending_Approval"
DONE_GMAIL_DIR   = BASE_DIR / "vault" / "Done" / "gmail"
PROCESSED_IDS    = BASE_DIR / "vault" / "gmail" / "processed_ids.txt"

NEEDS_DRAFT    = {"reply_needed", "review_needed", "auto_reply"}
NEEDS_ARTIFACT = {"reply_needed", "review_needed"}

# ---------------------------------------------------------------------------
# Sensitive keyword pre-check
# ---------------------------------------------------------------------------

_SENSITIVE_KEYWORDS = {
    "please send", "kindly send",
    "urgent", "urgently", "asap", "immediate",
    "payment", "transfer", "wire", "bank",
    "contract", "agreement", "terms", "sign",
    "important client", "key client", "vip",
}

_AUTO_REPLY_KEYWORDS = {
    "write", "likho", "likh", "banao", "bana",
    "story", "song", "poem", "letter", "application",
    "translate", "summarize", "explain",
    "sales pitch", "cover letter", "essay", "caption",
}


def _is_sensitive(email: dict) -> bool:
    """Return True if subject or snippet contains any sensitive keyword."""
    text = " ".join([
        email.get("subject", ""),
        email.get("snippet", ""),
    ]).lower()
    return any(kw in text for kw in _SENSITIVE_KEYWORDS)


# ---------------------------------------------------------------------------
# Processed ID registry
# ---------------------------------------------------------------------------

def _load_processed_ids() -> set[str]:
    """Load all previously processed message IDs from disk. Returns empty set if file missing."""
    if not PROCESSED_IDS.exists():
        return set()
    return set(PROCESSED_IDS.read_text(encoding="utf-8").splitlines())


def _mark_processed(msg_id: str) -> None:
    """Append a message ID to the processed IDs file, creating it if needed."""
    PROCESSED_IDS.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_IDS.open("a", encoding="utf-8") as f:
        f.write(msg_id + "\n")


# ---------------------------------------------------------------------------
# Artifact writer
# ---------------------------------------------------------------------------

def _save_artifact(email: dict, category: str, reason: str, draft: str | None) -> Path:
    """Save a JSON approval artifact to vault/Pending_Approval/."""
    PENDING_APPROVAL.mkdir(parents=True, exist_ok=True)

    artifact = {
        "source":                "gmail",
        "message_id":            email.get("message_id", ""),
        "thread_id":             email.get("thread_id", ""),
        "from":                  email.get("from", ""),
        "subject":               email.get("subject", ""),
        "date":                  email.get("date", ""),
        "snippet":               email.get("snippet", ""),
        "category":              category,
        "classification_reason": reason,
        "draft":                 draft,
        "status":                "pending_approval",
        "created_at":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    filename = f"gmail_{email.get('message_id', 'unknown')}.json"
    path     = PENDING_APPROVAL / filename
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Skipped email writer
# ---------------------------------------------------------------------------

def _save_skipped(email: dict, reason: str) -> Path:
    """Write a lightweight skipped record to vault/Done/gmail/."""
    DONE_GMAIL_DIR.mkdir(parents=True, exist_ok=True)

    subject    = email.get("subject", "no_subject")
    short_subj = re.sub(r"[^\w\s-]", "", subject).strip().replace(" ", "_")[:35]
    dt_str     = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename   = f"{dt_str}_{short_subj}_skipped.txt"
    path        = DONE_GMAIL_DIR / filename

    content = (
        f"Subject        : {email.get('subject', '')}\n"
        f"From           : {email.get('from', '')}\n"
        f"Classification : no_reply_needed\n"
        f"Reason         : {reason}\n"
        f"Action         : skipped\n"
    )

    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Auto-reply done writer
# ---------------------------------------------------------------------------

def _save_done(email: dict, category: str, reason: str, draft: str, sent_id: str) -> None:
    """Save a sent auto_reply record to vault/Done/gmail/."""
    DONE_GMAIL_DIR.mkdir(parents=True, exist_ok=True)
    artifact = {
        "source":                "gmail",
        "message_id":            email.get("message_id", ""),
        "thread_id":             email.get("thread_id", ""),
        "from":                  email.get("from", ""),
        "subject":               email.get("subject", ""),
        "date":                  email.get("date", ""),
        "snippet":               email.get("snippet", ""),
        "category":              category,
        "classification_reason": reason,
        "draft":                 draft,
        "status":                "sent",
        "sent_id":               sent_id,
        "sent_at":               datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    def _clean(text, maxlen=30):
        text = re.sub(r"[^\w\s-]", "", str(text)).strip()
        return re.sub(r"\s+", "_", text)[:maxlen].strip("_").lower()

    def _sender_name(from_str, maxlen=15):
        m = re.match(r"^([^<]+)", from_str)
        return _clean(m.group(1).strip() if m else from_str, maxlen)

    dt_str   = datetime.now().strftime("%Y-%m-%d_%H-%M")
    sender   = _sender_name(email.get("from", "unknown"))
    subject  = _clean(email.get("subject", "no_subject"), 35)
    filename = f"{dt_str}_{sender}_{subject}.json"
    (DONE_GMAIL_DIR / filename).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Desktop notification
# ---------------------------------------------------------------------------

def _notify(email: dict, draft: str | None) -> None:
    """Show a Windows toast notification for a new pending approval."""
    sender  = email.get("from", "Unknown")
    subject = email.get("subject", "(no subject)")
    preview = (draft or "")[:80].replace("\n", " ")
    title   = f"New Email — Approval Needed"
    body    = f"From: {sender}\n{subject}\nDraft: {preview}..."
    try:
        ps = (
            f'Add-Type -AssemblyName System.Windows.Forms;'
            f'$n = New-Object System.Windows.Forms.NotifyIcon;'
            f'$n.Icon = [System.Drawing.SystemIcons]::Information;'
            f'$n.Visible = $true;'
            f'$n.ShowBalloonTip(8000, "{title}", "{body}", [System.Windows.Forms.ToolTipIcon]::Info);'
            f'Start-Sleep -Seconds 9;'
            f'$n.Dispose()'
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info(f"NOTIFY_SENT | id={email.get('message_id', '')} | subject={subject}")
    except Exception as e:
        log.warning(f"NOTIFY_FAILED | reason={e}")


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

def process_inbox() -> list[dict]:
    """
    Fetch unread inbox emails, skip already-processed ones, classify,
    draft replies where needed, and save approval artifacts.

    Returns a list of result dicts, one per newly processed email:
    {
        "email":         { message_id, thread_id, subject, from, date, snippet },
        "category":      "reply_needed | no_reply_needed | review_needed",
        "reason":        "classifier explanation",
        "draft":         "reply text or None",
        "artifact_path": "path to saved artifact or None",
    }
    """
    try:
        emails = fetch_unread_inbox()
    except FileNotFoundError as e:
        log.error(f"GMAIL_CREDENTIALS_MISSING | {e}")
        raise
    except Exception as e:
        log.error(f"FETCH_ERROR | {e}")
        raise

    if not emails:
        log.info("No unread emails found.")
        return []

    processed_ids = _load_processed_ids()
    log.info(f"Fetched {len(emails)} unread email(s). Known processed: {len(processed_ids)}.")

    results = []

    for email in emails:
        msg_id = email.get("message_id", "unknown")

        if msg_id in processed_ids:
            log.info(f"SKIP_DUPLICATE | id={msg_id}")
            continue

        # Plan — step 1: Email received
        label = f"{email.get('from', 'Unknown').split('<')[0].strip()} — {email.get('subject', '')[:40]}"
        create_plan(msg_id, "gmail", label)

        # Pre-classification sensitive override
        if _is_sensitive(email):
            category = "review_needed"
            reason   = "sensitive keyword detected — human review required"
            log.info(f"SENSITIVE_OVERRIDE | id={msg_id} | category={category}")
        else:
            classification = classify_email(email)
            category = classification.get("category", "review_needed")
            reason   = classification.get("reason", "")
            # If classifier failed, try creative keyword fallback
            if reason == "classification failed":
                text = " ".join([
                    email.get("subject", ""),
                    email.get("snippet", ""),
                ]).lower()
                if any(kw in text for kw in _AUTO_REPLY_KEYWORDS):
                    category = "auto_reply"
                    reason   = "creative/writing request detected via keyword fallback"
                    log.info(f"AUTO_REPLY_FALLBACK | id={msg_id}")
            log.info(f"CLASSIFIED | id={msg_id} | category={category}")

        update_plan(msg_id, "Classified", category)

        draft = None
        if category in NEEDS_DRAFT:
            draft_result = draft_email_reply(email)
            draft = draft_result.get("draft")
            log.info(f"DRAFTED | id={msg_id}")
            update_plan(msg_id, "Draft generated")

        if category == "no_reply_needed":
            try:
                skipped_path = _save_skipped(email, reason)
                log.info(f"SKIPPED_SAVED | id={msg_id} | path={skipped_path.name}")
            except Exception as e:
                log.error(f"SKIPPED_ERROR | id={msg_id} | reason={e}")

        if category == "auto_reply" and draft:
            try:
                from integrations.gmail.auth import get_gmail_service
                service   = get_gmail_service()
                sent_id   = send_reply(
                    service,
                    to=email.get("from", ""),
                    subject=email.get("subject", ""),
                    body=draft,
                    thread_id=email.get("thread_id", ""),
                )
                archive_message(service, msg_id)
                _save_done(email, category, reason, draft, sent_id)
                update_plan(msg_id, "Sent", "auto_reply")
                log.info(f"AUTO_SENT | id={msg_id} | sent_id={sent_id}")
            except Exception as e:
                log.error(f"AUTO_SEND_FAILED | id={msg_id} | reason={e}")

        artifact_path = None
        if category in NEEDS_ARTIFACT:
            try:
                artifact_path = _save_artifact(email, category, reason, draft)
                log.info(f"ARTIFACT_SAVED | id={msg_id} | path={artifact_path.name}")
                update_plan(msg_id, "Pending approval")
                _notify(email, draft)
            except Exception as e:
                log.error(f"ARTIFACT_ERROR | id={msg_id} | reason={e}")

        _mark_processed(msg_id)
        processed_ids.add(msg_id)

        results.append({
            "email":         email,
            "category":      category,
            "reason":        reason,
            "draft":         draft,
            "artifact_path": str(artifact_path) if artifact_path else None,
        })

    return results


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [GMAIL_PROCESSOR] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log.info("Gmail processor started.")
    results = process_inbox()
    log.info(f"Done. Processed {len(results)} email(s).")

    for r in results:
        e = r["email"]
        print(f"\n  id            : {e.get('message_id')}")
        print(f"  from          : {e.get('from')}")
        print(f"  subject       : {e.get('subject')}")
        print(f"  category      : {r['category']}")
        print(f"  reason        : {r['reason']}")
        print(f"  artifact_path : {r['artifact_path']}")
        if r["draft"]:
            print(f"  draft         : {r['draft'][:120]}...")


if __name__ == "__main__":
    main()
