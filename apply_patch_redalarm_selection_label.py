#!/usr/bin/env python3
"""RedAlarm patch: alarm-list long-press multi-select and editable 25-word labels.

Run from /workspaces/RedAlarm on fix/spinner-cancel-touch.
The script refuses to apply if the expected source blocks do not match.
"""
from __future__ import annotations

import datetime
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path.cwd()
FILES = ("main.py", "alarm.kv", "redalarm_timepicker.py", "validate_redalarm_timepicker_integration.py")


def fail(message: str) -> None:
    raise SystemExit("[RedAlarm patch] ERROR: " + message)


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        fail("{}: expected one matching source block, found {}. No files were written.".format(label, count))
    return source.replace(old, new, 1)


def replace_all(source: str, old: str, new: str, label: str, expected: int | None = None) -> str:
    count = source.count(old)
    if expected is not None and count != expected:
        fail("{}: expected {} matching blocks, found {}. No files were written.".format(label, expected, count))
    if count == 0:
        fail("{}: matching source block not found. No files were written.".format(label))
    return source.replace(old, new)


def replace_between(source: str, start: str, end: str, replacement: str, label: str) -> str:
    if source.count(start) != 1 or source.count(end) != 1:
        fail("{}: expected unique section markers. No files were written.".format(label))
    a = source.index(start)
    b = source.index(end, a + len(start))
    if b <= a:
        fail("{}: invalid section boundaries. No files were written.".format(label))
    return source[:a] + replacement.rstrip() + "\n\n" + source[b:]


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=str(ROOT), text=True)
    if result.returncode:
        fail("command failed ({}): {}".format(result.returncode, " ".join(command)))


