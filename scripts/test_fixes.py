#!/usr/bin/env python3
"""
test_fixes.py — Automated regression tests for 4 workflow bug fixes.

Tests:
  A. Stability check prevents early pickup
  B. Empty body left in Drop (not archived or queued)
  C. Empty/unsupported files do not block the processor queue
  D. Bank statement email handler matches and generates output
  E. No duplicate intake across multiple scans of the same file

Run from project root:
    python scripts/test_fixes.py
"""

import os
import sys
import time
import shutil
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# Result tracking
# ─────────────────────────────────────────────────────────────────────────────
_results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    _results.append((status, name, detail))
    tag = f"[{status}]"
    line = f"  {tag:<6} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)


# ─────────────────────────────────────────────────────────────────────────────
# TEST A — Stability check prevents early pickup
# ─────────────────────────────────────────────────────────────────────────────

def test_A_stability():
    print("\n=== TEST A: Stability gate ===")
    import watchers.main_watcher as mw

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("hello world\n")
        tmp_path = f.name

    class _FakeEntry:
        path = tmp_path
        name = os.path.basename(tmp_path)
        def stat(self): return os.stat(tmp_path)

    entry = _FakeEntry()
    mw._pending_stable.clear()

    try:
        # 1st call — should NOT be stable (first time seen)
        r1 = mw._is_stable(entry)
        check("A1: first scan -> not stable", not r1)

        # 2nd call immediately — size same, but clock not elapsed
        r2 = mw._is_stable(entry)
        check("A2: immediate re-scan -> still not stable", not r2)

        # Fast-forward clock past STABILITY_WAIT
        size, t = mw._pending_stable[tmp_path]
        mw._pending_stable[tmp_path] = (size, t - mw.STABILITY_WAIT - 1)
        r3 = mw._is_stable(entry)
        check("A3: after wait elapsed -> stable", r3)

        # Append bytes -> size changes -> clock resets
        with open(tmp_path, "a") as fh:
            fh.write("more content\n")
        r4 = mw._is_stable(entry)
        check("A4: size changed -> stability reset", not r4)

    finally:
        os.unlink(tmp_path)
        mw._pending_stable.clear()


# ─────────────────────────────────────────────────────────────────────────────
# TEST B — Empty body is left in Drop, not archived
# ─────────────────────────────────────────────────────────────────────────────

