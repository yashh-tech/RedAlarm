#!/usr/bin/env python3
"""Standard-library regression checks for the RedAlarm Tech Patch 2 source.

These checks avoid importing Kivy/pyjnius and run before Buildozer downloads the
Android toolchain. They verify static wiring; touch/audio behavior still needs
runtime testing on an Android device.
"""
from __future__ import annotations

import ast
import datetime
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
MAIN = ROOT / "main.py"
KV = ROOT / "alarm.kv"
MODULE = ROOT / "redalarm_timepicker.py"


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def class_methods(source: str):
    tree = ast.parse(source)
    return {
        (cls.name, node.name): node
        for cls in (item for item in tree.body if isinstance(item, ast.ClassDef))
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def extract_functions(source: str, names: set[str], injected=None):
    tree = ast.parse(source)
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in names]
    found = {node.name for node in selected}
    if found != names:
        fail("Expected helpers missing: {}".format(sorted(names - found)))
    namespace = dict(injected or {})
    mini = ast.Module(body=selected, type_ignores=[])
    exec(compile(mini, "<helpers>", "exec"), namespace)
    return namespace


def class_assign_value(source: str, class_name: str, attr_name: str):
    tree = ast.parse(source)
    cls = next((node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name), None)
    if cls is None:
        fail("Class {} missing".format(class_name))
    assignment = next((node for node in cls.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == attr_name
                               for target in node.targets)), None)
    if assignment is None:
        fail("{}.{} missing".format(class_name, attr_name))
    return eval(compile(ast.Expression(assignment.value), "<preset_expression>", "eval"), {})


def source_for_node(source: str, node) -> str:
    return "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])


