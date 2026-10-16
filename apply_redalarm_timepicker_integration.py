#!/usr/bin/env python3
"""Safely integrate the RedAlarm two-page premium time picker into the app.

Run this from the root of a clean local checkout of branch `yashh-tech-patch-2`.
It backs up main.py and alarm.kv before writing and never commits or pushes.
"""
from __future__ import annotations

import datetime
import pathlib
import shutil
import subprocess
import sys

EXPECTED_BRANCH = "yashh-tech-patch-2"
ROOT = pathlib.Path.cwd().resolve()
MAIN = ROOT / "main.py"
KV = ROOT / "alarm.kv"
MODULE_SOURCE = pathlib.Path(__file__).resolve().with_name("redalarm_timepicker_payload.py")
MODULE_DEST = ROOT / "redalarm_timepicker.py"


def run_git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True,
                           capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("git {} failed:\n{}{}".format(
            " ".join(args), result.stdout, result.stderr))
    return result.stdout.strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError("Safety check for {!r}: expected one match, found {}. No files changed.".format(label, count))
    return text.replace(old, new, 1)


def replace_region(text: str, start_marker: str, end_marker: str,
                   replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError("Could not find start marker for {}. No files changed.".format(label))
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError("Could not find end marker for {}. No files changed.".format(label))
    return text[:start] + replacement.rstrip() + "\n\n\n" + text[end:]


NEW_EDITOR_CLASS = r'''class AlarmEditScreen(Screen):
    """Two-page alarm editor; existing persistence/scheduler APIs stay in main.py."""
    editing_id = StringProperty("")
    ampm = StringProperty("AM")
    days_selected = ListProperty([False] * 7)
    sound_path = StringProperty("")
    sound_name = StringProperty("Default beep")
    vibrate = BooleanProperty(False)
    volume = NumericProperty(0.80)
    auto_dismiss_sec = NumericProperty(300)
    snooze_sec = NumericProperty(300)
    error_message = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.time_state = {"hour": 7, "minute": 16, "ampm": "AM", "label": ""}
        self._return_screen = "home"
        self.ui = AlarmEditorUI(self, size_hint=(1, 1), pos=self.pos)
        self.add_widget(self.ui)
        self.label_input = self.ui.picker_page.label_input
        self.error_label = self.ui.settings_page.error_label

    def on_enter(self, *args):
        # Time picker is now an inline page, not the legacy button-grid popup.
        if self.ui.current != "picker":
            self.ui.show_picker()

    def load_alarm(self, alarm_id):
        """Load defaults or an existing record and reset the editor to page 1."""
        app = App.get_running_app()
        current_screen = getattr(app.root, "current", "home") if app.root else "home"
        self._return_screen = current_screen if current_screen in ("home", "list") else "home"
        self.error_message = ""
        self.error_label.text = ""
        self.ui.current = "picker"

        if alarm_id is None:
            self.editing_id = ""
            now = datetime.datetime.now()
            hour12 = now.hour % 12 or 12
            self.time_state.update({
                "hour": hour12,
                "minute": now.minute,
                "ampm": "PM" if now.hour >= 12 else "AM",
                "label": "",
            })
            self.days_selected = [False] * 7
            self.sound_path = ""
            self.sound_name = "Default beep"
            self.vibrate = False
            self.volume = 0.80
            self.auto_dismiss_sec = 300
            self.snooze_sec = 300
        else:
            alarm = App.get_running_app().store.get(alarm_id)
            if not alarm:
                return
            self.editing_id = alarm_id
            hour24 = int(alarm.get("hour", 7)) % 24
            self.time_state.update({
                "hour": hour24 % 12 or 12,
                "minute": int(alarm.get("minute", 0)) % 60,
                "ampm": "PM" if hour24 >= 12 else "AM",
                "label": str(alarm.get("label") or ""),
            })
            self.days_selected = list(alarm.get("days") or [False] * 7)
            if len(self.days_selected) != 7:
                self.days_selected = (self.days_selected + [False] * 7)[:7]
            self.sound_path = alarm.get("sound_path", "") or ""
            self.sound_name = alarm.get("sound_name") or "Default beep"
            self.vibrate = bool(alarm.get("vibrate", False))
            try:
                self.volume = max(0.0, min(1.0, float(alarm.get("volume", 0.80))))
            except (TypeError, ValueError):
                self.volume = 0.80
            self.auto_dismiss_sec = max(3, min(10800, int(alarm.get("auto_dismiss_sec", 300) or 300)))
            self.snooze_sec = max(3, min(10800, int(alarm.get("snooze_sec", 300) or 300)))

        self.ampm = self.time_state["ampm"]
        self.ui.picker_page.set_values(
            self.time_state["hour"], self.time_state["minute"],
            self.time_state["ampm"], self.time_state["label"],
        )
        self.ui.settings_page.refresh_from_editor()

    def _picker_state_changed(self, state):
        self.ampm = state.get("ampm", "AM")
        if hasattr(self, "ui"):
            self.ui.settings_page.refresh_time()

    def show_settings(self):
        self.ui.show_settings()

    def show_picker(self):
        self.ui.show_picker()

    def set_day(self, index, on):
        if not 0 <= index < 7:
            return
        if self.days_selected[index] != bool(on):
            days = list(self.days_selected)
            days[index] = bool(on)
            self.days_selected = days

    def _refresh_day_buttons(self):
        if hasattr(self, "ui"):
            self.ui.settings_page.refresh_days()

    def set_ampm(self, value):
        self.ampm = "PM" if str(value).upper() == "PM" else "AM"
        self.time_state["ampm"] = self.ampm
        self.ui.picker_page.set_values(
            self.time_state["hour"], self.time_state["minute"],
            self.ampm, self.time_state.get("label", ""),
        )
        self.ui.settings_page.refresh_time()

    def open_time_picker(self):
        # Kept as a compatibility hook for any old call site; now it shows page 1.
        self.ui.show_picker()

    def _apply_picked_time(self, hour12, minute, ampm):
        self.time_state.update({"hour": int(hour12), "minute": int(minute), "ampm": str(ampm).upper()})
        self.ampm = self.time_state["ampm"]
        self.ui.picker_page.set_values(hour12, minute, ampm, self.time_state.get("label", ""))
        self.ui.settings_page.refresh_time()

    def choose_sound(self):
        self.error_message = ""
        self.error_label.text = ""
        pick_ringtone_file(self._on_sound_picked, self._on_picker_error)

    def _on_picker_error(self, message):
        self.error_message = str(message)
        self.error_label.text = self.error_message

    def _on_sound_picked(self, path):
        if not path:
            return
        print("[RedAlarm] ringtone picked, raw path/URI:", path)
        name = None
        if ANDROID and path.startswith("content://"):
            try:
                name = android_get_display_name(path)
            except Exception as exc:
                print("[RedAlarm] display-name lookup failed:", exc)
            try:
                android_take_persistable_permission(path)
            except Exception as exc:
                print("[RedAlarm] could not persist URI permission:", exc)
            app = App.get_running_app()
            try:
                local_path = resolve_ringtone_for_playback(
                    path, app.ringtone_cache_dir, display_name=name
                )
            except Exception as exc:
                local_path = None
                print("[RedAlarm] immediate ringtone copy raised:", exc)
            if not local_path or not os.path.exists(local_path):
                print("[RedAlarm] immediate ringtone copy FAILED for", path)
                self._on_picker_error("Couldn't read that file — try picking it again.")
                return
            print("[RedAlarm] ringtone copied to durable local path:", local_path)
            self.sound_path = local_path
        else:
            self.sound_path = path
        self.sound_name = name or os.path.basename(path.replace("\\", "/"))
        self.error_message = ""
        self.error_label.text = ""
        self.ui.settings_page.refresh_sound()

    def preview_sound(self):
        self.error_message = ""
        self.error_label.text = ""
        app = App.get_running_app()
        path = self.sound_path or app.default_ringtone_path
        sound = load_and_play(path, loop=False, volume=float(self.volume))
        if sound is None:
            self._on_picker_error("Couldn't play that sound — try another file.")
            return

        def _stop(_dt):
            try:
                sound.stop()
                sound.unload()
            except Exception:
                pass
        Clock.schedule_once(_stop, 2.5)

    def cancel_edit(self):
        app = App.get_running_app()
        destination = self._return_screen if self._return_screen in ("home", "list") else "home"
        app.root.current = destination

    def delete_alarm(self):
        if not self.editing_id:
            return
        app = App.get_running_app()
        alarm = app.store.get(self.editing_id)
        if alarm:
            app.scheduler.cancel(alarm)
            app.scheduler.cancel_snooze(alarm)
        ring = app.root.get_screen("ring")
        if ring.alarm_id == self.editing_id:
            ring.finish(reason="delete")
        app.store.delete(self.editing_id)
        app.root.current = "list"

    def _fail(self, message):
        self.error_message = str(message)
        self.error_label.text = self.error_message
        if self.ui.current != "settings":
            self.ui.show_settings()

    @staticmethod
    def _next_day_label(trigger_dt, now=None):
        now = now or datetime.datetime.now()
        if trigger_dt.date() == now.date():
            return "Today"
        if trigger_dt.date() == now.date() + datetime.timedelta(days=1):
            return "Tomorrow"
        return trigger_dt.strftime("%A, %d %b")

    def _show_alarm_confirmation(self, alarm, trigger_dt):
        app = App.get_running_app()
        now = datetime.datetime.now()
        day_label = self._next_day_label(trigger_dt, now)
        label_text = (alarm.get("label") or "Alarm").strip() or "Alarm"
        time_text = format_time(alarm["hour"], alarm["minute"])
        repeat_text = format_days(alarm.get("days"))
        volume_text = "{}%".format(int(round(float(alarm.get("volume", 0.80)) * 100)))
        details = [
            ("Sound", alarm.get("sound_name") or "Default beep"),
            ("Repeat", repeat_text),
            ("Volume", volume_text),
            ("Vibration", "On" if alarm.get("vibrate") else "Off"),
            ("Auto-dismiss", format_duration(alarm.get("auto_dismiss_sec", 300))),
            ("Snooze", format_duration(alarm.get("snooze_sec", 300))),
        ]
        content = BoxLayout(orientation="vertical", padding=(dp(18), dp(14), dp(18), dp(14)), spacing=dp(8))
        title = Label(text="ALARM SET FOR {}".format(day_label.upper()), color=(156/255, 12/255, 12/255, 1),
                      font_size="15sp", bold=True, size_hint_y=None, height=dp(28),
                      halign="center", valign="middle")
        title.bind(size=lambda w, v: setattr(w, "text_size", v))
        content.add_widget(title)
        name_label = Label(text=label_text, color=(0.64, 0.64, 0.68, 1), font_size="13sp", bold=True,
                           size_hint_y=None, height=dp(22), halign="center", valign="middle")
        name_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        content.add_widget(name_label)
        big_time = Label(text=time_text, color=(0.975, 0.975, 0.985, 1), font_size="32sp", bold=True,
                         size_hint_y=None, height=dp(52), halign="center", valign="middle")
        big_time.bind(size=lambda w, v: setattr(w, "text_size", v))
        content.add_widget(big_time)

        details_panel = RoundedPanel(fill=(0.060, 0.060, 0.068, 1), radius=dp(16),
                                      orientation="vertical", padding=(dp(12), dp(8), dp(12), dp(8)),
                                      spacing=dp(2), size_hint_y=None, height=dp(162))
        for key, value in details:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(23), spacing=dp(8))
            left = Label(text=key, color=(0.64, 0.64, 0.68, 1), font_size="11sp",
                         halign="left", valign="middle", size_hint_x=0.42)
            left.bind(size=lambda w, v: setattr(w, "text_size", v))
            right = Label(text=str(value), color=(0.975, 0.975, 0.985, 1), font_size="11sp", bold=True,
                          halign="right", valign="middle", size_hint_x=0.58)
            right.bind(size=lambda w, v: setattr(w, "text_size", v))
            row.add_widget(left)
            row.add_widget(right)
            details_panel.add_widget(row)
        content.add_widget(details_panel)

        popup = Popup(title="", content=content, size_hint=(0.88, None), height=dp(455),
                      background="atlas://data/images/defaulttheme/modalview-background",
                      background_color=(0, 0, 0, 0), separator_height=0, auto_dismiss=False)

        def finish(_button=None):
            popup.dismiss()
            app.root.current = "home"
            home = app.root.get_screen("home")
            home._refresh_next_alarm()
            remaining_seconds = max(0.0, (trigger_dt - datetime.datetime.now()).total_seconds())
            total_minutes = int(math.ceil(remaining_seconds / 60.0))
            hours, minutes = divmod(total_minutes, 60)
            message = "Alarm Set for {} {} and {} {} from now".format(
                hours, "hour" if hours == 1 else "hours",
                minutes, "minute" if minutes == 1 else "minutes",
            )
            Clock.schedule_once(lambda _dt: home.show_toast(message), 0.12)

        content.add_widget(RoundedActionButton("DONE", callback=finish, accent=True,
                                               size_hint_y=None, height=dp(44)))
        popup.open()

    def save_alarm(self):
        try:
            hour12 = int(self.time_state["hour"])
            minute = int(self.time_state["minute"])
            period = str(self.time_state.get("ampm", self.ampm)).upper()
        except (KeyError, TypeError, ValueError):
            return self._fail("Enter a valid time.")
        if not 1 <= hour12 <= 12:
            return self._fail("Hour must be between 1 and 12.")
        if not 0 <= minute <= 59:
            return self._fail("Minutes must be between 00 and 59.")
        if period == "PM":
            hour24 = 12 if hour12 == 12 else hour12 + 12
        else:
            hour24 = 0 if hour12 == 12 else hour12
        try:
            dismiss_seconds = int(self.auto_dismiss_sec)
            snooze_seconds = int(self.snooze_sec)
            volume = max(0.0, min(1.0, float(self.volume)))
        except (TypeError, ValueError, OverflowError):
            return self._fail("Enter valid settings values.")
        if not 3 <= dismiss_seconds <= 10800:
            return self._fail("Auto-dismiss must be between 3 seconds and 3 Hr.")
        if not 3 <= snooze_seconds <= 10800:
            return self._fail("Snooze must be between 3 seconds and 3 Hr.")

        app = App.get_running_app()
        is_new_alarm = not bool(self.editing_id)
        alarm = app.store.get(self.editing_id) or {}
        sound_path = self.sound_path or app.default_ringtone_path
        sound_name = self.sound_name if self.sound_path else "Default beep"
        alarm.update({
            "id": self.editing_id or new_alarm_id(),
            "hour": hour24,
            "minute": minute,
            "days": list(self.days_selected),
            "label": str(self.time_state.get("label") or self.label_input.text or "").strip(),
            "sound_path": sound_path,
            "sound_name": sound_name,
            "volume": volume,
            "auto_dismiss_sec": dismiss_seconds,
            "snooze_sec": snooze_seconds,
            "vibrate": bool(self.vibrate),
            "enabled": True,
        })
        app.store.put(alarm)
        app.scheduler.cancel(alarm)
        app.scheduler.cancel_snooze(alarm)
        trigger_dt = app.scheduler.schedule(alarm)
        print("[RedAlarm] alarm saved:", alarm.get("id"), "next trigger:", trigger_dt,
              "new:", is_new_alarm)
        self._show_alarm_confirmation(alarm, trigger_dt)
'''


def main() -> int:
    if not MAIN.is_file() or not KV.is_file() or not (ROOT / ".git").exists():
        print("ERROR: Run this installer from the root of your RedAlarm git checkout.")
        return 2
    if not MODULE_SOURCE.is_file():
        print("ERROR: redalarm_timepicker_payload.py must be beside this installer in the extracted ZIP.")
        return 2

    branch = run_git("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        print("ERROR: Expected branch {!r}, current branch is {!r}. No files changed.".format(EXPECTED_BRANCH, branch))
        return 2
    target_dirty = run_git("status", "--porcelain", "--", "main.py", "alarm.kv")
    if target_dirty:
        print("ERROR: main.py/alarm.kv have local changes. Commit or back them up before applying this patch.")
        print(target_dirty)
        return 2
    if MODULE_DEST.exists():
        print("ERROR: redalarm_timepicker.py already exists; refusing to overwrite it. No files changed.")
        return 2

    main_text = MAIN.read_text(encoding="utf-8")
    kv_text = KV.read_text(encoding="utf-8")
    module_text = MODULE_SOURCE.read_text(encoding="utf-8")

    # Import the new UI module only once near the app constants.
    main_text = replace_once(
        main_text,
        'from kivy.uix.textinput import TextInput\nfrom kivy.uix.widget import Widget\n\n\nAPP_TITLE = "Red Alarm"',
        'from kivy.uix.textinput import TextInput\nfrom kivy.uix.widget import Widget\nfrom redalarm_timepicker import AlarmEditorUI, RoundedActionButton, RoundedPanel, format_duration\n\n\nAPP_TITLE = "Red Alarm"',
        "import premium alarm editor module",
    )

    # Add a light-weight Kivy toast to the existing first/home screen.
    old_home_actions = '''    def go_alarms(self):
        App.get_running_app().root.current = "list"

    def go_new_alarm(self):
'''
    new_home_actions = r'''    def go_alarms(self):
        App.get_running_app().root.current = "list"

    def show_toast(self, message):
        """Display a crisp, animated toast over the home clock."""
        previous = getattr(self, "_toast_widget", None)
        if previous is not None and previous.parent is self:
            self.remove_widget(previous)
        toast_width = max(dp(230), min(self.width - dp(32), dp(350)))
        toast = BoxLayout(orientation="horizontal", size_hint=(None, None),
                          size=(toast_width, dp(54)), padding=(dp(14), dp(7)))
        toast.pos = (self.center_x - toast_width / 2, dp(28))
        toast.opacity = 0
        with toast.canvas.before:
            Color(rgba=(0.075, 0.060, 0.064, 1))
            toast_bg = RoundedRectangle(pos=toast.pos, size=toast.size, radius=[dp(18)])
            Color(rgba=(0.6118, 0.0471, 0.0471, 1))
            toast_border = Line(rounded_rectangle=(toast.x, toast.y, toast.width, toast.height, dp(18)), width=dp(1.0))
        def sync_toast(*_):
            toast_bg.pos, toast_bg.size = toast.pos, toast.size
            toast_border.rounded_rectangle = (toast.x, toast.y, toast.width, toast.height, dp(18))
        toast.bind(pos=sync_toast, size=sync_toast)
        label = Label(text=message, color=(0.98, 0.98, 0.99, 1), font_size="12.5sp",
                      bold=True, halign="center", valign="middle")
        label.bind(size=lambda w, v: setattr(w, "text_size", (w.width, None)))
        toast.add_widget(label)
        self.add_widget(toast)
        self._toast_widget = toast
        Animation(opacity=1, duration=0.18, t="out_quad").start(toast)

        def fade(_dt):
            animation = Animation(opacity=0, duration=0.28, t="in_quad")
            def remove_toast(*_):
                if toast.parent is self:
                    self.remove_widget(toast)
                if getattr(self, "_toast_widget", None) is toast:
                    self._toast_widget = None
            animation.bind(on_complete=remove_toast)
            animation.start(toast)
        Clock.schedule_once(fade, 3.2)

    def go_new_alarm(self):
'''
    main_text = replace_once(main_text, old_home_actions, new_home_actions, "add home toast")

    # The real app's Android MediaPlayer path also honours the selected volume.
    main_text = replace_once(
        main_text,
        '        def __init__(self, path, loop=True):\n            MediaPlayer = autoclass("android.media.MediaPlayer")',
        '        def __init__(self, path, loop=True, volume=1.0):\n            MediaPlayer = autoclass("android.media.MediaPlayer")',
        "allow Android alarm volume",
    )
    main_text = replace_once(
        main_text,
        '            self._mp = MediaPlayer()\n            try:\n',
        '            self._mp = MediaPlayer()\n            self._volume = max(0.0, min(1.0, float(volume)))\n            try:\n',
        "store Android alarm volume",
    )
    main_text = replace_once(
        main_text,
        '                self._mp.prepare()\n                self._mp.start()\n',
        '                self._mp.prepare()\n                self._mp.setVolume(self._volume, self._volume)\n                self._mp.start()\n',
        "set Android MediaPlayer volume",
    )

    # Replace the sound helper in one operation, preserving its fallback path.
    load_start = main_text.find("def load_and_play(path, loop=True):")
    load_end = main_text.find("\n\n# ======================================================================\n# 3. CUSTOM WIDGETS", load_start)
    if load_start < 0 or load_end < 0:
        raise RuntimeError("Could not locate load_and_play() block. No files changed.")
    new_load = r'''def load_and_play(path, loop=True, volume=1.0):
    """Play a ringtone with the requested 0..1 volume on Android or desktop."""
    if not path:
        return None
    if not os.path.exists(path):
        print("[RedAlarm] playback: file does not exist:", path)
        return None
    try:
        volume = max(0.0, min(1.0, float(volume)))
    except (TypeError, ValueError):
        volume = 1.0
    if ANDROID:
        try:
            player = _AndroidPlayer(path, loop, volume=volume)
            print("[RedAlarm] playback: native MediaPlayer started:", path)
            return player
        except Exception as exc:
            print("[RedAlarm] playback: native MediaPlayer failed, trying SoundLoader:", exc)
    try:
        sound = SoundLoader.load(path)
        if sound is not None:
            sound.loop = loop
            sound.volume = volume
            sound.play()
            print("[RedAlarm] playback: SoundLoader started:", path)
            return sound
        print("[RedAlarm] playback: SoundLoader returned None for", path)
    except Exception as exc:
        print("[RedAlarm] playback: SoundLoader error:", exc)
    return None'''
    main_text = main_text[:load_start] + new_load + main_text[load_end:]

    # Replace obsolete grid-popup picker and editor class with the wired two-page editor.
    main_text = replace_region(
        main_text,
        "class TimePickerPopup(Popup):",
        "class AlarmRingScreen(Screen):",
        NEW_EDITOR_CLASS,
        "replace legacy editor and time picker",
    )

    # Ring playback uses the saved per-alarm volume, including its fallback sound.
    old_ring_start = '''        sound = load_and_play(path, loop=True) if path else None
        if sound is None and path != app.default_ringtone_path:
            print("[RedAlarm] ring: chosen sound failed, falling back to default beep")
            sound = load_and_play(app.default_ringtone_path, loop=True)
'''
    new_ring_start = '''        try:
            ring_volume = max(0.0, min(1.0, float(alarm.get("volume", 0.80))))
        except (TypeError, ValueError):
            ring_volume = 0.80
        sound = load_and_play(path, loop=True, volume=ring_volume) if path else None
        if sound is None and path != app.default_ringtone_path:
            print("[RedAlarm] ring: chosen sound failed, falling back to default beep")
            sound = load_and_play(app.default_ringtone_path, loop=True, volume=ring_volume)
'''
    main_text = replace_once(main_text, old_ring_start, new_ring_start, "apply alarm volume to ring playback")

    # The edit screen is built by AlarmEditorUI in Python; KV retains only its background.
    kv_start = kv_text.find("<AlarmEditScreen>:")
    kv_end = kv_text.find("<AlarmRingScreen>:", kv_start)
    if kv_start < 0 or kv_end < 0:
        raise RuntimeError("Could not locate the complete AlarmEditScreen KV block. No files changed.")
    new_kv = '''<AlarmEditScreen>:
    canvas.before:
        Color:
            rgba: COL_BG
        Rectangle:
            pos: self.pos
            size: self.size


'''
    kv_text = kv_text[:kv_start] + new_kv + kv_text[kv_end:]

    # Static syntax checks must pass before backups/writes.
    compile(main_text, str(MAIN), "exec")
    compile(module_text, str(MODULE_DEST), "exec")
    if 'class AlarmEditScreen(Screen):' not in main_text or 'class AlarmAppSettingsPage(BoxLayout):' not in module_text:
        raise RuntimeError("Post-transform markers missing. No files changed.")
    if 'transparent.png' in module_text:
        raise RuntimeError("Invalid transparent.png texture reference found. No files changed.")
    if 'self.ids.dismiss_min' in main_text or 'self.ids.input_hour' in main_text:
        raise RuntimeError("A legacy edit-screen id reference remains in main.py. No files changed.")
    if 'set_editing(' in NEW_EDITOR_CLASS:
        raise RuntimeError("TimePickerPage API mismatch: unexpected set_editing() call. No files changed.")
    if 'from kivy.core.audio import SoundLoader' not in module_text:
        raise RuntimeError("redalarm_timepicker module is missing the spinner-tick SoundLoader import. No files changed.")

    # Stage all output files first, then keep recoverable backups before replacing
    # any project source. If one replacement fails, restore both original files.
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT.parent / (ROOT.name + "-timepicker-backup-" + stamp)
    backup_dir.mkdir(parents=True, exist_ok=False)
    main_backup = backup_dir / "main.py.before_timepicker.bak"
    kv_backup = backup_dir / "alarm.kv.before_timepicker.bak"
    shutil.copy2(MAIN, main_backup)
    shutil.copy2(KV, kv_backup)

    temp_main = ROOT / ".main.py.timepicker.tmp"
    temp_kv = ROOT / ".alarm.kv.timepicker.tmp"
    temp_module = ROOT / ".redalarm_timepicker.py.timepicker.tmp"
    try:
        temp_main.write_text(main_text, encoding="utf-8")
        temp_kv.write_text(kv_text, encoding="utf-8")
        shutil.copy2(MODULE_SOURCE, temp_module)
        compile(temp_main.read_text(encoding="utf-8"), str(MAIN), "exec")
        compile(temp_module.read_text(encoding="utf-8"), str(MODULE_DEST), "exec")
        temp_main.replace(MAIN)
        temp_kv.replace(KV)
        temp_module.replace(MODULE_DEST)
    except Exception:
        # Best-effort rollback ensures a partial write does not leave a half-patched app.
        shutil.copy2(main_backup, MAIN)
        shutil.copy2(kv_backup, KV)
        if MODULE_DEST.exists():
            try:
                MODULE_DEST.unlink()
            except OSError:
                pass
        raise
    finally:
        for temp_path in (temp_main, temp_kv, temp_module):
            try:
                temp_path.unlink()
            except OSError:
                pass

    print("SUCCESS: integrated premium two-page alarm time picker into the local branch.")
    print("Branch:", branch)
    print("Backup folder:", backup_dir)
    print("Files modified/added:")
    print("  - main.py (editor flow, alarm save confirmation, toast, volume-aware playback)")
    print("  - alarm.kv (removed old edit layout; custom editor UI is now created by Python)")
    print("  - redalarm_timepicker.py (new custom UI widgets, wheel, settings and duration controls)")
    print("Next run these checks from this folder:")
    print("  py -m py_compile main.py redalarm_timepicker.py")
    print("  git diff --check")
    print("  git diff --stat")
    print("  python main.py")
    print("No commit or push was performed. Test locally before committing.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR:", exc)
        raise SystemExit(1)
