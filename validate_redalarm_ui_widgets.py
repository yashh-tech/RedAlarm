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
        "class DurationSelectionPage(BoxLayout):", "class VibrationSelectionPage(BoxLayout):",
        "self.settings_page = AlarmScreenshotEditorPage(editor, editor.cancel_edit)",
        "self.editor.ui.show_snooze()", "self.editor.ui.show_auto_dismiss()",
        "self.editor.ui.show_vibration()", "class SnoozeIcon(Widget):",
        "class AutoDismissIcon(Widget):",
    ):
        require(marker in module, "time-picker/editor marker missing: " + marker)
    for marker in (
        "sound_enabled = BooleanProperty(True)", "snooze_enabled = BooleanProperty(True)",
        "auto_dismiss_enabled = BooleanProperty(True)", '"sound_enabled": bool(self.sound_enabled)',
        '"snooze_enabled": bool(self.snooze_enabled)',
        '"auto_dismiss_enabled": bool(self.auto_dismiss_enabled)',
    ):
        require(marker in main_source, "setting persistence marker missing: " + marker)
    print("PASS: Python syntax, fling settings, editor navigation, and persisted toggles")

    provider = provider_path.read_text(encoding="utf-8")
    layout = widget_layout_path.read_text(encoding="utf-8")
    info = widget_info_path.read_text(encoding="utf-8")
    hook = manifest_hook_path.read_text(encoding="utf-8")
    require("RedAlarmWidgetData.upcomingText(context)" in provider,
            "combined widget does not display the upcoming alarm")
    require("AnalogClock" in layout and "TextClock" in layout
            and 'android:format12Hour="h:mm a"' in layout
            and 'android:format24Hour="h:mm a"' in layout,
            "widget must show a live analog/digital clock in 12-hour time")
    require('android:targetCellWidth="3"' in info and 'android:targetCellHeight="1"' in info,
            "combined widget is not configured as a 3x1 widget")
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
