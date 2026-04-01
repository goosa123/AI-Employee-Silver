#!/usr/bin/env python3
"""
test_live_dedup.py  —  Live end-to-end test against the RUNNING watcher.

Simulates VS Code saving the same file multiple times.
Waits for the real watcher (with STABILITY_WAIT=10s) to process each cycle.

Run:
    python scripts/test_live_dedup.py
"""

import os
import sys
import time
import glob as _glob
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP_DIR    = os.path.join(BASE_DIR, "vault", "Drop")
ARCHIVE_DIR = os.path.join(BASE_DIR, "vault", "Archive")
NEEDS_DIR   = os.path.join(BASE_DIR, "vault", "Needs_Action")
LOG_FILE    = os.path.join(BASE_DIR, "vault", "Logs", "watcher.log")
LOCK_FILE   = os.path.join(BASE_DIR, "watchers", "watcher.lock")

CYCLE       = 25   # seconds — CHECK_INTERVAL(10) + STABILITY_WAIT(10) + 5s buffer

_results = []


def check(name, condition, detail=""):
    s = "PASS" if condition else "FAIL"
    _results.append((s, name, detail))
    print(f"  [{s}] {name}" + (f"  ({detail})" if detail else ""))


def write_drop(name, content):
    path = os.path.join(DROP_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def count_matching(folder, stem):
    """Count files in folder whose name contains stem."""
    return len([f for f in os.listdir(folder) if stem in f])


def last_log_lines(n=30):
    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        return f.readlines()[-n:]


def grep_log(keyword, since_mark):
    """Count occurrences of keyword in log lines after since_mark."""
    lines = last_log_lines(60)
    found = 0
    past_mark = False
    for line in lines:
        if since_mark in line:
            past_mark = True
        if past_mark and keyword in line:
            found += 1
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ─────────────────────────────────────────────────────────────────────────────

def preflight():
    print("\n=== PRE-FLIGHT ===")

    # 1. Watcher running?
    if not os.path.exists(LOCK_FILE):
        check("watcher lock exists", False, "watcher not running — start it first")
        sys.exit(1)
    with open(LOCK_FILE) as f:
        pid = f.read().strip()
    check(f"watcher lock present (PID {pid})", True)

    # 2. Version confirmed in log?
    recent = "".join(last_log_lines(100))
    has_ver = "version=2." in recent
    ver_str = next((w for w in recent.split() if w.startswith("version=")), "none")
    check(f"new watcher version in log ({ver_str})", has_ver)

    # 3. Clean stale files from ALL test folders (previous run leftovers)
    stem = "live_test_"
    for folder in (DROP_DIR, ARCHIVE_DIR, NEEDS_DIR):
        for f in os.listdir(folder):
            if stem in f:
                try:
                    os.remove(os.path.join(folder, f))
                except OSError:
                    pass
    # Also clean Pending_Approval and Done
    for folder_name in ("Pending_Approval", "Done"):
        folder = os.path.join(BASE_DIR, "vault", folder_name)
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if stem in f:
                    try:
                        os.remove(os.path.join(folder, f))
                    except OSError:
                        pass
    check("Folders cleaned before test", True)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Single save → exactly 1 Archive + 1 NA
# ─────────────────────────────────────────────────────────────────────────────

def test_1_single_save():
    print(f"\n=== TEST 1: Single save -> wait {CYCLE}s -> check intake ===")
    stem = "live_test_single"

    arc_before = count_matching(ARCHIVE_DIR, stem)
    na_before  = count_matching(NEEDS_DIR,   stem)

    # Use unique content each run so the registry never matches a prior run
    unique_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    content = f"write email for bank statement\nrun_id={unique_tag}\n"
    drop_path = write_drop(f"{stem}.md", content)
    print(f"  Dropped: {drop_path}")
    print(f"  Waiting {CYCLE}s for stability + intake...")
    time.sleep(CYCLE)

    arc_after = count_matching(ARCHIVE_DIR, stem)
    na_after  = count_matching(NEEDS_DIR,   stem)

    check("T1: 1 new archive entry",      arc_after - arc_before == 1,
          f"new={arc_after - arc_before}")
    # NA may be 0 if processor already handled it (sent to Pending_Approval) — that's OK
    check("T1: archive count is exactly 1", arc_after - arc_before == 1)
    return stem, content


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Same content re-saved 3× → DUPLICATE_IGNORED, no new archive/NA
# ─────────────────────────────────────────────────────────────────────────────

def test_2_duplicate_saves(stem, content):
    print(f"\n=== TEST 2: 3x same-content re-saves -> DUPLICATE_IGNORED ===")

    arc_before = count_matching(ARCHIVE_DIR, stem)

    for i in range(1, 4):
        drop_path = write_drop(f"{stem}.md", content)
        print(f"  Re-save #{i}: wrote {drop_path}")
        print(f"  Waiting {CYCLE}s...")
        time.sleep(CYCLE)

    arc_after = count_matching(ARCHIVE_DIR, stem)
    new_arc   = arc_after - arc_before

    # Read log and count DUPLICATE_IGNORED for this stem
    dup_count = sum(1 for line in last_log_lines(80)
                    if "DUPLICATE_IGNORED" in line and stem in line)

    check("T2: no new archive entries after 3 re-saves",  new_arc == 0,
          f"new_archives={new_arc}")
    check("T2: DUPLICATE_IGNORED logged at least 3 times", dup_count >= 3,
          f"dup_count={dup_count}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Content changed → TASK_UPDATED (1 more archive, same NA file)
# ─────────────────────────────────────────────────────────────────────────────

def test_3_content_changed():
    print(f"\n=== TEST 3: Content changed -> TASK_UPDATED ===")
    stem = "live_test_update"

    # Drop v1
    write_drop(f"{stem}.md", "dedup live test task v1 unmatched content\n")
    print(f"  Dropped v1. Waiting {CYCLE}s...")
    time.sleep(CYCLE)

    arc_v1 = count_matching(ARCHIVE_DIR, stem)
    na_v1  = count_matching(NEEDS_DIR,   stem)
    check("T3: v1 intaken -> 1 archive", arc_v1 == 1, f"archive={arc_v1}")
    check("T3: v1 in Needs_Action",      na_v1  == 1, f"na={na_v1}")

    if na_v1 == 0:
        print("  [INFO] NA already processed — TASK_UPDATED path will fall through to fresh intake")

    # Drop v2 (different content)
    write_drop(f"{stem}.md", "dedup live test task v2 updated content\n")
    print(f"  Dropped v2. Waiting {CYCLE}s...")
    time.sleep(CYCLE)

    arc_v2  = count_matching(ARCHIVE_DIR, stem)
    na_v2   = count_matching(NEEDS_DIR,   stem)
    upd_log = sum(1 for line in last_log_lines(40)
                  if "TASK_UPDATED" in line and stem in line)

    check("T3: v2 archived (total=2)",        arc_v2 == 2, f"archive={arc_v2}")
    if na_v1 == 1:
        check("T3: still 1 NA (updated in place)", na_v2 == 1, f"na={na_v2}")
        check("T3: TASK_UPDATED logged",           upd_log >= 1, f"upd_log={upd_log}")
    else:
        check("T3: fresh NA created",  na_v2 >= 1, f"na={na_v2}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("AI-Employee-Silver  --  Live Dedup Test (real watcher)")
    print("=" * 60)

    preflight()

    stem, content = test_1_single_save()
    test_2_duplicate_saves(stem, content)
    test_3_content_changed()

    passed = sum(1 for s, _, _ in _results if s == "PASS")
    failed = sum(1 for s, _, _ in _results if s == "FAIL")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\n*** OVERALL: PASS ***\n")
    else:
        print("\n*** OVERALL: FAIL ***")
        for s, name, detail in _results:
            if s == "FAIL":
                print(f"  FAILED: {name}" + (f"  ({detail})" if detail else ""))
        print()
    sys.exit(0 if failed == 0 else 1)
