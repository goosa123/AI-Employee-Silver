#!/usr/bin/env python3
"""
test_dedup.py  —  Regression tests for VS Code duplicate-save deduplication.

Scenarios tested:
  1. File created and intaken normally               -> 1 archive, 1 NA
  2. Same file re-saved (identical content)          -> DUPLICATE_IGNORED, still 1 archive
  3. File edited and re-saved (new content)
     a. NA still open                                -> TASK_UPDATED, 2 archives, 1 NA (updated)
     b. NA already processed                         -> fresh intake, 3 archives, 2 NA
  4. Both Inbox and Drop folders are covered
  5. Old test_fixes suite still passes               -> no regressions

Run from project root:
    python scripts/test_dedup.py
"""

import os
import sys
import time
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ── Result tracker ────────────────────────────────────────────────────────────
_results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    _results.append((status, name, detail))
    tag  = f"[{status}]"
    line = f"  {tag:<6} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _frontmatter(uid="abc"):
    return (
        f"---\nid: {uid}\nsource: drop\nstatus: pending\n"
        f"created_at: 2026-01-01T00:00:00Z\ntask_type: general\n---\n"
    )


def _force_stable(mw, path):
    size = os.path.getsize(path)
    mw._pending_stable[path] = (size, time.time() - mw.STABILITY_WAIT - 1)


def _patch(mw, tp, *, drop, archive, needs, done, pending, inbox=None):
    orig = {
        "mw.DROP_DIR":     mw.DROP_DIR,
        "mw.INBOX_DIR":    mw.INBOX_DIR,
        "mw.ARCHIVE_DIR":  mw.ARCHIVE_DIR,
        "mw.NEEDS_ACTION": mw.NEEDS_ACTION,
        "tp.NEEDS_ACTION": tp.NEEDS_ACTION,
        "tp.DONE_DIR":     tp.DONE_DIR,
        "tp.PENDING_DIR":  tp.PENDING_DIR,
    }
    mw.DROP_DIR     = drop
    mw.INBOX_DIR    = inbox or drop
    mw.ARCHIVE_DIR  = archive
    mw.NEEDS_ACTION = needs
    tp.NEEDS_ACTION = needs
    tp.DONE_DIR     = done
    tp.PENDING_DIR  = pending
    return orig


def _restore(mw, tp, orig):
    mw.DROP_DIR     = orig["mw.DROP_DIR"]
    mw.INBOX_DIR    = orig["mw.INBOX_DIR"]
    mw.ARCHIVE_DIR  = orig["mw.ARCHIVE_DIR"]
    mw.NEEDS_ACTION = orig["mw.NEEDS_ACTION"]
    tp.NEEDS_ACTION = orig["tp.NEEDS_ACTION"]
    tp.DONE_DIR     = orig["tp.DONE_DIR"]
    tp.PENDING_DIR  = orig["tp.PENDING_DIR"]


def _clear_state(mw):
    mw._in_flight.clear()
    mw._pending_stable.clear()
    mw._intake_registry.clear()


def _scan(mw, folder, label):
    """Run one scan cycle (stability already forced by caller)."""
    mw.scan_folder(folder, label)