def main() -> int:
    for path in (MAIN, KV, MODULE):
        if not path.is_file():
            fail("Missing required file: {}".format(path.name))

    main_text = MAIN.read_text(encoding="utf-8")
    kv_text = KV.read_text(encoding="utf-8")
    module_text = MODULE.read_text(encoding="utf-8")
    main_tree = ast.parse(main_text)
    module_tree = ast.parse(module_text)
    compile(main_text, str(MAIN), "exec")
    compile(module_text, str(MODULE), "exec")
    print("PASS: main.py and redalarm_timepicker.py compile")

    namespace = extract_functions(module_text, {"format_duration", "_parse_duration"})
    fmt, parse = namespace["format_duration"], namespace["_parse_duration"]
    durations = {3: "3 sec", 30: "30 sec", 60: "1 min", 600: "10 min",
                 900: "15 min", 1800: "30 min", 3600: "1 Hr",
                 4500: "1.25 Hr", 5400: "1.5 Hr", 6300: "1.75 Hr",
                 7200: "2 Hr", 10800: "3 Hr"}
    for seconds, expected in durations.items():
        if fmt(seconds) != expected:
            fail("format_duration({}) mismatch".format(seconds))
    parse_cases = {"3s": 3, "30s": 30, "5m": 300, "1h": 3600,
                   "1.5h": 5400, "3h": 10800, "5": 300}
    for text, expected in parse_cases.items():
        if parse(text, 300) != expected:
            fail("_parse_duration({!r}) mismatch".format(text))
    presets = class_assign_value(module_text, "DurationRow", "PRESETS")
    if presets != sorted(set(presets)) or presets[0] != 1 or presets[-1] != 10800:
        fail("DurationRow.PRESETS must be unique, sorted, bounded by 1 sec/3 Hr")
    # Auto-dismiss is allowed down to 1 second; SnoozeRow separately enforces 3 seconds.
    if any(value not in presets for value in (1, 3, 5, 10, 15, 30, 60, 600, 900, 1800, 2700, 10800)):
        fail("A required duration preset is missing")
    print("PASS: duration labels, parser, ordered presets and 3 Hr cap")

    if sum(1 for n in ast.walk(main_tree)
           if isinstance(n, ast.FunctionDef) and n.name == "open_time_picker") != 1:
        fail("Duplicate/shadowing open_time_picker definitions remain")
    if sum(1 for n in ast.walk(main_tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_apply_picked_time") != 1:
        fail("Duplicate/shadowing _apply_picked_time definitions remain")
    if "class TimePickerPage(AnchorLayout):" not in module_text:
        fail("Current inline TimePickerPage implementation missing")
    if "class AlarmAppSettingsPage(BoxLayout):" not in module_text:
        fail("Alarm settings page missing")
    if "from redalarm_timepicker import AlarmEditorUI, RoundedActionButton, RoundedPanel, format_duration" not in main_text:
        fail("main.py does not import the active editor")
    if "_commit_pending_confirmation()" not in main_text or "self._show_alarm_confirmation(alarm, trigger_dt)" not in main_text:
        fail("Alarm review/commit wiring is missing")
    if "def cancel_confirmation(self, popup=None):" not in main_text:
        fail("Unified confirmation cancellation handler missing")
    if 'RoundedActionButton("CANCEL", callback=cancel_review' in main_text:
        fail("Confirmation popup CANCEL button should be removed")
    if 'RoundedActionButton("DONE", callback=finish' not in main_text:
        fail("Confirmation popup DONE button is missing")
    methods = class_methods(main_text)
    confirm = methods.get(("AlarmEditScreen", "_show_alarm_confirmation"))
    if confirm is None:
        fail("AlarmEditScreen confirmation method missing")
    confirm_text = source_for_node(main_text, confirm)
    cancel_start = confirm_text.find("def cancel_review")
    cancel_text = confirm_text[cancel_start:] if cancel_start >= 0 else ""
    if "_commit_pending_confirmation" in cancel_text:
        fail("CANCEL must never call the alarm commit/schedule path")
    print("PASS: confirmation commits on DONE; Back cancellation remains available")

    if "def _seconds_to_next_wall_second():" not in main_text:
        fail("Wall-second alignment helper missing")
    home = methods.get(("HomeScreen", "_wall_clock_tick"))
    analog = methods.get(("AnalogClock", "_tick"))
    if home is None or "Clock.schedule_once" not in source_for_node(main_text, home):
        fail("Home countdown is not re-aligned to wall-clock seconds")
    if analog is None or "Clock.schedule_once" not in source_for_node(main_text, analog):
        fail("Analog clock is not re-aligned to wall-clock seconds")
    helper = extract_functions(main_text, {"_seconds_to_next_wall_second"}, {"datetime": datetime})
    delay = helper["_seconds_to_next_wall_second"]()
    if not 0 < delay <= 1:
        fail("Wall-second delay must be in (0, 1]")
    print("PASS: analog clock and countdown schedule from current wall time")

    wheel_methods = class_methods(module_text)
    wheel_init = wheel_methods.get(("SpinnerWheel", "__init__"))
    wheel_down = wheel_methods.get(("SpinnerWheel", "on_touch_down"))
    wheel_move = wheel_methods.get(("SpinnerWheel", "on_touch_move"))
    wheel_up = wheel_methods.get(("SpinnerWheel", "on_touch_up"))
    player = next((n for n in module_tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "_play_spinner_tick"), None)
    loader = next((n for n in module_tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "_load_spinner_tick"), None)
    if not all((wheel_init, wheel_down, wheel_move, wheel_up, player, loader)):
        fail("Spinner lifecycle/touch/audio helpers missing")
    play_text = source_for_node(module_text, player)
    load_text = source_for_node(module_text, loader)
    if any(marker in play_text for marker in ("_load_spinner_tick()", "SoundLoader.load", "_spinner_tick_path()")):
        fail("Touch-time spinner playback still performs synchronous loading or file work")
    if "_schedule_spinner_tick_load()" not in play_text or "_schedule_spinner_tick_load()" not in source_for_node(module_text, wheel_init):
        fail("Spinner sound preload is not scheduled before wheel gestures")
    if load_text.count("SoundLoader.load(") != 1 or "Clock.schedule_once(_load_spinner_tick" not in load_text:
        fail("Spinner voices must load one per scheduled callback")
    if "_cancel_motion()" not in source_for_node(module_text, wheel_down):
        fail("Fresh pointer input does not clear stale touch/animation state")
    if "_cancel_motion()" not in source_for_node(module_text, wheel_move) or "_cancel_motion()" not in source_for_node(module_text, wheel_up):
        fail("Spinner lost-grab recovery is missing")
    print("PASS: spinner tick load is deferred and stale grabs are recovered")

    if any(marker not in kv_text for marker in ("<HomeScreen>:", "<AlarmEditScreen>:", "<AlarmRingScreen>:")):
        fail("KV screen definitions are incomplete")
    if "TimePickerPopup" in main_text:
        fail("Orphaned legacy TimePickerPopup reference remains")
    print("PASS: active screen boundaries and obsolete picker handlers")
    print("ALL STATIC REGRESSION CHECKS PASSED; device tests are still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
