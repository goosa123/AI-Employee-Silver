import os
import re
import uuid
import logging
import subprocess
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEEDS_ACTION = os.path.join(BASE_DIR, "vault", "Needs_Action")
DONE_DIR     = os.path.join(BASE_DIR, "vault", "Done")
PENDING_DIR  = os.path.join(BASE_DIR, "vault", "Pending_Approval")
LOG_FILE     = os.path.join(BASE_DIR, "vault", "Logs", "processor.log")

# Keywords that mark a task as sensitive — result goes to Pending_Approval.
SENSITIVE_KEYWORDS = ["send", "email", "post", "linkedin"]

# Claude CLI settings
CLAUDE_MODEL   = "haiku"   # fast, cost-effective for task generation
CLAUDE_TIMEOUT = 120       # seconds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
for _d in (NEEDS_ACTION, DONE_DIR, PENDING_DIR, os.path.dirname(LOG_FILE)):
    os.makedirs(_d, exist_ok=True)

_log = logging.getLogger("processor")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fmt = logging.Formatter("%(asctime)s [PROCESSOR] %(message)s", "%Y-%m-%d %H:%M:%S")
    _fh  = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh  = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _log.addHandler(_fh)
    _log.addHandler(_sh)
_log.propagate = False

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


# ---------------------------------------------------------------------------
# Sensitivity routing
# ---------------------------------------------------------------------------

def _norm(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def is_sensitive(body):
    """Return True if any sensitive keyword appears in the task body."""
    n = _norm(body)
    return any(kw in n for kw in SENSITIVE_KEYWORDS)


# ---------------------------------------------------------------------------
# Claude CLI generator
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a professional AI assistant. "
    "Complete the task exactly as requested. "
    "Output only the final result — no explanations, no preamble, no meta-commentary."
)


def call_claude(task_body):
    """
    Call Claude CLI with the task body and return the generated text.

    Returns (result_text, True)  on success.
    Returns (error_reason, False) on failure — caller must leave file in Needs_Action.
    """
    prompt = f"{SYSTEM_PROMPT}\n\nTask:\n{task_body.strip()}"

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", CLAUDE_MODEL],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"Claude timed out after {CLAUDE_TIMEOUT}s", False
    except FileNotFoundError:
        return "claude CLI not found on PATH", False
    except Exception as e:
        return f"subprocess error: {e}", False

    if proc.returncode != 0:
        stderr = proc.stderr.strip()[:200]
        return f"Claude exited {proc.returncode}: {stderr}", False

    result = proc.stdout.strip()
    if not result:
        return "Claude returned empty output", False

    return result, True


# ---------------------------------------------------------------------------
# Output file writers
# ---------------------------------------------------------------------------

def write_done(fields, body, result_text, source_filename):
    """Write a completed result to vault/Done/."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    done_fields = {
        "id":           fields.get("id", str(uuid.uuid4())),
        "source":       fields.get("source", "unknown"),
        "status":       "done",
        "task_type":    fields.get("task_type", "general"),
        "created_at":   fields.get("created_at", now),
        "completed_at": now,
        "source_file":  source_filename,
        "generated_by": "claude",
    }

    content = (
        build_frontmatter(done_fields)
        + "## Original Task\n\n"
        + body.strip()
        + "\n\n"
        + "## Result\n\n"
        + result_text.strip()
        + "\n"
    )

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(source_filename)[0]
    name = f"{ts}_{base}_done.md"
    ctr  = 1
    while os.path.exists(os.path.join(DONE_DIR, name)):
        name = f"{ts}_{base}_done_{ctr}.md"
        ctr += 1

    with open(os.path.join(DONE_DIR, name), "w", encoding="utf-8") as fh:
        fh.write(content)
    return name


def write_pending_approval(fields, body, result_text, source_filename):
    """Write a result that needs human review to vault/Pending_Approval/."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    pa_fields = {
        "id":           fields.get("id", str(uuid.uuid4())),
        "source":       fields.get("source", "unknown"),
        "status":       "pending_approval",
        "task_type":    fields.get("task_type", "general"),
        "created_at":   fields.get("created_at", now),
        "reviewed_at":  "",
        "source_file":  source_filename,
        "generated_by": "claude",
    }

    content = (
        build_frontmatter(pa_fields)
        + "## Original Task\n\n"
        + body.strip()
        + "\n\n"
        + "## Result\n\n"
        + result_text.strip()
        + "\n"
    )

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(source_filename)[0]
    name = f"{ts}_{base}_pending.md"
    ctr  = 1
    while os.path.exists(os.path.join(PENDING_DIR, name)):
        name = f"{ts}_{base}_pending_{ctr}.md"
        ctr += 1

    with open(os.path.join(PENDING_DIR, name), "w", encoding="utf-8") as fh:
        fh.write(content)
    return name


# ---------------------------------------------------------------------------
# Main processing logic
# ---------------------------------------------------------------------------

def process_one():
    """
    Scan Needs_Action for the oldest eligible .md file and process it via Claude.

    Routing:
      - sensitive task  -> vault/Pending_Approval/
      - normal task     -> vault/Done/

    On Claude failure: file stays in Needs_Action, error is logged.

    Returns True  if a file was successfully processed.
    Returns False otherwise.
    """
    try:
        candidates = sorted(
            (e for e in os.scandir(NEEDS_ACTION) if e.is_file() and e.name.endswith(".md")),
            key=lambda e: e.stat().st_mtime
        )
    except Exception as e:
        _log.error(f"Cannot scan Needs_Action: {e}")
        return False

    if not candidates:
        _log.info("Needs_Action is empty -- nothing to process.")
        return False

    for entry in candidates:
        filename = entry.name
        filepath = entry.path

        _log.info(f"Processing: {filename}")

        # --- Read ---
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except Exception as e:
            _log.error(f"READ_ERROR | file={filename} | reason={e} | action=skipping_to_next")
            continue

        fields, body = parse_frontmatter(raw)
        body = body.strip()

        if not body:
            _log.warning(f"SKIP_EMPTY | file={filename} | action=skipping_to_next")
            continue

        # --- Call Claude ---
        result_text, ok = call_claude(body)

        if not ok:
            _log.error(
                f"CLAUDE_FAIL | file={filename} | reason={result_text} "
                f"| action=left_in_Needs_Action"
            )
            continue  # leave file in Needs_Action, try next candidate

        # --- Route ---
        sensitive = is_sensitive(body)

        try:
            if sensitive:
                out_name = write_pending_approval(fields, body, result_text, filename)
                out_dir  = "Pending_Approval"
                status   = "pending_approval"
            else:
                out_name = write_done(fields, body, result_text, filename)
                out_dir  = "Done"
                status   = "done"
        except Exception as e:
            _log.error(
                f"WRITE_ERROR | file={filename} | sensitive={sensitive} "
                f"| reason={e} | action=left_in_Needs_Action"
            )
            continue

        # --- Remove from Needs_Action only after successful write ---
        try:
            os.remove(filepath)
        except Exception as e:
            _log.error(
                f"CLEANUP_ERROR | file={filename} | out={out_name} | reason={e} "
                f"| note=result written but source not removed"
            )

        _log.info(f"OK | file={filename} | out={out_dir}/{out_name} | status={status} | engine=claude")
        print(f"  >>> {status.upper()}: {filename} -> {out_dir}/{out_name}")
        return True

    _log.info("No eligible file processed from Needs_Action.")
    return False


def main():
    _log.info("=" * 60)
    _log.info("Processor run started (engine: claude).")
    _log.info("=" * 60)
    process_one()
    _log.info("Processor run finished.")


if __name__ == "__main__":
    main()