def main() -> None:
    if not (ROOT / ".git").exists() or not all((ROOT / name).is_file() for name in FILES):
        fail("Run this from the RedAlarm repository root (/workspaces/RedAlarm).")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=str(ROOT), text=True).strip()
    if branch != "fix/spinner-cancel-touch":
        fail("Expected branch 'fix/spinner-cancel-touch', found {!r}. Switch branches first.".format(branch))

    original = {name: (ROOT / name).read_text(encoding="utf-8") for name in FILES}
    main_src = original["main.py"]
    kv_src = original["alarm.kv"]
    editor_src = original["redalarm_timepicker.py"]
    test_src = original["validate_redalarm_timepicker_integration.py"]

    # A disabled/touch-held switch must not toggle the alarm after a long-press
    # has changed the list into selection mode.
    main_src = replace_once(
        main_src,
        'class IOSToggle(ButtonBehavior, Widget):\n    """Rounded iOS-style switch: RED when on, GREY when off. Exposes a normal\n    `active` BooleanProperty, so `on_active:` works in kv like a Switch."""\n\n    active = BooleanProperty(False)\n    _thumb = NumericProperty(0)   # 0 = left/off, 1 = right/on (animated)\n',
        'class IOSToggle(ButtonBehavior, Widget):\n    """Rounded iOS-style switch: RED when on, GREY when off. Exposes a normal\n    `active` BooleanProperty, so `on_active:` works in kv like a Switch."""\n\n    active = BooleanProperty(False)\n    row = ObjectProperty(None)\n    _thumb = NumericProperty(0)   # 0 = left/off, 1 = right/on (animated)\n',
        "IOSToggle row property",
    )
    main_src = replace_once(
        main_src,
        '    def on_release(self):\n        self.active = not self.active\n\n    def _redraw(self, *_):\n',
        '    def on_release(self):\n        row = self.row\n        if row is not None:\n            row.release_child_touch()\n            if row._long_press_triggered:\n                row._long_press_triggered = False\n                return\n            if row.list_screen is not None and row.list_screen.selection_mode:\n                return\n        self.active = not self.active\n\n    def _redraw(self, *_):\n',
        "IOSToggle long-press guard",
    )

    indicator_class = '''class AlarmSelectionIndicator(ButtonBehavior, Widget):
    """A compact checkbox shown only while the alarm list is in selection mode."""
    selected = BooleanProperty(False)
    row = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, selected=self._redraw)
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        side = min(dp(22), self.width, self.height * 0.72)
        if side < dp(2):
            return
        x, y = self.center_x - side / 2.0, self.center_y - side / 2.0
        radius = min(dp(5), side / 4.0)
        with self.canvas:
            if self.selected:
                Color(rgba=(0.88, 0.12, 0.15, 1))
                RoundedRectangle(pos=(x, y), size=(side, side), radius=[radius])
                Color(rgba=(1, 1, 1, 1))
                Line(points=[x + side * 0.22, y + side * 0.53,
                             x + side * 0.43, y + side * 0.31,
                             x + side * 0.79, y + side * 0.72], width=dp(1.8), cap="round")
            else:
                Color(rgba=(0.34, 0.34, 0.36, 1))
                Line(rounded_rectangle=(x, y, side, side, radius), width=dp(1.35))

    def on_release(self):
        if self.row is not None and self.row.list_screen is not None:
            self.row.release_child_touch()
            self.row.on_row_press()


'''
    main_src = replace_once(main_src, "class AlarmInfoButton(ButtonBehavior, BoxLayout):", indicator_class + "class AlarmInfoButton(ButtonBehavior, BoxLayout):", "selection indicator class insertion")
    main_src = replace_once(
        main_src,
        '    def on_release(self):\n        if self.row is not None:\n            self.row.on_row_press()\n\n\n# ======================================================================\n# 4. SCREENS',
        '    def on_release(self):\n        if self.row is not None:\n            self.row.release_child_touch()\n            self.row.on_row_press()\n\n\n# ======================================================================\n# 4. SCREENS',
        "selection-aware row tap",
    )

    row_class = '''class AlarmRow(BoxLayout):
    alarm_id = StringProperty("")
    time_text = StringProperty("")
    sub_text = StringProperty("")
    enabled = BooleanProperty(True)
    list_screen = ObjectProperty(None)
    selection_mode = BooleanProperty(False)
    selected = BooleanProperty(False)
    LONG_PRESS_SECONDS = 0.55

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._long_press_event = None
        self._press_touch = None
        self._press_origin = None
        self._long_press_triggered = False

    def release_child_touch(self):
        event, self._long_press_event = self._long_press_event, None
        if event is not None:
            try:
                event.cancel()
            except Exception:
                pass
        self._press_touch = None
        self._press_origin = None

    def _fire_long_press(self, touch):
        self._long_press_event = None
        if self._press_touch is not touch or self.list_screen is None:
            return
        if not self.collide_point(*touch.pos) or self.list_screen.selection_mode:
            return
        self._long_press_triggered = True
        self.list_screen.begin_selection(self.alarm_id)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.release_child_touch()
            self._long_press_triggered = False
            if self.list_screen is not None and not self.list_screen.selection_mode:
                self._press_touch = touch
                self._press_origin = tuple(touch.pos)
                self._long_press_event = Clock.schedule_once(
                    lambda _dt, held=touch: self._fire_long_press(held),
                    self.LONG_PRESS_SECONDS,
                )
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._press_touch is touch and not self._long_press_triggered and self._press_origin:
            if (abs(touch.x - self._press_origin[0]) > dp(14)
                    or abs(touch.y - self._press_origin[1]) > dp(14)):
                self.release_child_touch()
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._press_touch is touch:
            self.release_child_touch()
        return super().on_touch_up(touch)

    def on_switch_active(self, value):
        self.release_child_touch()
        if self._long_press_triggered:
            self._long_press_triggered = False
            return
        if self.list_screen is not None and self.list_screen.selection_mode:
            return
        value = bool(value)
        if value == self.enabled:      # programmatic sync, not a user tap
            return
        self.enabled = value
        if self.list_screen is not None:
            self.list_screen.on_toggle_alarm(self.alarm_id, value)

    def on_row_press(self):
        self.release_child_touch()
        if self._long_press_triggered:
            self._long_press_triggered = False
            return
        if self.list_screen is None:
            return
        if self.list_screen.selection_mode:
            self.list_screen.toggle_selection(self.alarm_id)
        else:
            self.list_screen.open_edit(self.alarm_id)

    def on_delete_press(self):
        self.release_child_touch()
        if self._long_press_triggered:
            self._long_press_triggered = False
            return
        if self.list_screen is not None:
            self.list_screen.confirm_delete(self.alarm_id)


'''
    main_src = replace_between(main_src, "class AlarmRow(BoxLayout):", "class AlarmListScreen(Screen):", row_class, "AlarmRow implementation")

    main_src = replace_once(
        main_src,
        '    def go_home(self):\n        App.get_running_app().root.current = "home"\n',
        '    def go_home(self):\n        if self.selection_mode:\n            self.cancel_selection()\n            return\n        App.get_running_app().root.current = "home"\n',
        "Back button clears selection first",
    )
    main_src = replace_once(
        main_src,
        '        self.time_state = {"hour": 7, "minute": 16, "ampm": "AM", "label": "Alarm"}\n',
        '        self.time_state = {"hour": 7, "minute": 16, "ampm": "AM", "label": ""}\n',
        "blank editor startup label",
    )
    main_src = replace_once(
        main_src,
        'class AlarmListScreen(Screen):\n    _delete_popup = None\n    exact_alarm_ok = BooleanProperty(True)\n',
        'class AlarmListScreen(Screen):\n    _delete_popup = None\n    selection_mode = BooleanProperty(False)\n    selected_alarm_ids = ListProperty([])\n    selected_count = NumericProperty(0)\n    all_selected = BooleanProperty(False)\n    exact_alarm_ok = BooleanProperty(True)\n',
        "AlarmListScreen selection properties",
    )

    selection_methods = '''    def _sync_selection_visuals(self):
        box = self.ids.get("alarms_box") if hasattr(self, "ids") else None
        if box is None:
            return
        selected = set(self.selected_alarm_ids)
        for row in box.children:
            if isinstance(row, AlarmRow):
                row.selection_mode = self.selection_mode
                row.selected = row.alarm_id in selected

    def _apply_selection_state(self, alarm_ids):
        app = App.get_running_app()
        available = {str(item.get("id", "")) for item in app.store.all()}
        unique = []
        for alarm_id in alarm_ids:
            alarm_id = str(alarm_id)
            if alarm_id in available and alarm_id not in unique:
                unique.append(alarm_id)
        self.selected_alarm_ids = unique
        self.selection_mode = bool(unique)
        self.selected_count = len(unique)
        self.all_selected = bool(available) and len(unique) == len(available)
        self._sync_selection_visuals()

    def begin_selection(self, alarm_id):
        ids = list(self.selected_alarm_ids) if self.selection_mode else []
        if str(alarm_id) not in ids:
            ids.append(str(alarm_id))
        self._apply_selection_state(ids)

    def toggle_selection(self, alarm_id):
        ids = list(self.selected_alarm_ids)
        alarm_id = str(alarm_id)
        if alarm_id in ids:
            ids.remove(alarm_id)
        else:
            ids.append(alarm_id)
        if not ids:
            self.cancel_selection()
        else:
            self._apply_selection_state(ids)

    def select_all_selected(self):
        ids = [str(item.get("id", "")) for item in App.get_running_app().store.all()]
        if not ids or self.all_selected:
            self.cancel_selection()
        else:
            self._apply_selection_state(ids)

    def cancel_selection(self):
        self.selected_alarm_ids = []
        self.selection_mode = False
        self.selected_count = 0
        self.all_selected = False
        self._sync_selection_visuals()

    def copy_selected(self):
        app = App.get_running_app()
        selected_ids = list(self.selected_alarm_ids)
        if not selected_ids:
            return
        copied_count = 0
        for alarm_id in selected_ids:
            alarm = app.store.get(alarm_id)
            if not alarm:
                continue
            duplicate = dict(alarm)
            duplicate["id"] = new_alarm_id()
            duplicate["days"] = list(alarm.get("days") or [False] * 7)
            app.store.put(duplicate)
            if duplicate.get("enabled", True):
                app.scheduler.schedule(duplicate)
            copied_count += 1
        if copied_count:
            app.refresh_next_alarm_notification()
        self.cancel_selection()
        self.refresh()

    def confirm_delete_selected(self):
        app = App.get_running_app()
        selected_ids = list(self.selected_alarm_ids)
        if not selected_ids:
            return
        active = getattr(self, "_delete_popup", None)
        if active is not None and getattr(active, "is_open", False):
            return

        count = len(selected_ids)
        content = RoundedPanel(
            fill=(0.045, 0.045, 0.052, 1), radius=dp(22),
            orientation="vertical", padding=(dp(18), dp(14), dp(18), dp(14)),
            spacing=dp(8),
        )
        title = Label(
            text="DELETE {} ALARM{}?".format(count, "S" if count != 1 else ""),
            color=(1, 0.42, 0.45, 1), font_size="15sp", bold=True,
            size_hint_y=None, height=dp(26), halign="center", valign="middle",
        )
        title.bind(size=lambda widget, value: setattr(widget, "text_size", value))
        content.add_widget(title)
        details = Label(
            text="This removes the selected alarms and cancels their schedules.",
            color=(0.72, 0.72, 0.76, 1), font_size="12sp",
            size_hint_y=None, height=dp(36), halign="center", valign="middle",
        )
        details.bind(size=lambda widget, value: setattr(widget, "text_size", value))
        content.add_widget(details)
        buttons = BoxLayout(orientation="horizontal", spacing=dp(10),
                            size_hint_y=None, height=dp(44))
        popup = Popup(
            title="", content=content, size_hint=(0.88, None), height=dp(190),
            separator_height=0, background_color=(0.025, 0.025, 0.03, 1),
            auto_dismiss=True,
        )

        def do_delete(*_):
            for alarm_id in selected_ids:
                alarm = app.store.get(alarm_id)
                if alarm:
                    app.scheduler.cancel(alarm)
                    app.scheduler.cancel_snooze(alarm)
                ring = app.root.get_screen("ring")
                if ring.alarm_id == alarm_id:
                    ring.finish(reason="delete")
                app.store.delete(alarm_id)
            app.refresh_next_alarm_notification()
            popup.dismiss()
            self.cancel_selection()
            self.refresh()

        buttons.add_widget(RoundedActionButton(
            "CANCEL", callback=lambda: popup.dismiss(), accent=False, size_hint_x=1,
        ))
        buttons.add_widget(RoundedActionButton(
            "DELETE", callback=do_delete, accent=True, size_hint_x=1,
        ))
        content.add_widget(buttons)
        self._delete_popup = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_delete_popup", None))
        popup.open()

'''
    main_src = replace_once(main_src, "    def on_pre_enter(self, *args):\n        self.refresh()\n", selection_methods + "    def on_pre_enter(self, *args):\n        self.refresh()\n", "multi-select action methods insertion")

    main_src = replace_once(
        main_src,
        '        alarms = app.store.all()\n        if not alarms:\n',
        '        alarms = app.store.all()\n        valid_ids = {str(item.get("id", "")) for item in alarms}\n        self.selected_alarm_ids = [item_id for item_id in self.selected_alarm_ids if item_id in valid_ids]\n        if not self.selected_alarm_ids:\n            self.selection_mode = False\n        self.selected_count = len(self.selected_alarm_ids)\n        self.all_selected = bool(alarms) and self.selected_count == len(alarms)\n        if not alarms:\n',
        "selection state retained safely during refresh",
    )
    main_src = replace_once(
        main_src,
        '            row.sub_text = (label + " · " + days_str) if label else days_str\n            row.enabled = bool(alarm.get("enabled", True))\n            box.add_widget(row)\n',
        '            row.sub_text = label if label else days_str\n            row.enabled = bool(alarm.get("enabled", True))\n            row.selection_mode = self.selection_mode\n            row.selected = row.alarm_id in self.selected_alarm_ids\n            box.add_widget(row)\n',
        "alarm list row labels and selection visuals",
    )

    # Blank text is the real default; the saved/ringing alarm may still fall
    # back to the friendly word Alarm if the user leaves the label empty.
    main_src = replace_once(
        main_src,
        '                "ampm": "PM" if now.hour >= 12 else "AM",\n                "label": "Alarm",\n',
        '                "ampm": "PM" if now.hour >= 12 else "AM",\n                "label": "",\n',
        "new-alarm blank label default",
    )
    main_src = replace_once(
        main_src,
        '            self.editing_id = alarm_id\n            hour24 = int(alarm.get("hour", 7)) % 24\n            self.time_state.update({\n',
        '            self.editing_id = alarm_id\n            hour24 = int(alarm.get("hour", 7)) % 24\n            stored_label = str(alarm.get("label") or "").strip()\n            if stored_label.lower() == "alarm":\n                stored_label = ""\n            self.time_state.update({\n',
        "normalize legacy default label",
    )
    main_src = replace_once(
        main_src,
        '                "label": str(alarm.get("label") or "Alarm"),\n',
        '                "label": stored_label,\n',
        "loaded alarm label",
    )
    main_src = replace_once(
        main_src,
        '        alarm = dict(existing_alarm or {})\n',
        '        label_text = str(self.label_input.text or self.time_state.get("label") or "").strip()\n        if len(label_text.split()) > 25:\n            return self._fail("Alarm label can contain up to 25 words.")\n\n        alarm = dict(existing_alarm or {})\n',
        "save-time alarm label word limit",
    )
    main_src = replace_once(
        main_src,
        '            "label": str(self.time_state.get("label") or self.label_input.text or "Alarm").strip() or "Alarm",\n',
        '            "label": label_text or "Alarm",\n',
        "save normalized label",
    )

    old_row_kv = '''<AlarmRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: "76dp"
    padding: "14dp", "8dp", "10dp", "8dp"
    spacing: "8dp"

    canvas.before:
        Color:
            rgba: COL_CARD if root.enabled else COL_CARD_DIM
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(16)]

    AlarmInfoButton:
        row: root
        time_text: root.time_text
        sub_text: root.sub_text
        dim: not root.enabled

    Button:
        text: "×"
        size_hint: None, None
        size: "42dp", "42dp"
        pos_hint: {"center_y": 0.5}
        background_normal: ""
        background_down: ""
        background_color: 0, 0, 0, 0
        color: (1, 0.48, 0.50, 1)
        font_size: "23sp"
        bold: True
        canvas.before:
            Color:
                rgba: (0.25, 0.045, 0.055, 1) if self.state == "normal" else (0.42, 0.07, 0.085, 1)
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(12)]
        on_release: root.on_delete_press()

    IOSToggle:
        active: root.enabled
        pos_hint: {"center_y": 0.5}
        on_active: root.on_switch_active(self.active)
'''
    new_row_kv = '''<AlarmRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: "76dp"
    padding: "14dp", "8dp", "10dp", "8dp"
    spacing: "8dp"

    canvas.before:
        Color:
            rgba: COL_CARD if root.enabled else COL_CARD_DIM
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(16)]
        Color:
            rgba: COL_RED if root.selected else (0, 0, 0, 0)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(16))
            width: dp(1.0)

    AlarmSelectionIndicator:
        row: root
        selected: root.selected
        size_hint_x: None
        width: dp(25) if root.selection_mode else 0
        opacity: 1 if root.selection_mode else 0
        disabled: not root.selection_mode

    AlarmInfoButton:
        row: root
        time_text: root.time_text
        sub_text: root.sub_text
        dim: not root.enabled

    IOSToggle:
        row: root
        active: root.enabled
        pos_hint: {"center_y": 0.5}
        disabled: root.selection_mode
        on_active: root.on_switch_active(self.active)
'''
    kv_src = replace_once(kv_src, old_row_kv, new_row_kv, "alarm row selection UI")

    footer_kv = '''\n        BoxLayout:
            orientation: "horizontal"
            size_hint_y: None
            height: dp(62) if root.selection_mode else 0
            opacity: 1 if root.selection_mode else 0
            disabled: not root.selection_mode
            spacing: dp(10)
            padding: 0, dp(6), 0, 0
            canvas.before:
                Color:
                    rgba: (0.045, 0.045, 0.05, 1) if root.selection_mode else (0, 0, 0, 0)
                Rectangle:
                    pos: self.pos
                    size: self.size
                Color:
                    rgba: (0.20, 0.20, 0.22, 1)
                Line:
                    points: self.x, self.top, self.right, self.top
                    width: dp(0.8)

            HomeButton:
                text: "Deselect All" if root.all_selected else "Select All"
                font_size: "12sp"
                size_hint_y: None
                height: dp(48)
                bg_color: (0.11, 0.11, 0.12, 1)
                text_color: COL_TEXT
                on_release: root.select_all_selected()

            HomeButton:
                text: "Copy"
                font_size: "12sp"
                size_hint_y: None
                height: dp(48)
                bg_color: (0.11, 0.11, 0.12, 1)
                text_color: COL_TEXT
                on_release: root.copy_selected()

            HomeButton:
                text: "Delete"
                font_size: "12sp"
                size_hint_y: None
                height: dp(48)
                bg_color: COL_RED
                text_color: 1, 1, 1, 1
                on_release: root.confirm_delete_selected()
'''
    kv_src = replace_once(
        kv_src,
        '                height: self.minimum_height\n                spacing: "12dp"\n\n\n# --------------------------------------------------------------------\n#  Screen 3 - Add / edit alarm',
        '                height: self.minimum_height\n                spacing: "12dp"\n' + footer_kv + '\n\n# --------------------------------------------------------------------\n#  Screen 3 - Add / edit alarm',
        "selection toolbar insertion",
    )

    # Make the label input genuinely empty by default, visibly readable, and
    # focusable even when nested in the custom settings card.
    editor_src = replace_once(
        editor_src,
        'class AlarmLabelInput(TextInput):\n    """Text input that reliably receives pointer focus in the custom picker UI."""\n    def on_touch_down(self, touch):\n',
        'class AlarmLabelInput(TextInput):\n    """Readable label input with a hard 25-word limit and reliable touch focus."""\n    MAX_WORDS = 25\n\n    def insert_text(self, substring, from_undo=False):\n        if from_undo:\n            return super().insert_text(substring, from_undo=from_undo)\n        substring = str(substring).replace("\\n", " ").replace("\\r", " ")\n        try:\n            if self.selection_text:\n                start = min(int(self.selection_from), int(self.selection_to))\n                end = max(int(self.selection_from), int(self.selection_to))\n            else:\n                start = end = int(self.cursor_index())\n            prefix, suffix = self.text[:start], self.text[end:]\n            candidate = prefix + substring + suffix\n            if len(candidate.split()) > self.MAX_WORDS:\n                while substring and len((prefix + substring + suffix).split()) > self.MAX_WORDS:\n                    substring = substring[:-1]\n                if not substring:\n                    return\n                if len((prefix + substring + suffix).split()) > self.MAX_WORDS:\n                    return\n        except (AttributeError, TypeError, ValueError):\n            if len((self.text + substring).split()) > self.MAX_WORDS:\n                return\n        return super().insert_text(substring, from_undo=from_undo)\n\n    def on_touch_down(self, touch):\n',
        "label input word limit",
    )

    # Two legacy/active label field constructors share the same visual fixes.
    editor_src = replace_once(editor_src, 'orientation="vertical", size_hint_y=None, height=dp(52), spacing=dp(3)\n        )\n        label_block.add_widget(self._label("ALARM LABEL", 12.0, SUB, height=17, bold=True))', 'orientation="vertical", size_hint_y=None, height=dp(56), spacing=dp(3)\n        )\n        label_block.add_widget(self._label("ALARM LABEL", 12.0, SUB, height=17, bold=True))', "legacy label field height")
    editor_src = replace_once(editor_src, 'text=self.state.get("label") or "Alarm",\n            hint_text="",\n', 'text=str(self.state.get("label") or ""),\n            hint_text="Enter label (optional)",\n', "legacy label input default")
    editor_src = replace_once(editor_src, 'font_size=sp(14.5), padding=(dp(12), dp(7)),\n            size_hint_y=None, height=dp(33),', 'font_size=sp(15), padding=(dp(12), dp(7)),\n            size_hint_y=None, height=dp(36),', "legacy label input readability")

    editor_src = replace_once(editor_src, 'label_block = BoxLayout(\n            orientation="vertical", size_hint_y=None, height=dp(52), spacing=dp(3)\n        )\n        label_block.add_widget(self._label("ALARM LABEL", 10.5, SUB, True, dp(16)))', 'label_block = BoxLayout(\n            orientation="vertical", size_hint_y=None, height=dp(56), spacing=dp(3)\n        )\n        label_block.add_widget(self._label("ALARM LABEL", 10.5, SUB, True, dp(16)))', "active label field height")
    editor_src = replace_once(editor_src, 'text=str(self.editor.time_state.get("label") or "Alarm"),\n            hint_text="Alarm name", multiline=False, write_tab=False,', 'text=str(self.editor.time_state.get("label") or ""),\n            hint_text="Enter label (optional)", multiline=False, write_tab=False,', "active label input default")
    editor_src = replace_once(editor_src, 'font_size=sp(13.5), padding=(dp(12), dp(6)),\n            size_hint_y=None, height=dp(33),', 'font_size=sp(15), padding=(dp(12), dp(7)),\n            size_hint_y=None, height=dp(36),', "active label input readability")

    editor_src = replace_all(editor_src, 'str(label or "Alarm")', 'str(label or "")', "empty label refresh API", expected=2)
    editor_src = replace_all(editor_src, 'str(state.get("label") or "Alarm")', 'str(state.get("label") or "")', "empty label refresh sync", expected=1)
    editor_src = replace_once(editor_src, '        self.editor.time_state["label"] = value\n\n    def set_values(self, hour, minute, ampm, label=""):', '        self.editor.time_state["label"] = value\n\n    def on_touch_down(self, touch):\n        label_input = getattr(self, "label_input", None)\n        if label_input is not None and label_input.collide_point(*touch.pos):\n            return label_input.on_touch_down(touch)\n        return super().on_touch_down(touch)\n\n    def set_values(self, hour, minute, ampm, label=""):', "active page label touch routing")
    editor_src = replace_once(editor_src, '            "label": str(label or ""),\n        })\n        self.editor.ampm = self.editor.time_state["ampm"]\n        self.label_input.text = self.editor.time_state["label"]\n', '            "label": str(label or ""),\n        })\n        self.editor.ampm = self.editor.time_state["ampm"]\n        self.label_input.text = self.editor.time_state["label"]\n', "active page label API consistency")

    # Regression coverage for the newly added selection/label features.
    test_src = replace_once(
        test_src,
        '    print("PASS: active screen boundaries and obsolete picker handlers")\n',
        '    if "class AlarmSelectionIndicator(ButtonBehavior, Widget):" not in main_text:\n        fail("Alarm-list selection checkbox widget is missing")\n    for marker in ("def begin_selection(", "def toggle_selection(", "def select_all_selected(", "def copy_selected(", "def confirm_delete_selected("):\n        if marker not in main_text:\n            fail("Alarm-list multi-select action is missing: " + marker)\n    if any(marker not in kv_text for marker in ("AlarmSelectionIndicator:", \'text: "Copy"\', "root.copy_selected()", "root.confirm_delete_selected()")):\n        fail("Alarm-list long-press toolbar wiring is incomplete")\n    if "MAX_WORDS = 25" not in module_text or "Enter label (optional)" not in module_text:\n        fail("Editable, 25-word alarm-label input is missing")\n    print("PASS: long-press multi-select, select-all/copy/delete toolbar, and label input word cap")\n    print("PASS: active screen boundaries and obsolete picker handlers")\n',
        "static regression checks for selection and label input",
    )

    updated = {
        "main.py": main_src,
        "alarm.kv": kv_src,
        "redalarm_timepicker.py": editor_src,
        "validate_redalarm_timepicker_integration.py": test_src,
    }
    if updated == original:
        fail("No source changes produced; refusing to continue.")

    backup_dir = pathlib.Path("/tmp") / ("redalarm-selection-label-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        shutil.copy2(ROOT / name, backup_dir / name)
    for name, content in updated.items():
        (ROOT / name).write_text(content, encoding="utf-8", newline="\n")

    print("[RedAlarm patch] Backup:", backup_dir)
    run([sys.executable, "-m", "py_compile", "main.py", "redalarm_timepicker.py", "validate_redalarm_timepicker_integration.py"])
    run([sys.executable, "validate_redalarm_timepicker_integration.py"])
    run(["git", "diff", "--check"])
    print("[RedAlarm patch] SUCCESS: long-press selection, bottom actions, and editable 25-word labels are wired.")
    print("[RedAlarm patch] Review with: git diff -- main.py alarm.kv redalarm_timepicker.py validate_redalarm_timepicker_integration.py")
    print("[RedAlarm patch] This is static validation; test long-press, copy, delete, and typing on the Android APK.")


if __name__ == "__main__":
    main()
