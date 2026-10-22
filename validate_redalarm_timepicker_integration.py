#!/usr/bin/env python3
"""Standard-library validation for an integrated RedAlarm time-picker checkout.

Run from the RedAlarm repository root after apply_redalarm_timepicker_integration.py.
This checks Python syntax, duration helpers/presets, and critical wiring markers.
It deliberately does not import Kivy or launch the UI.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path.cwd().resolve()
MAIN = ROOT / "main.py"
KV = ROOT / "alarm.kv"
MODULE = ROOT / "redalarm_timepicker.py"


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def extract_functions(source: str, names: set[str]) -> dict[str, object]:
    tree = ast.parse(source)
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in names]
    found = {node.name for node in selected}
    if found != names:
        fail("Expected helpers missing: {}".format(sorted(names - found)))
    mini = ast.Module(body=selected, type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(mini, "<duration_helpers>", "exec"), namespace)
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


def main() -> int:
    for path in (MAIN, KV, MODULE):
        if not path.is_file():
            fail("Missing required file: {}".format(path.name))

    main_text = MAIN.read_text(encoding="utf-8")
    kv_text = KV.read_text(encoding="utf-8")
    module_text = MODULE.read_text(encoding="utf-8")

    # Compile all Python files without importing Android/Kivy dependencies.
    compile(main_text, str(MAIN), "exec")
    compile(module_text, str(MODULE), "exec")
    print("PASS: main.py and redalarm_timepicker.py compile")

    namespace = extract_functions(module_text, {"format_duration", "_parse_duration"})
    fmt = namespace["format_duration"]
    parse = namespace["_parse_duration"]
    duration_cases = {
        3: "3 sec", 30: "30 sec", 60: "1 min", 600: "10 min",
        900: "15 min", 1800: "30 min", 3600: "1 Hr",
        4500: "1.25 Hr", 5400: "1.5 Hr", 6300: "1.75 Hr",
        7200: "2 Hr", 10800: "3 Hr",
    }
    for seconds, expected in duration_cases.items():
        actual = fmt(seconds)
        if actual != expected:
            fail("format_duration({}) returned {!r}, expected {!r}".format(seconds, actual, expected))
    parse_cases = {"3s": 3, "30s": 30, "5m": 300, "1h": 3600,
                   "1.5h": 5400, "3h": 10800, "5": 300}
    for text, expected in parse_cases.items():
        actual = parse(text, 300)
        if actual != expected:
            fail("_parse_duration({!r}) returned {}, expected {}".format(text, actual, expected))
    print("PASS: duration labels and custom parser cases")

    presets = class_assign_value(module_text, "DurationRow", "PRESETS")
    if presets != sorted(set(presets)):
        fail("DurationRow.PRESETS must be unique and sorted for +/- stepping")
    if presets[0] != 3 or presets[-1] != 10800:
        fail("Duration presets must span 3 seconds through 3 Hr")
    for required in (3, 5, 10, 15, 30, 60, 600, 900, 1800, 2700, 10800):
        if required not in presets:
            fail("Required duration preset {} missing".format(required))
    if any(value > 10800 for value in presets):
        fail("Duration preset exceeds 3 Hr cap")
    print("PASS: timer preset order and 3 Hr hard cap")

    required_main = [
        "from redalarm_timepicker import AlarmEditorUI, RoundedActionButton, RoundedPanel, format_duration",
        "class AlarmEditScreen(Screen):",
        "self._show_alarm_confirmation(alarm, trigger_dt)",
        "home.show_toast(message)",
        "def show_toast(self, message):",
        "def load_and_play(path, loop=True, volume=1.0):",
        "load_and_play(path, loop=True, volume=ring_volume)",
        '"auto_dismiss_sec": dismiss_seconds',
        '"snooze_sec": snooze_seconds',
    ]
    for marker in required_main:
        if marker not in main_text:
            fail("main.py wiring marker missing: {}".format(marker))
    if "self.ui.picker_page.set_editing(" in main_text:
        fail("Stale TimePickerPage.set_editing call found")
    if "self.ids.dismiss_min" in main_text or "self.ids.input_hour" in main_text:
        fail("Legacy KV editor IDs remain in the replacement editor")
    print("PASS: picker -> settings -> save/confirmation -> home toast wiring")

    if 'formatter=lambda v: "{:02d}".format(v)' not in module_text:
        fail("Minute wheel is not formatted with leading zeroes")
    if "from kivy.core.audio import SoundLoader" not in module_text:
        fail("Spinner tick SoundLoader import missing")
    if "class AlarmAppSettingsPage(BoxLayout):" not in module_text:
        fail("Settings page class missing")
    if "class TimePickerPage(BoxLayout):" not in module_text:
        fail("Time picker page class missing")
    if "transparent.png" in module_text:
        fail("Invalid transparent.png Kivy texture reference remains")
    if "<AlarmEditScreen>:" not in kv_text or "<AlarmRingScreen>:" not in kv_text:
        fail("KV screen boundaries missing")
    print("PASS: picker/settings classes, icons/audio dependency, minute labels and KV screen boundaries")
    print("ALL STATIC CHECKS PASSED. Run the app locally to verify touch, audio and visual layout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