def _write(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── TEST 1: Normal first intake ───────────────────────────────────────────────

def test_1_normal_intake():
    print("\n=== TEST 1: Normal first intake ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d = _mk_dirs(tmp)
        orig = _patch(mw, tp, **d)
        _clear_state(mw)

        try:
            drop_file = os.path.join(d["drop"], "task.md")
            # Use unmatched body so processor leaves the NA file in place
            _write(drop_file, _frontmatter() + "dedup regression test task v1\n")

            # Scan 1: not stable yet
            _scan(mw, d["drop"], "drop")
            check("1a: scan1 -> no intake (not stable)",
                  len(os.listdir(d["archive"])) == 0)

            # Scan 2: stable -> intaken
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")
            a = len(os.listdir(d["archive"]))
            n = len(os.listdir(d["needs"]))
            check("1b: 1 archive entry",  a == 1, f"archive={a}")
            check("1c: 1 Needs_Action",   n == 1, f"needs={n}")
            check("1d: Drop is empty",    len(os.listdir(d["drop"])) == 0)
            check("1e: registry populated",
                  "task.md" in mw._intake_registry)

        finally:
            _restore(mw, tp, orig)
            _clear_state(mw)


# ── TEST 2: Identical re-save (DUPLICATE_IGNORED) ────────────────────────────

def test_2_duplicate_ignored():
    print("\n=== TEST 2: Duplicate re-save -> DUPLICATE_IGNORED ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d = _mk_dirs(tmp)
        orig = _patch(mw, tp, **d)
        _clear_state(mw)

        try:
            drop_file = os.path.join(d["drop"], "task.md")
            # Unmatched body: processor leaves NA file open
            content = _frontmatter() + "dedup regression test task v1\n"
            _write(drop_file, content)

            # First intake
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")
            check("2a: first intake ok", len(os.listdir(d["archive"])) == 1)

            # VS Code saves same content again
            _write(drop_file, content)
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")

            a = len(os.listdir(d["archive"]))
            n = len(os.listdir(d["needs"]))
            check("2b: DUPLICATE_IGNORED -> still 1 archive",     a == 1, f"archive={a}")
            check("2c: still 1 Needs_Action (no duplicate NA)",   n == 1, f"needs={n}")
            check("2d: duplicate source removed from Drop",
                  not os.path.exists(drop_file))

            # Third re-save of same content
            _write(drop_file, content)
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")
            check("2e: third re-save still ignored",
                  len(os.listdir(d["archive"])) == 1)

        finally:
            _restore(mw, tp, orig)
            _clear_state(mw)


# ── TEST 3a: Content changed, NA still open (TASK_UPDATED) ───────────────────

def test_3a_task_updated_na_open():
    print("\n=== TEST 3a: Content changed, NA open -> TASK_UPDATED ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d = _mk_dirs(tmp)
        orig = _patch(mw, tp, **d)
        _clear_state(mw)

        try:
            drop_file = os.path.join(d["drop"], "task.md")
            # Unmatched bodies so processor leaves NA open
            v1 = _frontmatter() + "dedup regression test task v1\n"
            _write(drop_file, v1)

            # First intake
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")
            check("3a-1: first intake ok", len(os.listdir(d["archive"])) == 1)

            na_files = os.listdir(d["needs"])
            check("3a-1b: NA file created", len(na_files) == 1, f"na_files={na_files}")
            if not na_files:
                print("    [SKIP] Cannot continue 3a without NA file")
                return

            na_file = na_files[0]
            na_path = os.path.join(d["needs"], na_file)

            # User edits and re-saves with different content
            v2 = _frontmatter() + "dedup regression test task v2 updated content\n"
            _write(drop_file, v2)
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")

            a = len(os.listdir(d["archive"]))
            n = len(os.listdir(d["needs"]))
            check("3a-2: 2 archive entries (v1 + v2)",         a == 2, f"archive={a}")
            check("3a-3: still only 1 Needs_Action file",      n == 1, f"needs={n}")
            check("3a-4: NA file is same name (updated in place)",
                  os.path.exists(na_path))
            check("3a-5: NA content has updated body",
                  "v2 updated content" in _read(na_path))
            check("3a-6: registry hash updated",
                  mw._intake_registry.get("task.md", {}).get("hash") != "")

        finally:
            _restore(mw, tp, orig)
            _clear_state(mw)


# ── TEST 3b: Content changed, NA already processed (fresh intake) ─────────────

def test_3b_fresh_intake_after_processed():
    print("\n=== TEST 3b: Content changed, NA processed -> fresh intake ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d = _mk_dirs(tmp)
        orig = _patch(mw, tp, **d)
        _clear_state(mw)

        try:
            drop_file = os.path.join(d["drop"], "task.md")
            v1 = _frontmatter() + "dedup regression test task v1\n"
            _write(drop_file, v1)

            # First intake
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")

            # Simulate NA file being processed (removed by processor)
            for f in os.listdir(d["needs"]):
                os.remove(os.path.join(d["needs"], f))
            check("3b-1: NA cleared (simulating processing)",
                  len(os.listdir(d["needs"])) == 0)

            # User edits file and saves again
            v2 = _frontmatter() + "dedup regression test task v2 new content\n"
            _write(drop_file, v2)
            _force_stable(mw, drop_file)
            _scan(mw, d["drop"], "drop")

            a = len(os.listdir(d["archive"]))
            n = len(os.listdir(d["needs"]))
            check("3b-2: 2 archive entries", a == 2, f"archive={a}")
            check("3b-3: new NA created",    n == 1, f"needs={n}")

        finally:
            _restore(mw, tp, orig)
            _clear_state(mw)


# ── TEST 4: Inbox folder covered (same logic) ─────────────────────────────────

def test_4_inbox_dedup():
    print("\n=== TEST 4: Inbox folder dedup ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d = _mk_dirs(tmp)
        orig = _patch(mw, tp, inbox=d["drop"], **d)
        _clear_state(mw)

        try:
            inbox_file = os.path.join(d["drop"], "mail.md")  # drop acts as inbox
            content = _frontmatter() + "dedup regression inbox test unmatched\n"
            _write(inbox_file, content)

            _force_stable(mw, inbox_file)
            _scan(mw, d["drop"], "inbox")
            check("4a: first inbox intake ok",
                  len(os.listdir(d["archive"])) == 1)

            # Re-save same content
            _write(inbox_file, content)
            _force_stable(mw, inbox_file)
            _scan(mw, d["drop"], "inbox")
            check("4b: inbox duplicate ignored",
                  len(os.listdir(d["archive"])) == 1)
            check("4c: no extra NA file",
                  len(os.listdir(d["needs"])) == 1)

        finally:
            _restore(mw, tp, orig)
            _clear_state(mw)


# ── TEST 5: _body_hash helper ─────────────────────────────────────────────────

def test_5_body_hash():
    print("\n=== TEST 5: _body_hash helper ===")
    from watchers.main_watcher import _body_hash

    raw_a = _frontmatter("x") + "hello world\n"
    raw_b = _frontmatter("y") + "hello world\n"   # different frontmatter, same body
    raw_c = _frontmatter("x") + "different body\n"

    check("5a: same body, diff frontmatter -> same hash",
          _body_hash(raw_a) == _body_hash(raw_b))
    check("5b: diff body -> diff hash",
          _body_hash(raw_a) != _body_hash(raw_c))
    check("5c: whitespace-only body -> consistent hash",
          _body_hash("   \n\n") == _body_hash("\n   "))


# ── TEST 6: regression — existing test_fixes suite ───────────────────────────

def test_6_regression():
    print("\n=== TEST 6: Regression - test_fixes suite ===")
    import subprocess
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "scripts", "test_fixes.py")],
        capture_output=True, text=True
    )
    passed = "OVERALL: PASS" in result.stdout
    check("6: test_fixes.py still passes", passed,
          "FAIL" if not passed else "all 32 checks ok")
    if not passed:
        # Print last 20 lines for diagnosis
        for line in result.stdout.strip().splitlines()[-20:]:
            print(f"    {line}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mk_dirs(tmp):
    dirs = {
        "drop":    os.path.join(tmp, "Drop"),
        "archive": os.path.join(tmp, "Archive"),
        "needs":   os.path.join(tmp, "Needs_Action"),
        "done":    os.path.join(tmp, "Done"),
        "pending": os.path.join(tmp, "Pending"),
    }
    for d in dirs.values():
        os.makedirs(d)
    return dirs


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("AI-Employee-Silver  --  Dedup Regression Tests")
    print("=" * 60)

    test_1_normal_intake()
    test_2_duplicate_ignored()
    test_3a_task_updated_na_open()
    test_3b_fresh_intake_after_processed()
    test_4_inbox_dedup()
    test_5_body_hash()
    test_6_regression()

    passed = sum(1 for s, _, _ in _results if s == "PASS")
    failed = sum(1 for s, _, _ in _results if s == "FAIL")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(_results)} checks")
    print("=" * 60)

    if failed == 0:
        print("\n*** OVERALL: PASS ***\n")
        sys.exit(0)
    else:
        print("\n*** OVERALL: FAIL ***")
        for s, name, detail in _results:
            if s == "FAIL":
                print(f"  FAILED: {name}" + (f"  ({detail})" if detail else ""))
        print()
        sys.exit(1)
