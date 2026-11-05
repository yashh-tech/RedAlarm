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
    widget_layout_paths = {
        name: ROOT / ("android_src/res/layout/redalarm_widget_%s.xml" % name)
        for name in ("large", "wide", "square")
    }
    widget_info_path = ROOT / "android_src/res/xml/redalarm_clock_widget_info.xml"
    manifest_hook_path = ROOT / "java_src/manifest_hook.py"
    for path in (module_path, main_path, provider_path, *widget_layout_paths.values(),
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
        "LABEL_WHITE = (1, 1, 1, 1)",
        "def _get_line_options(self):",
        "options[\"color\"] = LABEL_WHITE",
        "USE SELECTED SOUND",
        "self.editor.toggle_preview_sound(path=path, duration=30.0)",
    ):
        require(marker in module, "time-picker/editor marker missing: " + marker)
    for marker in (
        "sound_enabled = BooleanProperty(True)", "snooze_enabled = BooleanProperty(True)",
        "auto_dismiss_enabled = BooleanProperty(True)", '"sound_enabled": bool(self.sound_enabled)',
        '"snooze_enabled": bool(self.snooze_enabled)',
        '"auto_dismiss_enabled": bool(self.auto_dismiss_enabled or self.auto_snooze_enabled)',
    ):
        require(marker in main_source, "setting persistence marker missing: " + marker)
    require("def start_selection(self):" in main_source,
            "explicit Select action must open selection mode with zero selected alarms")
    require("class AutoSnoozeSettingsPage(BoxLayout):" in module
            and "def show_auto_snooze(self):" in module
            and "self.editor.auto_dismiss_enabled = True" in module,
            "Auto Snooze must be a separate page with its own ring duration, interval and repeat limit")
    manual_page = module.split("class SnoozeSettingsPage(BoxLayout):", 1)[1].split(
        "class AutoSnoozeSettingsPage(BoxLayout):", 1
    )[0]
    auto_page = module.split("class AutoSnoozeSettingsPage(BoxLayout):", 1)[1].split(
        "class SoundSelectionPage(BoxLayout):", 1
    )[0]
    require("MANUAL SNOOZE DURATION" in manual_page and "MAX SNOOZES" in manual_page
            and "AUTO SNOOZE" not in manual_page,
            "Manual Snooze page must have its own delay and maximum count, separate from Auto Snooze")
    require("RING DURATION" in auto_page and "REPEAT AFTER" in auto_page
            and "MAX AUTO REPEATS" in auto_page,
            "Auto Snooze page must have ring duration, silent interval and independent maximum")
    require("self.action.bind(on_release=lambda *_: on_open())" in module
            and "self.auto_snooze_row, self.auto_snooze_switch" in module
            and "self._open_auto_snooze_settings" in module,
            "Setting rows must open their menu from the full action bar, with a separate toggle")
    require("snooze_max_count" in main_source and "MAX SNOOZES" in module
            and "auto_snooze_max_count" in main_source,
            "Manual and automatic snooze limits must persist independently")
    require('or alarm.get("auto_snooze_enabled", False)' in main_source
            and 'bool(self.auto_dismiss_enabled or self.auto_snooze_enabled)' in main_source,
            "Loading/saving an Auto Snooze alarm must also enable Auto-Dismiss")
    require('text: "CANCEL" if root.selection_mode else "SELECT"' in (ROOT / "alarm.kv").read_text(encoding="utf-8"),
            "alarm-list SELECT/CANCEL control is missing")
    kv_source = (ROOT / "alarm.kv").read_text(encoding="utf-8")
    require('size_hint: 1, None' in kv_source and
            'on_release: root.toggle_selection_mode()' in kv_source and
            "def toggle_selection_mode(self):" in main_source,
            "SELECT/CANCEL tap handling is not wired to the large touch target")
    require('id: alarms_scroll' in kv_source and
            'def _capture_list_scroll_offset(self):' in main_source and
            'width: dp(30)' in kv_source and
            'opacity: root.selection_reveal' in kv_source,
            "Alarm list must keep its scroll position and row width stable")
    require("percent_text = StringProperty" in module and
            "self.editor.set_alarm_volume(value)" in module and
            "load_and_play(path, loop=False, volume=1.0, use_media_volume=True)" in main_source,
            "Alarm-volume slider and media-stream sound preview wiring are missing")
    require("def toggle_preview_sound(" in main_source and
            "def set_preview_playing(" in module and
            "Local file selected." in module and
            "preview_button.set_playing" in main_source,
            "Local music selection and animated Play/Stop controls are missing")
    require("def repeat_summary_text(days_selected):" in module
            and '"Every weekday"' in module and '"Every weekend"' in module
            and "self.editor.bind(days_selected=lambda *_: self.refresh_repeat_summary())" in module
            and "Once if no days are selected" not in module,
            "Edit Alarm must show a live repeat summary under the label")
    root_manager_text = main_source.split("class RootManager(ScreenManager):", 1)[1].split(
        "# ======================================================================\n# 5. APP", 1
    )[0]
    require("def on_touch_down(" not in root_manager_text and "def on_touch_up(" not in root_manager_text,
            "Global horizontal gestures should not intercept app navigation")
    require("selection_toolbar_height=dp(124)" in main_source,
            "selection toolbar height is too small for its action row")
    for tone in ('("Classic Beep",', '("Soft Breeze",', '("Gentle Chime",',
                 '("Pop Alert",', '("Double Pop",'):
        require(tone in main_source, "built-in tone missing: " + tone)
    print("PASS: Python syntax, fling settings, editor navigation, and persisted toggles")
    require('AudioAttributes.USAGE_MEDIA if use_media_volume else AudioAttributes.USAGE_ALARM' in main_source
            and 'load_and_play(path, loop=False, volume=1.0, use_media_volume=True)' in main_source,
            "sound previews must use media volume while real alarms retain alarm volume")
    require("effect_cls=None" not in module and "LABEL_WHITE = (1, 1, 1, 1)" in module,
            "ScrollView effect_cls must not be None; pure-white alarm-label text must remain configured")
    for marker in ("def _animate_selection_toolbar", "selection_reveal = NumericProperty",
                   "neon_glow = NumericProperty", "def copy_selected", "def confirm_delete_selected"):
        require(marker in main_source, "animated multi-select marker missing: " + marker)

    splash_source = (ROOT / "splash_screen.py").read_text(encoding="utf-8")
    require("def _finish_startup_services" in main_source
            and "def _show_startup_failure" in main_source
            and "def _record_startup_exception" in main_source,
            "startup must show the app before non-UI services and report initialization failures")
    require("def show_startup_error" in splash_source
            and "Opening RedAlarm..." in splash_source
            and "Ready!" not in splash_source,
            "splash must not report Ready before the actual app is displayed")

    provider = provider_path.read_text(encoding="utf-8")
    layouts = {name: path.read_text(encoding="utf-8") for name, path in widget_layout_paths.items()}
    info = widget_info_path.read_text(encoding="utf-8")
    hook = manifest_hook_path.read_text(encoding="utf-8")
    data_source = (ROOT / "android_src/org/yashtech/redalarm/RedAlarmWidgetData.java").read_text(encoding="utf-8")
    for marker in ("R.layout.redalarm_widget_large", "R.layout.redalarm_widget_wide",
                   "R.layout.redalarm_widget_square", "new RemoteViews(bySize)",
                   "onAppWidgetOptionsChanged", "RedAlarmWidgetData.countdownText(context)",
                   "RedAlarmWidgetData.bindLiveCountdown(context, views, R.id.ra_countdown_live)",
                   "RedAlarmWidgetData.alarmTimeText(context, true)"):
        require(marker in provider, "adaptive widget provider marker missing: " + marker)
    for marker in ("has_next_alarm", "next_alarm_at", "next_alarm_label", "next_alarm_days",
                   "alarmTimeText", "alarmLabelText", "alarmDaysText", "countdownText",
                   "bindLiveCountdown", "setChronometerCountDown"):
        require(marker in data_source, "widget data marker missing: " + marker)
    require('"next_alarm_days"' in main_source and "def widget_days_mask(days):" in main_source,
            "Python must publish the alarm repeat days for the widget")
    expected_ids = {
        "large": ("ra_clock_time", "ra_next_time", "ra_next_label", "ra_next_days",
                  "ra_second_time", "ra_second_label", "ra_second_days"),
        "wide": ("ra_clock_time", "ra_next_time", "ra_next_days"),
        "square": ("ra_countdown", "ra_next_time", "ra_next_label", "ra_next_days"),
    }
    for name, ids in expected_ids.items():
        require('android:id="@+id/ra_widget_root"' in layouts[name],
                name + " widget layout is missing its tap target")
        for view_id in ids:
            require('@+id/%s"' % view_id in layouts[name],
                    "%s widget layout is missing %s" % (name, view_id))
        require("<View" not in layouts[name], name + " widget uses a View, which RemoteViews rejects")
    require('android:targetCellWidth="4"' in info and 'android:targetCellHeight="2"' in info
            and 'android:minResizeWidth="100dp"' in info,
            "widget must default to 4x2 and not shrink below two cells wide")
    require(not (ROOT / "android_src/res/layout/redalarm_clock_widget.xml").exists(),
            "old 3x1 widget layout still exists")
    require("RedAlarmNextAlarmWidgetProvider" not in hook,
            "obsolete separate upcoming-alarm widget is still registered")
    require(not (ROOT / "android_src/org/yashtech/redalarm/RedAlarmNextAlarmWidgetProvider.java").exists(),
            "obsolete separate widget Java provider still exists")
    require(not (ROOT / "android_src/res/layout/redalarm_next_alarm_widget.xml").exists(),
            "obsolete separate widget layout still exists")
    print("PASS: adaptive 4x2 / 4x1 / 2x2 widget and launcher preview")
    print("Static checks passed. Android build and touch behavior still need device testing.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
