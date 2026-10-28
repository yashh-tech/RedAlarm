#!/usr/bin/env python3
"""Static regression checks for the RedAlarm unified editor and widget patch."""
from __future__ import annotations
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("FAIL: " + message)

def main() -> int:
    module_path = ROOT / "redalarm_timepicker.py"
    main_path = ROOT / "main.py"
    provider_path = ROOT / "android_src/org/yashtech/redalarm/RedAlarmClockWidgetProvider.java"
    widget_layout_path = ROOT / "android_src/res/layout/redalarm_clock_widget.xml"
    widget_info_path = ROOT / "android_src/res/xml/redalarm_clock_widget_info.xml"
    manifest_hook_path = ROOT / "java_src/manifest_hook.py"
    for path in (module_path, main_path, provider_path, widget_layout_path,
                 widget_info_path, manifest_hook_path):
        require(path.is_file(), "missing required file: " + str(path.relative_to(ROOT)))

    module = module_path.read_text(encoding="utf-8")
    main_source = main_path.read_text(encoding="utf-8")
    compile(module, str(module_path), "exec")
    compile(main_source, str(main_path), "exec")
    ast.parse(module)
    ast.parse(main_source)
    for marker in (
        "self.fling_velocity_window = 0.12", "self.min_fling_velocity = 1.15",
        "self.max_fling_velocity = 28.0", "math.exp(-friction * dt)",
        "class AlarmEditorMainPage(BoxLayout):", "class SettingOptionRow(BoxLayout):",
        "class AlarmAppSettingsPage(BoxLayout):",
        "class DurationSelectionPage(BoxLayout):", "class VibrationSelectionPage(BoxLayout):",
        "self.settings_page = AlarmAppSettingsPage(editor, editor.cancel_edit)",
        "self.editor.ui.show_snooze()", "self.editor.ui.show_auto_dismiss()",
        "self.editor.ui.show_vibration()", "class SnoozeIcon(Widget):",
        "class AutoDismissIcon(Widget):",
        "class SoundSelectionPage(BoxLayout):",
        "foreground_color=(1, 1, 1, 1)",
        "def _get_line_options(self):",
        "options[\"color\"] = LABEL_WHITE",
        "USE SELECTED SOUND",
        "self.editor.preview_sound(path=p, duration=8.0)",
    ):
        require(marker in module, "time-picker/editor marker missing: " + marker)
    for marker in (
        "sound_enabled = BooleanProperty(True)", "snooze_enabled = BooleanProperty(True)",
        "auto_dismiss_enabled = BooleanProperty(True)", '"sound_enabled": bool(self.sound_enabled)',
        '"snooze_enabled": bool(self.snooze_enabled)',
        '"auto_dismiss_enabled": bool(self.auto_dismiss_enabled)',
    ):
        require(marker in main_source, "setting persistence marker missing: " + marker)
    require("def start_selection(self):" in main_source,
            "explicit Select action must open selection mode with zero selected alarms")
    require('text: "CANCEL" if root.selection_mode else "SELECT"' in (ROOT / "alarm.kv").read_text(encoding="utf-8"),
            "alarm-list SELECT/CANCEL control is missing")
    kv_source = (ROOT / "alarm.kv").read_text(encoding="utf-8")
    require('size: dp(136), dp(48)' in kv_source and
            'on_press: root.cancel_selection() if root.selection_mode else root.start_selection()' in kv_source,
            "SELECT/CANCEL touch target is too small or waits for release")
    require("selection_toolbar_height=dp(124)" in main_source,
            "selection toolbar height is too small for its action row")
    for tone in ('("Pulse",', '("Double Alert",', '("Rising Tone",', '("Digital",'):
        require(tone in main_source, "built-in tone missing: " + tone)
    print("PASS: Python syntax, fling settings, editor navigation, and persisted toggles")
    for marker in ("def _animate_selection_toolbar", "selection_reveal = NumericProperty",
                   "neon_glow = NumericProperty", "def copy_selected", "def confirm_delete_selected"):
        require(marker in main_source, "animated multi-select marker missing: " + marker)

    provider = provider_path.read_text(encoding="utf-8")
    layout = widget_layout_path.read_text(encoding="utf-8")
    info = widget_info_path.read_text(encoding="utf-8")
    hook = manifest_hook_path.read_text(encoding="utf-8")
    require("RedAlarmWidgetData.alarmTimeText(context, false)" in provider
            and "RedAlarmWidgetData.alarmTimeText(context, true)" in provider
            and "RedAlarmWidgetData.alarmLabelText(context, false)" in provider
            and "RedAlarmWidgetData.alarmLabelText(context, true)" in provider,
            "combined widget must bind the next two alarm times and labels")
    for marker in ("has_second_alarm", "second_alarm_at", "second_alarm_label", "alarmTimeText", "alarmLabelText"):
        require(marker in (ROOT / "android_src/org/yashtech/redalarm/RedAlarmWidgetData.java").read_text(encoding="utf-8"),
                "two-alarm widget data marker missing: " + marker)
    for marker in ("@+id/redalarm_next_alarm_text", "@+id/redalarm_next_alarm_label",
                   "@+id/redalarm_second_alarm_text", "@+id/redalarm_second_alarm_label"):
        require(marker in layout, "widget layout is missing an alarm row view: " + marker)
    require("AnalogClock" in layout and "TextClock" in layout
            and 'android:format12Hour="h:mm a"' in layout
            and 'android:format24Hour="h:mm a"' in layout,
            "widget must show a live analog/digital clock in 12-hour time")
    require('android:minWidth="220dp"' in info,
            "combined widget minimum width may exceed a typical launcher grid")
    require('android:targetCellWidth="3"' in info and 'android:targetCellHeight="2"' in info
            and 'android:minHeight="120dp"' in info,
            "combined widget must be configured as an aligned 3x2 widget")
    require('android:previewImage="@drawable/redalarm_widget_preview"' in info
            and 'android:previewLayout="@layout/redalarm_clock_widget"' in info,
            "widget picker preview is not configured")
    require("RedAlarmNextAlarmWidgetProvider" not in hook,
            "obsolete separate upcoming-alarm widget is still registered")
    require(not (ROOT / "android_src/org/yashtech/redalarm/RedAlarmNextAlarmWidgetProvider.java").exists(),
            "obsolete separate widget Java provider still exists")
    require(not (ROOT / "android_src/res/layout/redalarm_next_alarm_widget.xml").exists(),
            "obsolete separate widget layout still exists")
    print("PASS: single combined live-clock/upcoming-alarm 3x1 widget and launcher preview")
    print("Static checks passed. Android build and touch behavior still need device testing.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
