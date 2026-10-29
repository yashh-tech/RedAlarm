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
    if ('AudioAttributes.USAGE_MEDIA if use_media_volume else AudioAttributes.USAGE_ALARM' not in main_text
            or 'load_and_play(path, loop=False, volume=1.0, use_media_volume=True)' not in main_text):
        fail("Sound preview must use full player gain and the device media-volume stream without changing alarm ringing")
    if any(name not in main_text for name in ("Soft Chime", "Morning Rise", "Triple Pulse", "Deep Beacon", "Bright Wake")):
        fail("One or more original built-in preview tones are missing")
    if module_text.count("effect_cls=None") < 2:
        fail("Edit Alarm and Sound page must disable overscroll effects")
    if 'LABEL_WHITE = (1, 1, 1, 1)' not in module_text:
        fail("Alarm-label text must use pure white")
    if "AlarmContextMenu(" in main_text or "     def _fire_long_press(self, touch):" in main_text:
        fail("A malformed/undefined long-press context-menu regression remains")
    print("PASS: media-volume sound previews, built-in tones, no overscroll, readable label, and long-press syntax")

    notif_start = main_text.find("def android_show_next_alarm_notification")
    notif_end = main_text.find("def android_cancel_next_alarm_notification", notif_start)
    if notif_start < 0 or notif_end < 0:
        fail("Persistent next-alarm notification builder missing")
    notif_text = main_text[notif_start:notif_end]
    if 'builder.setContentTitle(JString("Next alarm on " + alarm_time))' not in notif_text:
        fail("Next-alarm notification title must be minimal and show the alarm time")
    if "builder.setUsesChronometer(True)" not in notif_text or "builder.setChronometerCountDown(True)" not in notif_text:
        fail("Persistent next-alarm notification must retain its system countdown")
    if "Notification$BigTextStyle" in notif_text or "builder.setSubText(" in notif_text:
        fail("Next-alarm notification must not return to the tall expanded text layout")
    print("PASS: minimal next-alarm notification retains Android countdown")

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
    if presets != sorted(set(presets)) or presets[0] != 1 or presets[-1] != 3600:
        fail("DurationRow.PRESETS must be unique, sorted, bounded by 1 sec/60 min")
    # Auto-dismiss is allowed down to 1 second; SnoozeRow separately enforces 3 seconds.
    if any(value not in presets for value in (1, 3, 5, 10, 15, 30, 60, 600, 900, 1800, 2700, 3600)):
        fail("A required duration preset is missing")
    print("PASS: duration labels, parser, ordered presets and 60 min cap")

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
    analog_init = methods.get(("AnalogClock", "__init__"))
    if home is None or "Clock.schedule_once" not in source_for_node(main_text, home):
        fail("Home countdown is not re-aligned to wall-clock seconds")
    if (analog is None or analog_init is None
            or "Clock.schedule_interval(self._tick, 1.0 / 30.0)" not in source_for_node(main_text, analog_init)
            or "return True" not in source_for_node(main_text, analog)):
        fail("Analog clock must redraw smoothly from wall time")
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
    physics_markers = (
        "self.fling_velocity_window = 0.12",
        "self.min_fling_velocity = 1.15",
        "self.max_fling_velocity = 28.0",
        "math.exp(-friction * dt)",
        "self._record_touch_sample(now)",
        "self._release_velocity(now)",
        "class SnoozeIcon(Widget):",
        "class AutoDismissIcon(Widget):",
        "icon=SnoozeIcon",
        "icon=AutoDismissIcon",
    )
    for marker in physics_markers:
        if marker not in module_text:
            fail("Fling physics or setting icon wiring missing: " + marker)
    print("PASS: recent-velocity fling, exponential friction, snapping, and setting icons")

    if any(marker not in kv_text for marker in ("<HomeScreen>:", "<AlarmEditScreen>:", "<AlarmRingScreen>:")):
        fail("KV screen definitions are incomplete")
    if "TimePickerPopup" in main_text:
        fail("Orphaned legacy TimePickerPopup reference remains")
    if "class AlarmSelectionIndicator(ButtonBehavior, Widget):" not in main_text:
        fail("Alarm-list selection checkbox widget is missing")
    for marker in ("def begin_selection(", "def toggle_selection(", "def select_all_selected(", "def copy_selected(", "def confirm_delete_selected("):
        if marker not in main_text:
            fail("Alarm-list multi-select action is missing: " + marker)
    if (
        "AlarmSelectionIndicator:" not in kv_text
        or not any(marker in kv_text for marker in ('text: "Copy"', 'text: "COPY"'))
        or "root.copy_selected()" not in kv_text
        or "root.confirm_delete_selected()" not in kv_text
    ):
        fail("Alarm-list long-press toolbar wiring is incomplete")
    if "MAX_WORDS = 25" not in module_text or "Enter label (optional)" not in module_text:
        fail("Editable, 25-word alarm-label input is missing")
    indicator = main_text.split("class AlarmSelectionIndicator(ButtonBehavior, Widget):", 1)[1].split("class AlarmInfoButton", 1)[0]
    if "toggle_selection(self.row.alarm_id)" not in indicator:
        fail("Tapping the row checkbox must toggle selection directly")
    row_class_text = main_text.split("class AlarmRow(BoxLayout):", 1)[1].split("class AlarmListScreen", 1)[0]
    if "checkbox_touched" not in row_class_text:
        fail("Tapping/holding a checkbox must not conflict with the row long-press timer")
    legacy_checkbox_markers = ("width: dp(30) if root.selection_mode else 0" in kv_text
                              and "opacity: 1 if root.selection_mode else 0" in kv_text)
    animated_checkbox_markers = ("width: dp(30) * root.selection_reveal" in kv_text
                                and "opacity: root.selection_reveal" in kv_text
                                and "selection_reveal = NumericProperty(0.0)" in main_text)
    if not (legacy_checkbox_markers or animated_checkbox_markers):
        fail("Alarm-row checkboxes should appear only in selection mode")
    legacy_toolbar_markers = ("height: dp(62) if root.selection_mode else 0" in kv_text
                              and "disabled: not root.selection_mode" in kv_text)
    animated_toolbar_markers = ("height: root.selection_toolbar_height" in kv_text
                                and "opacity: root.selection_toolbar_opacity" in kv_text
                                and "def _animate_selection_toolbar" in main_text)
    if not (legacy_toolbar_markers or animated_toolbar_markers):
        fail("Alarm-list bulk action bar should be hidden until long-press selection")
    if 'on_release: root.on_delete_press()' not in kv_text or "def confirm_delete(self, alarm_id):" not in main_text:
        fail("Individual alarm delete with confirmation must remain available")
    if 'kwargs["input_type"] = "text"' not in module_text or 'kwargs["keyboard_suggestions"] = True' not in module_text:
        fail("Label input must request a text keyboard with suggestions")
    if not (
        'kwargs["disabled_foreground_color"] = (1, 1, 1, 1)' in module_text
        or ('kwargs["disabled_foreground_color"] = LABEL_WHITE' in module_text
            and 'LABEL_WHITE = (1, 1, 1, 1)' in module_text)
    ):
        fail("Label input disabled text must remain readable")
    if "def _get_line_options(self):" not in module_text or 'options["color"] = LABEL_WHITE' not in module_text:
        fail("Alarm label must force #F9F9F9 on Kivy's rendered text lines")
    if 'text: "CANCEL" if root.selection_mode else "SELECT"' not in kv_text or "def start_selection(self):" not in main_text:
        fail("Alarm list must provide an explicit Select control that opens empty selection mode")
    if ('size: dp(136), dp(48)' not in kv_text
            or 'on_release: root.toggle_selection_mode()' not in kv_text
            or "def toggle_selection_mode(self):" not in main_text):
        fail("Select control must toggle selection mode on a completed tap")
    if ("percent_text = StringProperty" not in module_text
            or "def set_alarm_volume(self, value):" not in main_text
            or "load_and_play(path, loop=False, volume=1.0, use_media_volume=True)" not in main_text):
        fail("Alarm-volume slider and media-stream sound preview wiring are missing")
    root_manager_text = main_text.split("class RootManager(ScreenManager):", 1)[1].split(
        "# ======================================================================\n# 5. APP", 1
    )[0]
    if "def on_touch_down(" in root_manager_text or "def on_touch_up(" in root_manager_text:
        fail("Root-level gestures must not intercept navigation/touch controls")
    if "selection_toolbar_height=dp(124)" not in main_text:
        fail("Selection toolbar must reserve enough height for its action buttons")
    print("PASS: long-press checkboxes/action bar, individual delete confirmation, and bulk actions")
    print("PASS: readable label text, text keyboard, suggestions, and 25-word cap")
    if 'size: dp(24), dp(24)' not in kv_text or 'anchor_y: "center"' not in kv_text:
        fail("Alarm selection checkbox must be a fixed-size, vertically centred control")
    ring_activity_path = ROOT / "android_src" / "org" / "yashtech" / "redalarm" / "RedAlarmRingActivity.java"
    ring_service_path = ROOT / "android_src" / "org" / "yashtech" / "redalarm" / "RedAlarmRingingService.java"
    if not ring_activity_path.is_file() or not ring_service_path.is_file():
        fail("Native ringing activity/service is missing")
    ring_activity_text = ring_activity_path.read_text(encoding="utf-8")
    ring_service_text = ring_service_path.read_text(encoding="utf-8")
    if 'countdownTitle.setText("AUTO-DISMISS IN")' not in ring_activity_text or 'countdownValue.setText' not in ring_activity_text:
        fail("Native lock-screen alarm must display an auto-dismiss countdown")
    if 'ring_started_elapsed:' not in ring_service_text or 'ring_duration_sec:' not in ring_service_text:
        fail("Native ringing service must save the visible countdown deadline")
    print("PASS: alarm checkboxes use a fixed-size centred layout")
    print("PASS: native lock-screen ring screen displays the auto-dismiss countdown")
    print("PASS: active screen boundaries and obsolete picker handlers")
    print("ALL STATIC REGRESSION CHECKS PASSED; device tests are still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
