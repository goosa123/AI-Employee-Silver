"""
utils/plan_writer.py
Lightweight Plan.md tracker — one file per task in vault/Plans/.
Write failure NEVER raises — callers are never blocked.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent
PLANS_DIR = BASE_DIR / "vault" / "Plans"

# Step definitions per source type
GMAIL_STEPS    = ["Email received", "Classified", "Draft generated",
                  "Pending approval", "Sent", "Done"]
LINKEDIN_STEPS = ["Brief received", "Draft generated", "Pending approval", "Done"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_short() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _plan_path(task_id: str, source: str) -> Path:
    return PLANS_DIR / f"{source}_{task_id}.md"


def _find_plan(task_id: str) -> Path | None:
    """Locate an existing plan file by task_id regardless of source prefix."""
    if not PLANS_DIR.exists():
        return None
    matches = list(PLANS_DIR.glob(f"*_{task_id}.md"))
    return matches[0] if matches else None


def _steps_for(source: str) -> list[str]:
    if source == "gmail":
        return list(GMAIL_STEPS)
    if source == "linkedin":
        return list(LINKEDIN_STEPS)
    return ["Received", "Processed", "Done"]


def _render_steps(steps: list[str], completed: set) -> list[str]:
    return [f"- [{'x' if s in completed else ' '}] {s}" for s in steps]


def _parse_plan(text: str) -> dict:
    meta = {}
    completed = []
    log_lines = []
    in_steps = False
    in_log = False

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("source:"):
            meta["source"] = s.split(":", 1)[1].strip()
        elif s.startswith("task_id:"):
            meta["task_id"] = s.split(":", 1)[1].strip()
        elif s.startswith("created_at:"):
            meta["created_at"] = s.split(":", 1)[1].strip()
        elif s == "## Steps":
            in_steps, in_log = True, False
        elif s == "## Log":
            in_steps, in_log = False, True
        elif in_steps and s.startswith("- [x]"):
            completed.append(s[5:].strip())
        elif in_log and s.startswith("-"):
            log_lines.append(s)

    return {"meta": meta, "completed": completed, "log_lines": log_lines}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_plan(task_id: str, source: str, label: str) -> None:
    """
    Create vault/Plans/{source}_{task_id}.md. Skips silently if already exists.
    Never raises.
    """
    try:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        path = _plan_path(task_id, source)
        if path.exists():
            return

        steps = _steps_for(source)
        first = steps[0]

        lines = [
            "---",
            f"task_id: {task_id}",
            f"source: {source}",
            f"created_at: {_now()}",
            f"status: in_progress",
            "---",
            "",
            f"# Plan: {label}",
            "",
            "## Steps",
            "",
        ] + _render_steps(steps, {first}) + [
            "",
            "## Log",
            "",
            f"- {_ts_short()} — {first}",
            "",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"PLAN_CREATED | id={task_id} | source={source}")
    except Exception as e:
        log.warning(f"PLAN_CREATE_FAILED | id={task_id} | reason={e}")


def update_plan(task_id: str, step: str, note: str = "") -> None:
    """
    Mark step as completed and append a log line. Never raises.
    """
    try:
        path = _find_plan(task_id)
        if path is None:
            log.warning(f"PLAN_NOT_FOUND | id={task_id} | step={step}")
            return

        text   = path.read_text(encoding="utf-8")
        parsed = _parse_plan(text)

        source    = parsed["meta"].get("source", "gmail")
        completed = set(parsed["completed"])
        completed.add(step)
        log_lines = parsed["log_lines"]

        steps    = _steps_for(source)
        status   = "done" if all(s in completed for s in steps) else "in_progress"

        entry = f"- {_ts_short()} — {step}" + (f" ({note})" if note else "")
        log_lines.append(entry)

        created_at = parsed["meta"].get("created_at", _now())
        task_id_m  = parsed["meta"].get("task_id", task_id)

        title_line = next((l for l in text.splitlines() if l.startswith("# Plan:")), "")
        label = title_line.replace("# Plan:", "").strip() or task_id

        lines = [
            "---",
            f"task_id: {task_id_m}",
            f"source: {source}",
            f"created_at: {created_at}",
            f"status: {status}",
            "---",
            "",
            f"# Plan: {label}",
            "",
            "## Steps",
            "",
        ] + _render_steps(steps, completed) + [
            "",
            "## Log",
            "",
        ] + log_lines + [""]

        path.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"PLAN_UPDATED | id={task_id} | step={step} | status={status}")
    except Exception as e:
        log.warning(f"PLAN_UPDATE_FAILED | id={task_id} | step={step} | reason={e}")
