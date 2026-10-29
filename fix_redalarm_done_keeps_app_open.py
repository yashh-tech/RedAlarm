#!/usr/bin/env python3
"""Remove accidental app-close behavior from the alarm confirmation DONE action.

Run from the RedAlarm repository root on fix/spinner-cancel-touch.
This does NOT alter close behavior for real ringing, Dismiss, or Snooze actions.
"""
from __future__ import annotations

import datetime
import pathlib
import re
import subprocess
import sys

TARGET_BRANCH = "fix/spinner-cancel-touch"
BAD_LINE = '                Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.45)\n'
TOAST_LINE = '                Clock.schedule_once(lambda _dt: android_show_toast(message), 0.12)\n'


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def main() -> int:
    root = pathlib.Path(run_git("rev-parse", "--show-toplevel"))
    branch = run_git("branch", "--show-current")
    if branch != TARGET_BRANCH:
        raise RuntimeError(
            f"Wrong branch {branch!r}; switch to {TARGET_BRANCH!r} first."
        )

    main_file = root / "main.py"
    source = main_file.read_text(encoding="utf-8")
    if source.count(BAD_LINE) != 1:
        raise RuntimeError(
            "Expected exactly one accidental close call with the 0.45s delay; "
            "nothing was changed. The source may already be fixed or has drifted."
        )

    # Ensure the line being removed is in the confirmation DONE block, not elsewhere.
    toast_pos = source.find(TOAST_LINE)
    bad_pos = source.find(BAD_LINE)
    if toast_pos < 0 or bad_pos < toast_pos or bad_pos - toast_pos > 400:
        raise RuntimeError(
            "The close call is not next to the confirmation toast; nothing was changed."
        )

    backup_dir = pathlib.Path("/tmp") / (
        "redalarm-done-close-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    backup_dir.mkdir(parents=True, exist_ok=False)
    (backup_dir / "main.py").write_bytes(main_file.read_bytes())
    print(f"[RedAlarm] Backup: {backup_dir}")

    updated = source.replace(BAD_LINE, "", 1)
    if "Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.20)" not in updated:
        raise RuntimeError("Ringing close behavior was not found after edit; nothing written.")
    compile(updated, str(main_file), "exec")
    main_file.write_text(updated, encoding="utf-8")

    # Confirm only the confirmation action lost its close call.
    saved = main_file.read_text(encoding="utf-8")
    if BAD_LINE in saved:
        raise RuntimeError("Confirmation close call still present after writing.")
    if "Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.20)" not in saved:
        raise RuntimeError("Ring-session close behavior missing after writing.")

    print("[RedAlarm] FIX APPLIED: DONE no longer closes the app.")
    print("[RedAlarm] Dismiss/Snooze/ringing cleanup close paths were preserved.")
    print("[RedAlarm] main.py syntax passed.")
    print("Next: git diff --check && python -m compileall -q main.py redalarm_timepicker.py validate_redalarm_timepicker_integration.py && python validate_redalarm_timepicker_integration.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[RedAlarm patch] ABORTED: {exc}", file=sys.stderr)
        raise SystemExit(1)