def test_B_empty_body_left_in_drop():
    print("\n=== TEST B: Empty body left in Drop ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d_drop    = os.path.join(tmp, "Drop");    os.makedirs(d_drop)
        d_archive = os.path.join(tmp, "Archive"); os.makedirs(d_archive)
        d_needs   = os.path.join(tmp, "Needs_Action"); os.makedirs(d_needs)
        d_done    = os.path.join(tmp, "Done");    os.makedirs(d_done)
        d_pending = os.path.join(tmp, "Pending"); os.makedirs(d_pending)

        orig = _patch_paths(mw, tp,
                            drop=d_drop, archive=d_archive, needs=d_needs,
                            done=d_done, pending=d_pending)
        mw._in_flight.clear()
        mw._pending_stable.clear()

        try:
            drop_file = os.path.join(d_drop, "empty.md")
            with open(drop_file, "w") as f:
                f.write("   \n\n   \n")  # whitespace only

            # Force stability to pass
            _force_stable(mw, drop_file)

            mw.scan_folder(d_drop, "drop")

            check("B1: empty file stays in Drop",        os.path.exists(drop_file))
            check("B2: Archive is empty",                len(os.listdir(d_archive)) == 0)
            check("B3: Needs_Action is empty",           len(os.listdir(d_needs)) == 0)
            check("B4: stability entry cleared (reset)", drop_file not in mw._pending_stable)

        finally:
            _restore_paths(mw, tp, orig)
            mw._in_flight.clear()
            mw._pending_stable.clear()


# ─────────────────────────────────────────────────────────────────────────────
# TEST C — Empty/unsupported files do not block the queue
# ─────────────────────────────────────────────────────────────────────────────

def test_C_queue_not_blocked():
    print("\n=== TEST C: Empty file does not block processor queue ===")
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d_needs   = os.path.join(tmp, "Needs_Action"); os.makedirs(d_needs)
        d_done    = os.path.join(tmp, "Done");         os.makedirs(d_done)
        d_pending = os.path.join(tmp, "Pending");      os.makedirs(d_pending)

        orig_na, orig_d, orig_p = tp.NEEDS_ACTION, tp.DONE_DIR, tp.PENDING_DIR
        tp.NEEDS_ACTION = d_needs
        tp.DONE_DIR     = d_done
        tp.PENDING_DIR  = d_pending

        try:
            # File 1: empty body — must be skipped
            f_empty = os.path.join(d_needs, "20260326_000001_empty.md")
            with open(f_empty, "w") as f:
                f.write(_frontmatter("aaa") + "\n")

            # File 2: bank statement task — must be processed
            f_bank = os.path.join(d_needs, "20260326_000002_bank.md")
            with open(f_bank, "w") as f:
                f.write(_frontmatter("bbb") + "write email for bank satement\n")

            result = tp.process_one()

            pending_files = os.listdir(d_pending)
            check("C1: process_one returns True",             result is True)
            check("C2: empty file still in Needs_Action",     os.path.exists(f_empty))
            check("C3: bank file removed from Needs_Action",  not os.path.exists(f_bank))
            check("C4: bank file in Pending_Approval",        len(pending_files) == 1,
                  f"found: {pending_files}")

            if pending_files:
                pa_path = os.path.join(d_pending, pending_files[0])
                with open(pa_path) as fh:
                    content = fh.read()
                check("C5: result contains 'bank statement'",
                      "bank statement" in content.lower())

        finally:
            tp.NEEDS_ACTION = orig_na
            tp.DONE_DIR     = orig_d
            tp.PENDING_DIR  = orig_p


# ─────────────────────────────────────────────────────────────────────────────
# TEST D — Bank statement handler
# ─────────────────────────────────────────────────────────────────────────────

def test_D_bank_handler():
    print("\n=== TEST D: Bank statement email handler ===")
    from processors.task_processor import (
        _match_bank_email, _handle_bank_email,
        generate_result, is_sensitive,
    )

    cases_should_match = [
        "write email for bank satement",       # original typo
        "write email for bank statement",      # correct spelling
        "Write Email for Bank Statement",      # mixed case
        "draft bank statement email",
        "send bank statement email",
        "write bank statemant email",          # alternate typo
        "write bank statment email",           # another typo
    ]
    cases_no_match = [
        "write holiday leave application",
        "write a short story",
        "send email to friend",
        "bank transfer request",              # no statement keyword
    ]

    for body in cases_should_match:
        check(f"D_match: {body!r}", _match_bank_email(body))

    for body in cases_no_match:
        check(f"D_no_match: {body!r}", not _match_bank_email(body))

    result, matched = generate_result("write email for bank satement", {})
    check("D_generate: matched via registry",           matched)
    check("D_generate: result is non-empty",            bool(result and result.strip()))
    check("D_generate: result contains 'bank statement'",
          result is not None and "bank statement" in result.lower())
    check("D_sensitive: email keyword triggers review", is_sensitive("write email for bank satement"))


# ─────────────────────────────────────────────────────────────────────────────
# TEST E — No duplicate intake across multiple scans
# ─────────────────────────────────────────────────────────────────────────────

def test_E_no_duplicate():
    print("\n=== TEST E: No duplicate intake ===")
    import watchers.main_watcher as mw
    import processors.task_processor as tp

    with tempfile.TemporaryDirectory() as tmp:
        d_drop    = os.path.join(tmp, "Drop");    os.makedirs(d_drop)
        d_archive = os.path.join(tmp, "Archive"); os.makedirs(d_archive)
        d_needs   = os.path.join(tmp, "Needs_Action"); os.makedirs(d_needs)
        d_done    = os.path.join(tmp, "Done");    os.makedirs(d_done)
        d_pending = os.path.join(tmp, "Pending"); os.makedirs(d_pending)

        orig = _patch_paths(mw, tp,
                            drop=d_drop, archive=d_archive, needs=d_needs,
                            done=d_done, pending=d_pending)
        mw._in_flight.clear()
        mw._pending_stable.clear()

        try:
            drop_file = os.path.join(d_drop, "task.md")
            with open(drop_file, "w") as f:
                f.write("write email for bank statement\n")

            # Scan 1: file just appeared — not stable yet
            mw.scan_folder(d_drop, "drop")
            a1 = len(os.listdir(d_archive))
            n1 = len(os.listdir(d_needs))
            check("E1: scan1 -> no intake (not stable)", a1 == 0 and n1 == 0,
                  f"archive={a1}, needs={n1}")

            # Fast-forward stability
            _force_stable(mw, drop_file)

            # Scan 2: stable -> intake once
            mw.scan_folder(d_drop, "drop")
            a2 = len(os.listdir(d_archive))
            check("E2: scan2 -> exactly 1 archive entry", a2 == 1, f"archive={a2}")

            # Scan 3: file already gone from Drop -> no new intake
            mw.scan_folder(d_drop, "drop")
            a3 = len(os.listdir(d_archive))
            check("E3: scan3 -> still 1 archive entry (no duplicate)", a3 == 1,
                  f"archive={a3}")

            # Scan 4: another pass for good measure
            mw.scan_folder(d_drop, "drop")
            a4 = len(os.listdir(d_archive))
            check("E4: scan4 -> still 1 archive entry", a4 == 1, f"archive={a4}")

        finally:
            _restore_paths(mw, tp, orig)
            mw._in_flight.clear()
            mw._pending_stable.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _frontmatter(uid):
    return (
        f"---\nid: {uid}\nsource: drop\nstatus: pending\n"
        f"created_at: 2026-01-01T00:00:00Z\ntask_type: general\n---\n"
    )


def _force_stable(mw, path):
    """Inject a stability record that looks like STABILITY_WAIT has already elapsed."""
    size = os.path.getsize(path)
    mw._pending_stable[path] = (size, time.time() - mw.STABILITY_WAIT - 1)


def _patch_paths(mw, tp, *, drop, archive, needs, done, pending):
    orig = {
        "mw.DROP_DIR":    mw.DROP_DIR,
        "mw.ARCHIVE_DIR": mw.ARCHIVE_DIR,
        "mw.NEEDS_ACTION": mw.NEEDS_ACTION,
        "tp.NEEDS_ACTION": tp.NEEDS_ACTION,
        "tp.DONE_DIR":    tp.DONE_DIR,
        "tp.PENDING_DIR": tp.PENDING_DIR,
    }
    mw.DROP_DIR     = drop
    mw.ARCHIVE_DIR  = archive
    mw.NEEDS_ACTION = needs
    tp.NEEDS_ACTION = needs
    tp.DONE_DIR     = done
    tp.PENDING_DIR  = pending
    return orig


def _restore_paths(mw, tp, orig):
    mw.DROP_DIR     = orig["mw.DROP_DIR"]
    mw.ARCHIVE_DIR  = orig["mw.ARCHIVE_DIR"]
    mw.NEEDS_ACTION = orig["mw.NEEDS_ACTION"]
    tp.NEEDS_ACTION = orig["tp.NEEDS_ACTION"]
    tp.DONE_DIR     = orig["tp.DONE_DIR"]
    tp.PENDING_DIR  = orig["tp.PENDING_DIR"]


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("AI-Employee-Silver  —  Workflow Fix Regression Tests")
    print("=" * 60)

    test_A_stability()
    test_B_empty_body_left_in_drop()
    test_C_queue_not_blocked()
    test_D_bank_handler()
    test_E_no_duplicate()

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
