"""
processors/linkedin_processor.py
Scans vault/linkedin/intake/ for brief files, drafts a LinkedIn post,
and saves the artifact to vault/Pending_Approval/linkedin/.

Supported brief formats:
  .json  — { "topic": "...", "tone": "...", "audience": "...",
              "key_points": [...], "cta": "..." }
  .md    — frontmatter (topic: ...) or plain text treated as topic

No posting. No auto-approval. Human reviews vault/Pending_Approval/linkedin/.
"""

import sys
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.linkedin.config import (
    INTAKE_DIR,
    INTAKE_EXTENSIONS,
    PENDING_APPROVAL,
    PROCESSED_IDS,
    SOURCE,
    STATUS_PENDING,
    FIELD_TOPIC, FIELD_TONE, FIELD_AUDIENCE, FIELD_KEY_POINTS, FIELD_CTA,
    REQUIRED_FIELDS,
    ensure_linkedin_dirs,
)
from skills.linkedin_drafter.skill import draft_linkedin_post
from utils.plan_writer import create_plan, update_plan

log = logging.getLogger(__name__)

PENDING_LINKEDIN = PENDING_APPROVAL   # all approvals in one folder


# ---------------------------------------------------------------------------
# Processed IDs registry
# ---------------------------------------------------------------------------

def _load_processed_ids() -> set:
    if not PROCESSED_IDS.exists():
        return set()
    return set(PROCESSED_IDS.read_text(encoding="utf-8").splitlines())


def _mark_processed(file_stem: str) -> None:
    PROCESSED_IDS.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_IDS.open("a", encoding="utf-8") as f:
        f.write(file_stem + "\n")


# ---------------------------------------------------------------------------
# Brief parsers
# ---------------------------------------------------------------------------

def _parse_json_brief(path: Path) -> dict | None:
    """Parse a .json brief file. Returns normalized dict or None on error."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"PARSE_ERROR | file={path.name} | reason={e}")
        return None

    if not isinstance(raw, dict):
        log.warning(f"PARSE_ERROR | file={path.name} | reason=not a JSON object")
        return None

    return raw


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_md_brief(path: Path) -> dict | None:
    """
    Parse a .md brief file.
    Supports YAML-style frontmatter (key: value) or plain text (treated as topic).
    Returns normalized dict or None on error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"PARSE_ERROR | file={path.name} | reason={e}")
        return None

    m = _FM_RE.match(text)
    if m:
        fields = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip().lower()] = val.strip()
        body = text[m.end():].strip()
        if body and FIELD_TOPIC not in fields:
            fields[FIELD_TOPIC] = body
        return fields if fields else None

    # No frontmatter — treat entire text as topic
    topic = text.strip()
    if not topic:
        log.warning(f"PARSE_ERROR | file={path.name} | reason=empty file")
        return None
    return {FIELD_TOPIC: topic}


