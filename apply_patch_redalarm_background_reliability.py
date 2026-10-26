#!/usr/bin/env python3
"""Restore RedAlarm's native Android alarm/service pipeline on fix/spinner-cancel-touch.

Run from the repository root in GitHub Codespaces. The script fetches the
known-good native alarm implementation from origin/yashh-tech-patch-2 and
transplants only alarm/background logic; it preserves the current spinner UI.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import re
import subprocess
import sys

TARGET_BRANCH = "fix/spinner-cancel-touch"
REFERENCE_BRANCH = "origin/yashh-tech-patch-2"

NATIVE_FILES = [
    "android_src/org/yashtech/redalarm/RedAlarmNativeBridge.java",
    "android_src/org/yashtech/redalarm/RedAlarmAlarmReceiver.java",
    "android_src/org/yashtech/redalarm/RedAlarmRingingService.java",
    "android_src/org/yashtech/redalarm/RedAlarmApplication.java",
    "java_src/KivyAlarmReceiver.java",
    "java_src/manifest_hook.py",
]


def git(*args: str, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return (result.stdout or "").strip() if capture else ""


def git_file(ref: str, path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout


def replace_section(current: str, reference: str, start_marker: str, end_marker: str, label: str) -> str:
    def bounds(text: str) -> tuple[int, int]:
        start = text.find(start_marker)
        if start < 0:
            raise RuntimeError(f"Could not locate start marker for {label}")
        end = text.find(end_marker, start + len(start_marker))
        if end < 0:
            raise RuntimeError(f"Could not locate end marker for {label}")
        return start, end
    cs, ce = bounds(current)
    rs, re_ = bounds(reference)
    return current[:cs] + reference[rs:re_] + current[ce:]


def function_bounds(source: str, name: str) -> tuple[list[str], int, int]:
    lines = source.splitlines(keepends=True)
    pattern = re.compile(r"^    def " + re.escape(name) + r"\s*\(")
    starts = [i for i, line in enumerate(lines) if pattern.match(line)]
    if len(starts) != 1:
        raise RuntimeError(f"Expected one class method named {name}, found {len(starts)}")
    start = starts[0]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^    def \w+\s*\(", lines[i]) or re.match(r"^class \w+", lines[i]) or lines[i].startswith("if __name__ =="):
            end = i
            break
    return lines, start, end


def transplant_method(current: str, reference: str, name: str) -> str:
    cur_lines, cs, ce = function_bounds(current, name)
    ref_lines, rs, re_ = function_bounds(reference, name)
    return "".join(cur_lines[:cs] + ref_lines[rs:re_] + cur_lines[ce:])


def ensure_service_permissions(spec: str) -> str:
    lines = spec.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.startswith("android.permissions = ")), None)
    if index is None:
        raise RuntimeError("Could not find android.permissions in buildozer.spec")
    line = lines[index]
    prefix, values = line.split("=", 1)
    permissions = [p.strip() for p in values.strip().split(",") if p.strip()]
    for required in ("FOREGROUND_SERVICE", "FOREGROUND_SERVICE_MEDIA_PLAYBACK", "RECEIVE_BOOT_COMPLETED"):
        if required not in permissions:
            permissions.append(required)
    lines[index] = prefix + "= " + ",".join(permissions) + ("\n" if line.endswith("\n") else "")
    return "".join(lines)


def remove_confirmation_cancel(main: str) -> str:
    # The CANCEL button was wired with trigger_on_press=True and is the control
    # reported as hard to tap. Remove only this button and callback; leave Back
    # handling and auto-dismiss behavior unchanged.
    pattern = re.compile(
        r"\n        def cancel_review\(_button=None\):.*?\n        popup\.open\(\)",
        re.DOTALL,
    )
    main, count = pattern.subn("\n        popup.open()", main, count=1)
    if count != 1:
        raise RuntimeError("Could not safely remove the confirmation-page CANCEL control")
    return main


def main() -> int:
    root = pathlib.Path(git("rev-parse", "--show-toplevel"))
    branch = git("branch", "--show-current")
    if branch != TARGET_BRANCH:
        raise RuntimeError(
            f"Wrong branch: expected {TARGET_BRANCH!r}, currently on {branch!r}. "
            "Switch to fix/spinner-cancel-touch before running this patch."
        )

    # Do not overwrite any tracked edits that haven't been committed.
    if subprocess.run(["git", "diff", "--quiet"]).returncode != 0:
        raise RuntimeError("Tracked working-tree changes found. Commit or stash them before patching.")
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        raise RuntimeError("Staged changes found. Commit or unstage them before patching.")

    print(f"[RedAlarm patch] Repository: {root}")
    print(f"[RedAlarm patch] Branch: {branch}")
    print(f"[RedAlarm patch] Fetching native alarm reference: {REFERENCE_BRANCH}")
    git("fetch", "origin", f"+refs/heads/yashh-tech-patch-2:refs/remotes/{REFERENCE_BRANCH}")
    git(f"rev-parse", "--verify", f"{REFERENCE_BRANCH}^{{commit}}")

    # Back up any existing target files outside the repository before changing them.
    backup_root = pathlib.Path("/tmp") / ("redalarm-before-background-patch-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup_root.mkdir(parents=True, exist_ok=False)
    backup_paths = ["main.py", "buildozer.spec", *NATIVE_FILES]
    for rel in backup_paths:
        path = root / rel
        if path.is_file():
            dest = backup_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
    print(f"[RedAlarm patch] Backup saved to {backup_root}")

    current_main = (root / "main.py").read_text(encoding="utf-8")
    reference_main = git_file(REFERENCE_BRANCH, "main.py")

    # Replace only Android-native bridge and scheduler sections, not UI/timepicker code.
    current_main = replace_section(
        current_main, reference_main,
        "# ----------------------------------------------------------------------\n# ANDROID BRIDGE",
        "# ======================================================================\n# 2. STORAGE + SCHEDULING",
        "Android bridge",
    )
    current_main = replace_section(
        current_main, reference_main,
        "class AlarmScheduler:",
        "DEFAULT_RINGTONE_NAME =",
        "AlarmScheduler",
    )

    # Correct the outdated description in the copied bridge section: delivery
    # is native, not dependent on Activity relaunching.
    old_architecture_comment = """# How this actually wakes the phone, without any background service:
# AlarmManager.setAlarmClock() is the API Android reserves specifically for
# user-visible alarm clocks — the OS itself wakes the CPU at the exact time
# and directly re-launches THIS activity via a PendingIntent (no
# BroadcastReceiver, no 24/7 service needed; this is the same mechanism the
# stock Android Clock app uses). Once relaunched, this code acquires a
# WAKE_LOCK and sets window flags that draw over the lock screen and turn the
# screen on — that's what actually makes it \"wake the phone\" on top of
# merely firing on time.
"""
    new_architecture_comment = """# AlarmManager delivers to a native BroadcastReceiver, which starts the
# independent RedAlarmRingingService. Audio/wake-lock handling therefore does
# not depend on Kivy's render loop or the Activity staying alive. A boot/time
# receiver restores scheduled alarms from native preferences; PythonActivity
# is only the user-facing ringing screen and dismiss/snooze control surface.
"""
    current_main, _comment_replacements = re.subn(
        r"# How this actually wakes the phone, without any background service:\n.*?# merely firing on time\.\n",
        new_architecture_comment,
        current_main,
        count=1,
        flags=re.DOTALL,
    )

    # Native-service-aware ring lifecycle; this is what keeps sound alive when
    # the Python activity pauses/locks and prevents a late unlock from replaying it.
    for method in ("start_ringing", "_stop_common", "_dispatch_intent", "handle_alarm_fired", "on_stop"):
        current_main = transplant_method(current_main, reference_main, method)

    # Remove only the troublesome CANCEL button from the confirmation popup.
    current_main = remove_confirmation_cancel(current_main)
    (root / "main.py").write_text(current_main, encoding="utf-8")

    # Restore native receiver/service/application lifecycle and manifest registration.
    for rel in NATIVE_FILES:
        content = git_file(REFERENCE_BRANCH, rel)
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"[RedAlarm patch] Restored {rel}")

    spec_path = root / "buildozer.spec"
    spec = spec_path.read_text(encoding="utf-8")
    spec = ensure_service_permissions(spec)
    if "android.add_src = java_src,android_src" not in spec:
        raise RuntimeError("buildozer.spec must include android.add_src = java_src,android_src")
    if "p4a.hook = java_src/manifest_hook.py" not in spec:
        raise RuntimeError("buildozer.spec must point p4a.hook at java_src/manifest_hook.py")
    spec_path.write_text(spec, encoding="utf-8")

    # Fail early if the Python file has a syntax error before the user commits/builds.
    result = subprocess.run([sys.executable, "-m", "py_compile", "main.py"], cwd=root, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("main.py syntax validation failed:\n" + result.stderr)

    # Sanity checks for the key architecture and requested one-shot rule.
    checks = {
        "native bridge integration": "RedAlarmNativeBridge" in current_main and "android_native_ring_is_active" in current_main,
        "native ring service integration": "android_stop_native_ring_service" in current_main,
        "confirmation cancel callback removed": "def cancel_review(_button=None):" not in current_main,
        "receiver/service manifest hook": "RedAlarmRingingService" in (root / "java_src/manifest_hook.py").read_text(encoding="utf-8"),
        "boot recovery without launching Kivy": "restoreOnBoot(context)" in (root / "java_src/KivyAlarmReceiver.java").read_text(encoding="utf-8"),
        "one-shot completion handled natively": "markOneTimeComplete(context, id)" in (root / "android_src/org/yashtech/redalarm/RedAlarmAlarmReceiver.java").read_text(encoding="utf-8"),
        "foreground service permission": "FOREGROUND_SERVICE_MEDIA_PLAYBACK" in spec,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("Post-patch verification failed: " + ", ".join(failed))

    print("\n[RedAlarm patch] Applied and syntax-checked successfully.")
    print("[RedAlarm patch] Current spinner UI/timepicker was preserved; only the confirmation CANCEL control was removed.")
    print("[RedAlarm patch] Review the diff, then commit/push the branch and build a fresh APK.")
    print("\nNext commands (from repository root):")
    print("  git diff --check")
    print("  git status --short")
    print('  git add main.py buildozer.spec android_src java_src/KivyAlarmReceiver.java java_src/manifest_hook.py')
    print('  git commit -m "Fix native background alarm reliability and one-shot cleanup"')
    print("  git push origin fix/spinner-cancel-touch")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\n[RedAlarm patch] ABORTED: {exc}", file=sys.stderr)
        raise SystemExit(1)
