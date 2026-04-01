"""
scripts/approval_ui.py
Approval UI for LinkedIn / Gmail / general tasks.

Flow:
  Pending Approval  -->  [Approve]   --> Scheduled/  (with or without time)
  Pending Approval  -->  [Reject]    --> Rejected/
  Scheduled         -->  [Post Now]  --> Approved/   (immediate)
  Scheduled         -->  [Set Time]  --> stays in Scheduled/ with updated time
  Scheduled         -->  [Cancel]    --> Rejected/

Run: python scripts/approval_ui.py   (auto-opens browser)
"""

import json
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for

BASE_DIR      = Path(__file__).resolve().parent.parent
PENDING_DIR   = BASE_DIR / "vault" / "Pending_Approval"
APPROVED_DIR  = BASE_DIR / "vault" / "Approved"
REJECTED_DIR  = BASE_DIR / "vault" / "Rejected"
SCHEDULED_DIR = BASE_DIR / "vault" / "Scheduled"

for d in (APPROVED_DIR, REJECTED_DIR, SCHEDULED_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Approval Queue</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f0f2f5; color: #1a1a1a; padding: 24px; }

  .header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }
  .header h1 { font-size: 1.35rem; font-weight: 700; }
  .pill {
    font-size: .78rem; font-weight: 700;
    padding: 4px 12px; border-radius: 20px;
  }
  .pill-pending   { background: #1a73e8; color: #fff; }
  .pill-scheduled { background: #f59e0b; color: #fff; }
  .pill-zero      { background: #34a853; color: #fff; }

  .section-title {
    font-size: .82rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .07em; color: #666; margin: 28px 0 12px;
    max-width: 740px; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px;
  }
  .empty { color: #aaa; font-size: .88rem; padding: 10px 0; max-width: 740px; }

  .card {
    background: #fff; border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,.07);
    padding: 20px; margin-bottom: 14px; max-width: 740px;
  }
  .card.sched-card { border-left: 4px solid #f59e0b; }

  .card-top { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px; }
  .badge {
    display: inline-block; font-size: .68rem; font-weight: 700;
    padding: 3px 9px; border-radius: 20px;
    text-transform: uppercase; letter-spacing: .05em;
    white-space: nowrap; margin-top: 3px; flex-shrink: 0;
  }
  .badge-linkedin { background: #e8f0fe; color: #1a73e8; }
  .badge-gmail    { background: #fce8e6; color: #d93025; }
  .badge-general  { background: #f3e8ff; color: #7c3aed; }

  .topic { font-size: .98rem; font-weight: 600; }
  .meta  { font-size: .76rem; color: #999; margin-top: 2px; }

  .sched-tag {
    display: inline-flex; align-items: center; gap: 5px;
    background: #fef3c7; color: #92400e;
    font-size: .78rem; font-weight: 600;
    padding: 3px 11px; border-radius: 20px; margin-bottom: 10px;
  }
  .sched-tag.unset { background: #f3f4f6; color: #6b7280; }

  .post {
    background: #f8f9fa; border-left: 3px solid #d1d5db; border-radius: 4px;
    padding: 11px 14px; white-space: pre-wrap;
    font-size: .85rem; line-height: 1.65;
    margin-bottom: 14px; max-height: 240px; overflow-y: auto;
  }
  .sched-card .post { border-left-color: #f59e0b; }

  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .btn {
    padding: 8px 18px; border: none; border-radius: 8px;
    font-size: .85rem; font-weight: 600; cursor: pointer;
    transition: opacity .15s;
  }
  .btn:hover { opacity: .82; }
  .btn-approve   { background: #34a853; color: #fff; }
  .btn-reject    { background: #ea4335; color: #fff; }
  .btn-postnow   { background: #1a73e8; color: #fff; }
  .btn-settime   { background: #f59e0b; color: #fff; }
  .btn-cancel    { background: #9ca3af; color: #fff; font-size: .78rem; padding: 7px 13px; }

  .time-wrap { display: flex; align-items: center; gap: 6px; }
  .time-label { font-size: .75rem; color: #666; white-space: nowrap; }
  .time-input {
    border: 1px solid #d1d5db; border-radius: 6px;
    padding: 6px 10px; font-size: .82rem; width: 170px;
  }

  .divider { width: 1px; height: 28px; background: #e5e7eb; margin: 0 4px; }

  .flash {
    border-radius: 8px; padding: 9px 14px; margin-bottom: 14px;
    font-size: .85rem; max-width: 740px;
  }
  .flash.ok    { background: #e6f4ea; border: 1px solid #34a853; color: #1e7e34; }
  .flash.err   { background: #fce8e6; border: 1px solid #ea4335; color: #c62828; }
  .flash.sched { background: #fef3c7; border: 1px solid #f59e0b; color: #92400e; }

  .topbar { display: flex; justify-content: flex-end; max-width: 740px; margin-bottom: 6px; }
  a.refresh { color: #1a73e8; font-size: .78rem; text-decoration: none; }
</style>
</head>
<body>

<div class="header">
  <h1>Approval Queue</h1>
  {% if pending %}
  <span class="pill pill-pending">{{ pending|length }} pending</span>
  {% endif %}
  {% if scheduled %}
  <span class="pill pill-scheduled">{{ scheduled|length }} scheduled</span>
  {% endif %}
  {% if not pending and not scheduled %}
  <span class="pill pill-zero">All clear</span>
  {% endif %}
</div>

{% for msg, kind in messages %}
<div class="flash {{ kind }}">{{ msg }}</div>
{% endfor %}

<div class="topbar"><a class="refresh" href="/">Refresh</a></div>

<!-- ══ PENDING APPROVAL ══════════════════════════════════════════ -->
<div class="section-title">Pending Approval</div>
{% if not pending %}
  <div class="empty">Nothing pending.</div>
{% endif %}

{% for item in pending %}
<div class="card">
  <div class="card-top">
    <span class="badge badge-{{ item.source or 'general' }}">{{ item.source or 'general' }}</span>
    <div>
      <div class="topic">{{ item.topic or item.subject or '(no topic)' }}</div>
      <div class="meta">Created: {{ item.created_at }}</div>
    </div>
  </div>
  <div class="post">{{ item.post or item.body or '(no content)' }}</div>

  <form method="post" action="/approve">
    <input type="hidden" name="filename" value="{{ item.filename }}">
    <div class="actions">
      <button class="btn btn-approve" name="btn_action" value="approve">Approve</button>
      <button class="btn btn-reject"  name="btn_action" value="reject">Reject</button>
      <div class="divider"></div>
      <div class="time-wrap">
        <span class="time-label">Schedule time (optional):</span>
        <input class="time-input" type="text" name="scheduled_at"
               placeholder="09:00  or  2026-04-02 09:00">
      </div>
    </div>
  </form>
</div>
{% endfor %}

<!-- ══ SCHEDULED ════════════════════════════════════════════════ -->
<div class="section-title">Scheduled</div>
{% if not scheduled %}
  <div class="empty">No scheduled items.</div>
{% else %}
  {% for item in scheduled %}
  <div class="card sched-card">
    <div class="card-top">
      <span class="badge badge-{{ item.source or 'general' }}">{{ item.source or 'general' }}</span>
      <div>
        <div class="topic">{{ item.topic or item.subject or '(no topic)' }}</div>
        <div class="meta">Approved: {{ item.reviewed_at }}</div>
      </div>
    </div>

    {% if item.scheduled_at_fmt %}
    <div class="sched-tag">Schedule: {{ item.scheduled_at_fmt }}</div>
    {% else %}
    <div class="sched-tag unset">No time set — waiting for Post Now</div>
    {% endif %}

    <div class="post">{{ item.post or item.body or '(no content)' }}</div>

    <form method="post" action="/scheduled_action">
      <input type="hidden" name="filename" value="{{ item.filename }}">
      <div class="actions">
        <button class="btn btn-postnow"  name="btn_action" value="post_now">Post Now</button>
        <div class="divider"></div>
        <div class="time-wrap">
          <span class="time-label">Change time:</span>
          <input class="time-input" type="text" name="scheduled_at"
                 value="{{ item.scheduled_at_raw or '' }}"
                 placeholder="09:00  or  2026-04-02 09:00">
        </div>
        <button class="btn btn-settime" name="btn_action" value="set_time">Set</button>
        <div class="divider"></div>
        <button class="btn btn-cancel"  name="btn_action" value="cancel">Cancel</button>
      </div>
    </form>
  </div>
  {% endfor %}
{% endif %}

</body>
</html>
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y  %H:%M UTC")
    except Exception:
        return iso


def _parse_schedule(raw: str) -> str:
    sys.path.insert(0, str(BASE_DIR))
    from processors.linkedin_processor import _parse_scheduled_at
    return _parse_scheduled_at(raw)


def _scheduled_filename(data: dict, scheduled_at_iso: str) -> str:
    """
    Build a clean Scheduled/ filename:
      {source}_{YYYY-MM-DD}_{HH-MM}_{topic_slug}.json
    e.g. linkedin_2026-04-02_09-00_ai_automation_pakistan.json
    """
    import re
    source = data.get("source", "task")

    # Date and time from scheduled_at ISO string
    try:
        dt = datetime.fromisoformat(scheduled_at_iso.replace("Z", "+00:00"))
        dt_local = dt.astimezone()
        date_str = dt_local.strftime("%Y-%m-%d")
        time_str = dt_local.strftime("%H-%M")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = "00-00"

    # Topic slug
    topic = data.get("topic") or data.get("subject") or "task"
    slug  = re.sub(r"[^\w\s-]", "", topic.lower()).strip()
    slug  = re.sub(r"[\s_]+", "_", slug)[:40].strip("_")

    return f"{source}_{date_str}_{time_str}_{slug}.json"


def _load_pending():
    items = []
    for p in sorted(PENDING_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") not in ("pending_approval", "pending"):
            continue
        data["filename"]   = p.name
        data["created_at"] = _fmt_dt(data.get("created_at", ""))
        items.append(data)
    return items


def _load_scheduled():
    items = []
    for p in sorted(SCHEDULED_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["filename"]        = p.name
        data["scheduled_at_raw"] = data.get("scheduled_at", "")
        data["scheduled_at_fmt"] = _fmt_dt(data.get("scheduled_at", ""))
        data["reviewed_at"]     = _fmt_dt(data.get("reviewed_at", ""))
        items.append(data)
    items.sort(key=lambda x: x.get("scheduled_at_raw", ""))
    return items


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    messages = []
    act   = request.args.get("action", "")
    fname = request.args.get("file", "")
    msgs_map = {
        "approved":   ("Approved — moved to Scheduled.", "sched"),
        "rejected":   (f"Rejected: {fname}", "err"),
        "post_now":   (f"Sent for immediate posting: {fname}", "ok"),
        "time_set":   (f"Schedule time updated: {fname}", "sched"),
        "cancelled":  (f"Cancelled: {fname}", "err"),
    }
    if act in msgs_map:
        messages.append(msgs_map[act])

    return render_template_string(
        PAGE,
        pending=_load_pending(),
        scheduled=_load_scheduled(),
        messages=messages,
    )


@app.route("/approve", methods=["POST"])
def approve():
    filename     = request.form.get("filename", "")
    btn_action   = request.form.get("btn_action")
    scheduled_at = request.form.get("scheduled_at", "").strip()

    if not filename:
        return redirect(url_for("index"))

    src = PENDING_DIR / filename
    if not src.exists():
        return redirect(url_for("index"))

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return redirect(url_for("index"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if btn_action == "approve":
        data["status"]      = "scheduled"
        data["reviewed_at"] = now

        if scheduled_at:
            parsed = _parse_schedule(scheduled_at)
            if parsed:
                data["scheduled_at"] = parsed

        sched_iso    = data.get("scheduled_at", "")
        new_filename = _scheduled_filename(data, sched_iso) if sched_iso else f"scheduled_{filename}"
        dst = SCHEDULED_DIR / new_filename
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        src.unlink()
        return redirect(url_for("index", action="approved", file=new_filename))

    elif btn_action == "reject":
        data["status"]      = "rejected"
        data["reviewed_at"] = now
        dst = REJECTED_DIR / filename
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        src.unlink()
        return redirect(url_for("index", action="rejected", file=filename))

    return redirect(url_for("index"))


@app.route("/scheduled_action", methods=["POST"])
def scheduled_action():
    filename     = request.form.get("filename", "")
    btn_action   = request.form.get("btn_action")
    scheduled_at = request.form.get("scheduled_at", "").strip()

    if not filename:
        return redirect(url_for("index"))

    src = SCHEDULED_DIR / filename
    if not src.exists():
        return redirect(url_for("index"))

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return redirect(url_for("index"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if btn_action == "post_now":
        # Move to Approved/ → watcher posts immediately
        data["status"]   = "approved"
        data["post_now"] = now
        data.pop("scheduled_at", None)
        dst = APPROVED_DIR / filename
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        src.unlink()
        return redirect(url_for("index", action="post_now", file=filename))

    elif btn_action == "set_time":
        if scheduled_at:
            parsed = _parse_schedule(scheduled_at)
            if parsed:
                data["scheduled_at"] = parsed
                src.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return redirect(url_for("index", action="time_set", file=filename))

    elif btn_action == "cancel":
        data["status"] = "cancelled"
        dst = REJECTED_DIR / filename
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        src.unlink()
        return redirect(url_for("index", action="cancelled", file=filename))

    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = 5050
    url  = f"http://127.0.0.1:{port}"
    print(f"\n  Approval UI: {url}")
    print("  Press Ctrl+C to stop.\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
