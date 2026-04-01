import os
import re
import sys
import time
import uuid
import shutil
import hashlib
import logging
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Make project root importable so processors/ can be resolved as a package.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from processors.task_processor import process_one  # noqa: E402
INBOX_DIR      = os.path.join(BASE_DIR, "vault", "Inbox")
DROP_DIR       = os.path.join(BASE_DIR, "vault", "Drop")
NEEDS_ACTION   = os.path.join(BASE_DIR, "vault", "Needs_Action")
ARCHIVE_DIR    = os.path.join(BASE_DIR, "vault", "Archive")
APPROVED_DIR   = os.path.join(BASE_DIR, "vault", "Approved")
REJECTED_DIR   = os.path.join(BASE_DIR, "vault", "Rejected")
SCHEDULED_DIR  = os.path.join(BASE_DIR, "vault", "Scheduled")
DONE_DIR       = os.path.join(BASE_DIR, "vault", "Done")
LOG_FILE       = os.path.join(BASE_DIR, "vault", "Logs", "watcher.log")

from watchers.watcher_config import INTERVALS  # noqa: E402
CHECK_INTERVAL  = INTERVALS["main"]   # seconds between scan cycles
STABILITY_WAIT  = CHECK_INTERVAL      # file size must be unchanged for this many seconds before intake
WATCHER_VERSION = "2.3.0-debug"   # + DEDUP_CHECK trace logging