def _parse_brief(path: Path) -> dict | None:
    """Route to the correct parser based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _parse_json_brief(path)
    if suffix == ".md":
        return _parse_md_brief(path)
    log.warning(f"UNSUPPORTED_FORMAT | file={path.name} | suffix={suffix}")
    return None


def _validate(brief: dict, filename: str) -> bool:
    """Return True if all required fields are present and non-empty."""
    for field in REQUIRED_FIELDS:
        if not brief.get(field, "").strip():
            log.warning(f"MISSING_REQUIRED_FIELD | file={filename} | field={field}")
            return False
    return True


# ---------------------------------------------------------------------------
# Schedule parser
# ---------------------------------------------------------------------------

def _parse_scheduled_at(raw: str) -> str:
    """
    Parse a human-friendly schedule string into ISO-8601 UTC string.
    Accepted formats:
      "HH:MM"               → today at HH:MM local time (tomorrow if already past)
      "YYYY-MM-DD HH:MM"    → that date at HH:MM local time
      "YYYY-MM-DDTHH:MM:SS" → ISO, used as-is (assumed local)
    Returns ISO UTC string, or empty string if parsing fails.
    """
    from datetime import timedelta
    import re as _re

    raw = raw.strip()
    now_local = datetime.now()

    # "HH:MM" only
    m = _re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        scheduled = now_local.replace(
            hour=int(m.group(1)), minute=int(m.group(2)),
            second=0, microsecond=0
        )
        if scheduled <= now_local:
            scheduled += timedelta(days=1)
        return scheduled.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # "YYYY-MM-DD HH:MM"
    m = _re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})", raw)
    if m:
        try:
            scheduled = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
            return scheduled.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass

    # ISO-ish "YYYY-MM-DDTHH:MM:SS"
    try:
        scheduled = datetime.fromisoformat(raw)
        if scheduled.tzinfo is None:
            scheduled = scheduled.astimezone(timezone.utc)
        return scheduled.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass

    log.warning(f"SCHEDULE_PARSE_FAILED | raw={raw!r} | field will be omitted")
    return ""


# ---------------------------------------------------------------------------
# Artifact writer
# ---------------------------------------------------------------------------

def _save_artifact(brief: dict, post: str, reason: str, source_file: str) -> Path:
    """Save a pending-approval JSON artifact to vault/Pending_Approval/linkedin/."""
    PENDING_LINKEDIN.mkdir(parents=True, exist_ok=True)

    stem     = Path(source_file).stem
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"linkedin_{ts}_{stem}.json"
    path     = PENDING_LINKEDIN / filename

    artifact = {
        "source":       SOURCE,
        "source_file":  source_file,
        "topic":        brief.get(FIELD_TOPIC, ""),
        "tone":         brief.get(FIELD_TONE, ""),
        "audience":     brief.get(FIELD_AUDIENCE, ""),
        "key_points":   brief.get(FIELD_KEY_POINTS, []),
        "cta":          brief.get(FIELD_CTA, ""),
        "post":         post,
        "draft_reason": reason,
        "status":       STATUS_PENDING,
        "created_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Optional scheduled posting: brief can include scheduled_at in any of these formats:
    #   "HH:MM"                    → today at that time (or tomorrow if already past)
    #   "YYYY-MM-DD HH:MM"         → specific date and time
    #   "YYYY-MM-DDTHH:MM:SS"      → ISO format
    raw_schedule = brief.get("scheduled_at", "").strip()
    if raw_schedule:
        artifact["scheduled_at"] = _parse_scheduled_at(raw_schedule)

    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

def process_intake() -> list[dict]:
    """
    Scan intake dir, parse briefs, draft posts, save artifacts.
    Returns list of result dicts for each newly processed file.
    """
    ensure_linkedin_dirs()
    PENDING_LINKEDIN.mkdir(parents=True, exist_ok=True)

    try:
        candidates = [
            p for p in INTAKE_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in INTAKE_EXTENSIONS
        ]
    except Exception as e:
        log.error(f"SCAN_ERROR | dir={INTAKE_DIR} | reason={e}")
        return []

    if not candidates:
        log.info("No intake files found.")
        return []

    processed_ids = _load_processed_ids()
    log.info(f"Found {len(candidates)} intake file(s). Known processed: {len(processed_ids)}.")

    results = []

    for path in candidates:
        stem = path.stem

        if stem in processed_ids:
            log.info(f"SKIP_DUPLICATE | file={path.name}")
            continue

        log.info(f"PROCESSING | file={path.name}")

        # Plan — step 1: Brief received
        create_plan(stem, "linkedin", path.stem[:60])

        brief = _parse_brief(path)
        if brief is None:
            log.warning(f"SKIP_BAD_PARSE | file={path.name} | action=skipped")
            _mark_processed(stem)
            continue

        if not _validate(brief, path.name):
            log.warning(f"SKIP_INVALID | file={path.name} | action=skipped")
            _mark_processed(stem)
            continue

        result = draft_linkedin_post(brief)
        post   = result.get("post", "")
        reason = result.get("reason", "")
        log.info(f"DRAFTED | file={path.name}")
        update_plan(stem, "Draft generated")

        try:
            artifact_path = _save_artifact(brief, post, reason, path.name)
            log.info(f"ARTIFACT_SAVED | file={path.name} | artifact={artifact_path.name}")
            update_plan(stem, "Pending approval")
        except Exception as e:
            log.error(f"ARTIFACT_ERROR | file={path.name} | reason={e} | action=skipped")
            continue

        _mark_processed(stem)

        results.append({
            "source_file":   path.name,
            "topic":         brief.get(FIELD_TOPIC, ""),
            "post_preview":  post[:120],
            "artifact_path": str(artifact_path),
        })

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [LINKEDIN_PROCESSOR] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("LinkedIn processor started.")
    results = process_intake()
    log.info(f"Done. Processed {len(results)} brief(s).")

    for r in results:
        print(f"\n  file     : {r['source_file']}")
        print(f"  topic    : {r['topic']}")
        print(f"  preview  : {r['post_preview']}...")
        print(f"  artifact : {r['artifact_path']}")


if __name__ == "__main__":
    main()