REQUIRED_FIELDS = {
    "id":         None,   # generated per-file
    "source":     None,   # set from folder name
    "status":     "pending",
    "created_at": None,   # set from current time
    "task_type":  "general",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
for _d in (INBOX_DIR, DROP_DIR, NEEDS_ACTION, ARCHIVE_DIR,
           APPROVED_DIR, REJECTED_DIR, SCHEDULED_DIR, DONE_DIR,
           os.path.dirname(LOG_FILE)):
    os.makedirs(_d, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text):
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fields = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields, text[m.end():]


def build_frontmatter(fields):
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def ensure_frontmatter(text, source_label):
    fields, body = parse_frontmatter(text)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    defaults = {
        "id":         str(uuid.uuid4()),
        "source":     source_label,
        "status":     REQUIRED_FIELDS["status"],
        "created_at": now,
        "task_type":  REQUIRED_FIELDS["task_type"],
    }
    for key, default in defaults.items():
        if key not in fields or not fields[key]:
            fields[key] = default
    # Required fields first, extras after
    ordered = {k: fields.pop(k) for k in defaults if k in fields}
    ordered.update(fields)
    return build_frontmatter(ordered) + body


def _body_hash(raw_text):
    """MD5 of the stripped, line-ending-normalised task body (frontmatter excluded).
    Normalising CRLF → LF ensures VS Code saves on Windows always produce the
    same hash regardless of the editor's line-ending setting."""
    _, body = parse_frontmatter(raw_text)
    normalised = body.strip().replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.md5(normalised.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------
def unique_filename(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}_{counter}{ext}"
        counter += 1
    return candidate


def _write_blocked_task(needs_action_path, filename, source_label, reason):
    """
    Last-resort recovery: write a blocked placeholder into Needs_Action so
    the task is visible and not silently lost.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = (
        f"---\n"
        f"id: {uuid.uuid4()}\n"
        f"source: {source_label}\n"
        f"status: blocked\n"
        f"created_at: {now}\n"
        f"task_type: general\n"
        f"original_file: {filename}\n"
        f"block_reason: {reason}\n"
        f"---\n\n"
        f"This task was blocked during intake. See block_reason above.\n"
        f"Original file was archived. Manual review required.\n"
    )
    with open(needs_action_path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _archive_only(src_path, source_label):
    """Move a source file to Archive without touching Needs_Action.
    Used when a task is being *updated* in place rather than freshly intaken."""
    filename = os.path.basename(src_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived_name = unique_filename(ARCHIVE_DIR, f"{timestamp}_{filename}")
    try:
        shutil.move(src_path, os.path.join(ARCHIVE_DIR, archived_name))
        return archived_name
    except Exception as e:
        logging.error(
            f"ARCHIVE_ONLY_ERROR | source={source_label} | file={filename} | reason={e}"
        )
        return None


def process_file(src_path, source_label, raw=None):
    """
    Intake pipeline:
      1. Read + enrich content  (pure, no side effects)
         - raw may be supplied by caller to avoid a second disk read
      2. Move original → Archive
      3. Write working copy → Needs_Action
         - on failure: attempt to restore original from Archive back to source
         - if restore also fails: write a blocked placeholder to Needs_Action

    Returns {"archive": archived_name, "na": needs_action_name} on full success.
    Returns None if any step failed.
    """
    filename = os.path.basename(src_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived_name     = unique_filename(ARCHIVE_DIR,  f"{timestamp}_{filename}")
    needs_action_name = unique_filename(NEEDS_ACTION, f"{timestamp}_{filename}")
    archive_path      = os.path.join(ARCHIVE_DIR,  archived_name)
    needs_action_path = os.path.join(NEEDS_ACTION, needs_action_name)

    # ------------------------------------------------------------------
    # Step 1: Read and build enriched content — no side effects.
    # If this fails the source file is untouched; caller retries next cycle.
    # ------------------------------------------------------------------
    try:
        if raw is None:
            with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        enriched_text = ensure_frontmatter(raw, source_label)
    except Exception as e:
        logging.error(
            f"READ_ERROR | source={source_label} | file={filename} "
            f"| reason={e} | action=will_retry"
        )
        return None  # file still exists → caller removes from _in_flight

    # ------------------------------------------------------------------
    # Step 2: Move original → Archive.
    # If this fails the source file is still in place; caller retries next cycle.
    # ------------------------------------------------------------------
    try:
        shutil.move(src_path, archive_path)
    except Exception as e:
        logging.error(
            f"ARCHIVE_ERROR | source={source_label} | file={filename} "
            f"| reason={e} | action=will_retry"
        )
        return None  # file still exists → caller removes from _in_flight

    # ------------------------------------------------------------------
    # Step 3: Write working copy → Needs_Action.
    # Archive move already succeeded. If this fails, the task must not be lost.
    # ------------------------------------------------------------------
    try:
        with open(needs_action_path, "w", encoding="utf-8") as fh:
            fh.write(enriched_text)
    except Exception as write_err:
        logging.error(
            f"WRITE_ERROR | source={source_label} | file={filename} "
            f"| archived={archived_name} | reason={write_err}"
        )
        # Recovery attempt A: move archived file back to its source location.
        try:
            shutil.move(archive_path, src_path)
            logging.warning(
                f"RECOVERED | source={source_label} | file={filename} "
                f"| action=restored_to_source | will_retry=true"
            )
        except Exception as restore_err:
            # Recovery attempt B: original can't be restored.
            # Write a blocked placeholder so the task is visible in Needs_Action.
            logging.error(
                f"RESTORE_FAILED | source={source_label} | file={filename} "
                f"| archived={archived_name} | reason={restore_err}"
            )
            try:
                _write_blocked_task(needs_action_path, filename, source_label,
                                    str(write_err))
                logging.warning(
                    f"BLOCKED_TASK_CREATED | source={source_label} | file={filename} "
                    f"| needs_action={needs_action_name} | manual_review_required=true"
                )
            except Exception as blocked_err:
                logging.critical(
                    f"UNRECOVERABLE | source={source_label} | file={filename} "
                    f"| archived={archived_name} | reason={blocked_err} "
                    f"| MANUAL_INTERVENTION_REQUIRED"
                )
        return None

    logging.info(
        f"OK | source={source_label} | file={filename} "
        f"| archived={archived_name} | needs_action={needs_action_name}"
    )
    print(f"  >>> [{source_label}] {filename} -> Needs_Action/{needs_action_name}")
    return {"archive": archived_name, "na": needs_action_name}


# ---------------------------------------------------------------------------
# Approval / rejection handlers
# ---------------------------------------------------------------------------

def extract_original_task(body):
    """
    Pull the text that sits between '## Original Task' and '## Result'
    from a pending_approval file body.  Falls back to the full body if
    the expected markers are not found.
    """
    if "## Original Task" in body:
        after = body.split("## Original Task", 1)[1].lstrip("\n")
        if "## Result" in after:
            return after.split("## Result", 1)[0].strip()
        return after.strip()
    return body.strip()


def handle_approved(src_path):
    """
    Move an approved file from Approved/ to Done/ with status: done.
    The file content (original task + result) is preserved unchanged;
    only the frontmatter status fields are updated.
    """
    filename = os.path.basename(src_path)

    try:
        with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except Exception as e:
        logging.error(f"APPROVED_READ_ERROR | file={filename} | reason={e}")
        return False

    fields, body = parse_frontmatter(raw)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    fields["status"]       = "done"
    fields["completed_at"] = now
    fields.pop("reviewed_at", None)   # remove blank placeholder

    done_content = build_frontmatter(fields) + body

    # Strip ALL leading timestamp prefixes (YYYYMMDD_HHMMSS_) before adding a fresh one.
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    base      = re.sub(r"^(\d{8}_\d{6}_)+", "", os.path.splitext(filename)[0])
    base      = base.replace("_pending", "")
    done_name = unique_filename(DONE_DIR, f"{ts}_{base}_done.md")
    done_path = os.path.join(DONE_DIR, done_name)

    try:
        with open(done_path, "w", encoding="utf-8") as fh:
            fh.write(done_content)
    except Exception as e:
        logging.error(
            f"APPROVED_WRITE_ERROR | file={filename} | reason={e} "
            f"| action=left_in_Approved"
        )
        return False

    try:
        os.remove(src_path)
    except Exception as e:
        logging.error(
            f"APPROVED_CLEANUP_ERROR | file={filename} | done={done_name} "
            f"| reason={e} | note=result written, manual cleanup needed"
        )
        return True  # Done file is safe; log but do not block

    logging.info(f"APPROVED | file={filename} | done={done_name}")
    print(f"  >>> APPROVED: {filename} -> Done/{done_name}")
    return True


def handle_rejected(src_path):
    """
    Mark a rejected task as final — update its status to 'rejected' and
    leave it in Rejected/. Do NOT re-queue to Needs_Action.
    New tasks must be submitted via Drop if a retry is needed.
    """
    filename = os.path.basename(src_path)

    try:
        with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except Exception as e:
        logging.error(f"REJECTED_READ_ERROR | file={filename} | reason={e}")
        return False

    fields, body = parse_frontmatter(raw)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    fields["status"]      = "rejected"
    fields["rejected_at"] = now

    try:
        with open(src_path, "w", encoding="utf-8") as fh:
            fh.write(build_frontmatter(fields) + body)
    except Exception as e:
        logging.error(f"REJECTED_WRITE_ERROR | file={filename} | reason={e}")
        return False

    logging.info(f"REJECTED | file={filename} | action=marked_final_in_Rejected")
    print(f"  >>> REJECTED: {filename} (final, stays in Rejected/)")
    return True


def _handle_json_approval(src_path, status):
    """
    For Gmail/LinkedIn JSON artifacts moved to Approved/ or Rejected/:
    update their status field and move back to Pending_Approval/ so the
    respective approver (gmail_approver / linkedin_approver) picks them up.
    """
    import json as _json
    filename = os.path.basename(src_path)
    try:
        with open(src_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:
        logging.error(f"JSON_APPROVAL_READ_ERROR | file={filename} | reason={e}")
        return False

    data["status"] = status
    dst_path = os.path.join(NEEDS_ACTION.replace("Needs_Action", "Pending_Approval"), filename)

    # Ensure Pending_Approval exists
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    try:
        with open(dst_path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        os.remove(src_path)
        logging.info(f"JSON_APPROVAL | file={filename} | status={status} | routed_to=Pending_Approval")
        print(f"  >>> JSON {status.upper()}: {filename} -> Pending_Approval/")
        return True
    except Exception as e:
        logging.error(f"JSON_APPROVAL_WRITE_ERROR | file={filename} | reason={e}")
        return False


def scan_approval_folders():
    """Scan Approved/ and Rejected/ and act on any decisions found."""
    for folder, handler, label, json_status in (
        (APPROVED_DIR, handle_approved, "approved", "approved"),
        (REJECTED_DIR, handle_rejected, "rejected", "rejected"),
    ):
        try:
            entries = [e for e in os.scandir(folder) if e.is_file()]
        except FileNotFoundError:
            os.makedirs(folder, exist_ok=True)
            continue
        except Exception as e:
            logging.error(f"SCAN_ERROR | source={label} | reason={e}")
            continue

        new_files = [e for e in entries if e.path not in _in_flight]
        if not new_files:
            continue

        logging.info(f"{label}: {len(new_files)} decision(s) found.")

        for entry in new_files:
            _in_flight.add(entry.path)

            if entry.name.endswith(".json"):
                # Gmail / LinkedIn artifact — update status, route to Pending_Approval
                success = _handle_json_approval(entry.path, json_status)
            else:
                # Standard .md task file
                success = handler(entry.path)

            if not success and os.path.exists(entry.path):
                _in_flight.discard(entry.path)

        gone = {p for p in _in_flight if not os.path.exists(p)}
        _in_flight.difference_update(gone)


# ---------------------------------------------------------------------------
# Scan loop
# ---------------------------------------------------------------------------
# _in_flight:       paths being processed this cycle — prevents double-pickup.
# _pending_stable:  tracks (size, first_stable_time) for the stability gate.
# _intake_registry: maps source filename -> {"hash": str, "na_path": str}
#                   used to detect duplicate saves and update tasks in place.
_in_flight       = set()
_pending_stable  = {}   # path -> (observed_size, first_stable_timestamp)
_intake_registry = {}   # filename -> {"hash": str, "na_path": str}


def _is_stable(entry):
    """
    Return True only when the file's byte-size has been unchanged across at least
    two consecutive scan cycles separated by >= STABILITY_WAIT seconds.

    Side-effect: updates _pending_stable for the given path.
    """
    path = entry.path
    try:
        size = entry.stat().st_size
    except OSError:
        _pending_stable.pop(path, None)
        return False

    now  = time.time()
    prev = _pending_stable.get(path)

    if prev is None or prev[0] != size:
        # First time seen, or file is still growing — reset the clock.
        _pending_stable[path] = (size, now)
        return False

    # Size stable since prev[1] — check if the wait has elapsed.
    return (now - prev[1]) >= STABILITY_WAIT


def scan_folder(folder_path, source_label):
    try:
        entries = [e for e in os.scandir(folder_path) if e.is_file()]
    except FileNotFoundError:
        os.makedirs(folder_path, exist_ok=True)
        return
    except Exception as e:
        logging.error(f"SCAN_ERROR | source={source_label} | reason={e}")
        return

    # Prune stability records ONLY for files that belong to THIS folder and
    # are no longer present.  The previous implementation used a bare
    # `p not in current_paths` which cleared entries from OTHER folders
    # (e.g. an empty Inbox scan would wipe all Drop stability entries every
    # 10 s, making stability impossible to achieve).
    current_paths = {e.path for e in entries}
    for p in [p for p in list(_pending_stable)
              if os.path.dirname(p) == folder_path and p not in current_paths]:
        _pending_stable.pop(p, None)

    # Skip files already in-flight this cycle.
    candidates = [e for e in entries if e.path not in _in_flight]

    # Stability gate: size must be unchanged for >= STABILITY_WAIT seconds.
    stable = [e for e in candidates if _is_stable(e)]
    if not stable:
        return

    # ── Read + validate + deduplicate ────────────────────────────────────────
    # Each stable file is read once here; the content is forwarded to
    # process_file() so it never reads the file a second time.
    to_intake = []  # list of (entry, raw, content_hash) for fresh intake

    for entry in stable:
        try:
            with open(entry.path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            continue

        _, body = parse_frontmatter(raw)
        if not body.strip():
            # Empty body — leave in source folder, reset stability so the user
            # can keep typing and the file will be re-evaluated next cycle.
            logging.debug(
                f"EMPTY_BODY | source={source_label} | file={entry.name} "
                f"| action=left_in_source_retry_next_cycle"
            )
            _pending_stable.pop(entry.path, None)
            continue

        h        = _body_hash(raw)
        filename = entry.name
        existing = _intake_registry.get(filename)

        logging.info(
            f"DEDUP_CHECK | file={filename} | h={h[:8]} "
            f"| registry_hit={existing is not None} "
            f"| hash_match={existing is not None and existing['hash'] == h} "
            f"| existing_hash={existing['hash'][:8] if existing else 'none'}"
        )

        # ── Case 1: identical content already intaken (VS Code re-save) ─────
        if existing is not None and existing["hash"] == h:
            logging.info(
                f"DUPLICATE_IGNORED | source={source_label} | file={filename} "
                f"| hash={h[:8]} | action=removed_from_source"
            )
            try:
                os.remove(entry.path)
            except OSError as exc:
                logging.warning(
                    f"DUPLICATE_CLEANUP_WARN | file={filename} | reason={exc}"
                )
            _pending_stable.pop(entry.path, None)
            continue

        # ── Case 2: same filename, content changed, active task still open ──
        if existing is not None and os.path.exists(existing.get("na_path", "")):
            na_path = existing["na_path"]
            _in_flight.add(entry.path)
            enriched = ensure_frontmatter(raw, source_label)

            # Update the Needs_Action file in place.
            try:
                with open(na_path, "w", encoding="utf-8") as fh:
                    fh.write(enriched)
            except Exception as exc:
                logging.error(
                    f"UPDATE_WRITE_ERROR | source={source_label} | file={filename} "
                    f"| reason={exc} | action=falling_back_to_fresh_intake"
                )
                to_intake.append((entry, raw, h))
                _pending_stable.pop(entry.path, None)
                continue

            # Archive the new version (source moved off disk).
            archive_name = _archive_only(entry.path, source_label)
            logging.info(
                f"TASK_UPDATED | source={source_label} | file={filename} "
                f"| needs_action={os.path.basename(na_path)} "
                f"| archive={archive_name} | hash={h[:8]}"
            )
            _intake_registry[filename] = {"hash": h, "na_path": na_path}
            _pending_stable.pop(entry.path, None)
            continue

        # ── Case 3: new file or previously-processed task (fresh intake) ────
        to_intake.append((entry, raw, h))

    # Flush any in-flight entries moved off disk by Case 2 updates.
    gone = {p for p in _in_flight if not os.path.exists(p)}
    _in_flight.difference_update(gone)

    if not to_intake:
        return

    logging.info(f"{source_label}: {len(to_intake)} new file(s) found.")

    for entry, raw, h in to_intake:
        _in_flight.add(entry.path)
        intake = process_file(entry.path, source_label, raw=raw)

        if intake is None and os.path.exists(entry.path):
            # Intake failed before archive — file still on disk, allow retry.
            _in_flight.discard(entry.path)
        elif intake is not None:
            na_full = os.path.join(NEEDS_ACTION, intake["na"])
            _intake_registry[entry.name] = {"hash": h, "na_path": na_full}
            try:
                process_one()
            except Exception as e:
                logging.error(f"PROCESSOR_ERROR | reason={e}")

    gone = {p for p in _in_flight if not os.path.exists(p)}
    _in_flight.difference_update(gone)


def scan_scheduled_folder():
    """
    Check vault/Scheduled/ every cycle.
    Any file whose scheduled_at <= now is moved to vault/Approved/
    so the normal approval pipeline picks it up.
    """
    import json as _json
    try:
        entries = [e for e in os.scandir(SCHEDULED_DIR) if e.is_file()]
    except FileNotFoundError:
        os.makedirs(SCHEDULED_DIR, exist_ok=True)
        return
    except Exception as e:
        logging.error(f"SCHEDULED_SCAN_ERROR | reason={e}")
        return

    now_utc = datetime.now(timezone.utc)

    for entry in entries:
        try:
            # Support both .json and .md scheduled files
            if entry.name.endswith(".json"):
                with open(entry.path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                sched_raw = data.get("scheduled_at", "")
            else:
                with open(entry.path, "r", encoding="utf-8") as f:
                    raw = f.read()
                fields, _ = parse_frontmatter(raw)
                sched_raw = fields.get("scheduled_at", "")

            if not sched_raw:
                # No schedule — move immediately
                dst = os.path.join(APPROVED_DIR, entry.name)
                shutil.move(entry.path, dst)
                logging.info(f"SCHEDULED_RELEASED | file={entry.name} | reason=no_scheduled_at")
                continue

            sched_dt = datetime.fromisoformat(sched_raw.replace("Z", "+00:00"))
            if sched_dt <= now_utc:
                dst = os.path.join(APPROVED_DIR, entry.name)
                shutil.move(entry.path, dst)
                logging.info(f"SCHEDULED_RELEASED | file={entry.name} | was={sched_raw}")
                print(f"  >>> SCHEDULED → Approved: {entry.name}")
            else:
                remaining = sched_dt - now_utc
                h, rem = divmod(int(remaining.total_seconds()), 3600)
                m = rem // 60
                logging.info(f"SCHEDULED_WAITING | file={entry.name} | fires_at={sched_raw} | in={h}h {m}m")

        except Exception as e:
            logging.error(f"SCHEDULED_ERROR | file={entry.name} | reason={e}")


def main():
    logging.info("=" * 60)
    logging.info(f"Watcher started. version={WATCHER_VERSION}")
    logging.info(f"Intake   : Inbox={INBOX_DIR}")
    logging.info(f"           Drop ={DROP_DIR}")
    logging.info(f"Approval : Approved={APPROVED_DIR}")
    logging.info(f"           Rejected={REJECTED_DIR}")
    logging.info(f"Log file : {LOG_FILE}")
    logging.info("=" * 60)

    while True:
        try:
            scan_folder(INBOX_DIR, "inbox")
            scan_folder(DROP_DIR,  "drop")
            scan_approval_folders()
            scan_scheduled_folder()
        except Exception as e:
            logging.error(f"TOP_LEVEL_ERROR | reason={e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
