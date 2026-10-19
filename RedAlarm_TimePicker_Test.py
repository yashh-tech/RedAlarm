"""Standalone RedAlarm spinning time-picker prototype.

Run with the Python installation that has Kivy installed:
    python RedAlarm_TimePicker_Test.py

This file is independent of RedAlarm's main.py and does not create or edit alarms.
"""

import math

from kivy.config import Config
Config.set("graphics", "width", "440")
Config.set("graphics", "height", "820")
Config.set("graphics", "resizable", "1")

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle


# RedAlarm-inspired palette.
BG = (0.025, 0.025, 0.030, 1)
CARD = (0.055, 0.055, 0.062, 1)
RED = (0.88, 0.055, 0.105, 1)
RED_SOFT = (0.29, 0.025, 0.045, 0.72)
TEXT = (0.97, 0.97, 0.98, 1)
SUB = (0.64, 0.64, 0.68, 1)


class RoundedPanel(BoxLayout):
    """BoxLayout with a rounded background, drawn behind its children."""

    def __init__(self, fill=CARD, radius=dp(28), **kwargs):
        super().__init__(**kwargs)
        self._fill = fill
        self._radius = radius
        with self.canvas.before:
            Color(rgba=self._fill)
            self._background = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self._radius]
            )
        self.bind(pos=self._sync_background, size=self._sync_background)

    def _sync_background(self, *_):
        self._background.pos = self.pos
        self._background.size = self.size
        self._background.radius = [self._radius]


class WheelScrollView(ScrollView):
    """ScrollView that tells the wheel when finger/mouse dragging begins."""

    def __init__(self, wheel, **kwargs):
        self.wheel = wheel
        super().__init__(**kwargs)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not getattr(touch, "is_mouse_scrolling", False):
            self.wheel._touch_started()
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self.wheel.user_touching:
            self.wheel._touch_ended()
        return result


class SpinnerWheel(BoxLayout):
    """A vertical, cyclic spinner wheel with snapping and a highlighted center."""

    selected_text = StringProperty("")

    def __init__(self, values, selected_value, on_change, formatter=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint", (1, 1))
        super().__init__(**kwargs)

        self.values = list(values)
        self.period = len(self.values)
        self.formatter = formatter or (lambda value: str(value))
        self.on_change = on_change
        self.row_height = dp(56)
        self.cycles = 7
        self.total_rows = self.period * self.cycles
        self.initializing = True
        self.snapping = False
        self.user_touching = False
        self._suppress_callback = False
        self._snap_event = None
        self._styled_indices = set()

        if selected_value not in self.values:
            selected_value = self.values[0]
        self._selected_value = selected_value
        self.selected_text = self.formatter(selected_value)
        base_index = self.values.index(selected_value)
        self.center_index = (self.cycles // 2) * self.period + base_index

        self.content_box = BoxLayout(
            orientation="vertical", size_hint=(1, None),
            height=self.row_height * self.total_rows, spacing=0, padding=0,
        )
        self.rows = []
        for i in range(self.total_rows):
            value = self.values[i % self.period]
            label = Label(
                text=self.formatter(value), size_hint_y=None,
                height=self.row_height, halign="center", valign="middle",
                color=(0.30, 0.30, 0.33, 0.24), font_size="19sp",
            )
            self.rows.append(label)
            self.content_box.add_widget(label)

        self.scroll = WheelScrollView(
            self, do_scroll_x=False, do_scroll_y=True,
            scroll_type=["content"], bar_width=0, effect_cls="ScrollEffect",
        )
        self.scroll.add_widget(self.content_box)
        self.add_widget(self.scroll)
        self.scroll.bind(scroll_y=self._on_scroll_y)
        self._restyle_rows(self.center_index)
        Clock.schedule_once(self._apply_initial_center, 0.20)

    def _max_scroll_offset(self):
        return max(0.0, self.content_box.height - self.scroll.height)

    def _nearest_index(self):
        max_offset = self._max_scroll_offset()
        if max_offset <= 0 or self.scroll.height <= 0:
            return self.center_index
        offset = (1.0 - self.scroll.scroll_y) * max_offset
        raw = (offset + self.scroll.height / 2.0 - self.row_height / 2.0) / self.row_height
        return max(0, min(self.total_rows - 1, int(round(raw))))

    def _scroll_y_for_index(self, index):
        max_offset = self._max_scroll_offset()
        if max_offset <= 0:
            return 1.0
        offset = (index + 0.5) * self.row_height - self.scroll.height / 2.0
        offset = max(0.0, min(max_offset, offset))
        return 1.0 - (offset / max_offset)

    def _apply_initial_center(self, *_):
        if self.scroll.height <= 0 or self._max_scroll_offset() <= 0:
            Clock.schedule_once(self._apply_initial_center, 0.10)
            return
        self.initializing = True
        self.scroll.scroll_y = self._scroll_y_for_index(self.center_index)
        self._restyle_rows(self.center_index)
        Clock.schedule_once(self._finish_initial_center, 0.12)

    def _finish_initial_center(self, *_):
        self.center_index = self._nearest_index()
        self.initializing = False
        self._restyle_rows(self.center_index)
        self._set_selected(self.center_index, notify=False)

    def _restyle_rows(self, center_index):
        visible = set(range(max(0, center_index - 3), min(self.total_rows, center_index + 4)))
        for index in self._styled_indices | visible:
            label = self.rows[index]
            distance = abs(index - center_index)
            if distance == 0:
                label.font_size = "31sp"
                label.color = TEXT
            elif distance == 1:
                label.font_size = "25sp"
                label.color = (0.72, 0.72, 0.75, 0.82)
            elif distance == 2:
                label.font_size = "21sp"
                label.color = (0.45, 0.45, 0.48, 0.50)
            else:
                label.font_size = "19sp"
                label.color = (0.30, 0.30, 0.33, 0.23)
        self._styled_indices = visible

    def _set_selected(self, index, notify=True):
        value = self.values[index % self.period]
        if value != self._selected_value:
            self._selected_value = value
            self.selected_text = self.formatter(value)
            if notify and self.on_change:
                self.on_change(value)

    def _on_scroll_y(self, *_):
        if self.initializing:
            return
        self.center_index = self._nearest_index()
        self._restyle_rows(self.center_index)
        if self.snapping or self._suppress_callback:
            return
        self._set_selected(self.center_index)
        if not self.user_touching:
            self._schedule_snap(0.18)

    def _touch_started(self):
        self.user_touching = True
        if self._snap_event:
            self._snap_event.cancel()
            self._snap_event = None
        Animation.cancel_all(self.scroll, "scroll_y")
        self.snapping = False

    def _touch_ended(self):
        self.user_touching = False
        self._schedule_snap(0.22)

    def _schedule_snap(self, delay):
        if self.initializing or self.user_touching:
            return
        if self._snap_event:
            self._snap_event.cancel()
        self._snap_event = Clock.schedule_once(self._snap_to_nearest, delay)

    def _snap_to_nearest(self, _dt):
        self._snap_event = None
        if self.initializing or self.user_touching:
            return
        index = self._nearest_index()
        self.center_index = index
        self._set_selected(index)
        target = self._scroll_y_for_index(index)

        if abs(self.scroll.scroll_y - target) < 0.001:
            self._restyle_rows(index)
            self._recenter_if_needed(index)
            return

        self.snapping = True
        Animation.cancel_all(self.scroll, "scroll_y")
        animation = Animation(scroll_y=target, duration=0.14, t="out_quad")
        animation.bind(on_complete=lambda *_: self._finish_snap())
        animation.start(self.scroll)

    def _finish_snap(self):
        self.snapping = False
        self.center_index = self._nearest_index()
        self._set_selected(self.center_index)
        self._restyle_rows(self.center_index)
        self._recenter_if_needed(self.center_index)

    def _recenter_if_needed(self, index):
        # Reposition to the middle copy of the same value at the ends,
        # making the wheel effectively endless without a visible jump.
        if self.user_touching or self.initializing:
            return
        if index >= self.period and index < self.total_rows - self.period:
            return
        new_index = (self.cycles // 2) * self.period + (index % self.period)
        if new_index == index:
            return
        self.initializing = True
        self._suppress_callback = True
        self.center_index = new_index
        self.scroll.scroll_y = self._scroll_y_for_index(new_index)
        self._restyle_rows(new_index)
        Clock.schedule_once(self._finish_recenter, 0.04)

    def _finish_recenter(self, *_):
        self._suppress_callback = False
        self.initializing = False
        self.center_index = self._nearest_index()
        self._restyle_rows(self.center_index)
        self._set_selected(self.center_index, notify=False)


class WheelPanel(BoxLayout):
    """Three wheel columns with center band and column separators."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(rgba=RED_SOFT)
            self.center_fill = RoundedRectangle(pos=self.pos, size=(self.width, dp(56)), radius=[dp(20)])
            Color(rgba=(0.88, 0.055, 0.105, 0.96))
            self.center_border = Line(points=[], width=dp(1.2))
            Color(rgba=(0.35, 0.35, 0.38, 0.62))
            self.separator_a = Line(points=[], width=dp(0.7))
            self.separator_b = Line(points=[], width=dp(0.7))
        self.bind(pos=self._update_canvas, size=self._update_canvas)

    def _update_canvas(self, *_):
        x, y = self.pos
        width, height = self.size
        band_h = dp(56)
        band_y = y + (height - band_h) / 2
        left, right = x + dp(2), x + width - dp(2)
        self.center_fill.pos = (left, band_y)
        self.center_fill.size = (max(0, right - left), band_h)
        self.center_border.points = [
            left + dp(3), band_y, right - dp(3), band_y,
            right - dp(3), band_y + band_h, left + dp(3), band_y + band_h,
            left + dp(3), band_y,
        ]
        one, two = x + width / 3, x + 2 * width / 3
        self.separator_a.points = [one, y + dp(18), one, y + height - dp(18)]
        self.separator_b.points = [two, y + dp(18), two, y + height - dp(18)]


class TimePickerTestUI(BoxLayout):
    hour = NumericProperty(7)
    minute = NumericProperty(16)
    ampm = StringProperty("AM")
    status_text = StringProperty("Swipe any wheel to change the time")

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(18), dp(18), dp(18), dp(12)), spacing=dp(10), **kwargs)
        self.bind(size=self._resize_layout)
        self._build_ui()

    def _resize_layout(self, *_):
        # Reflow is handled by Kivy layouts; this binding intentionally keeps
        # the main card responsive as the desktop window is resized.
        pass

    def _build_ui(self):
        self.card = RoundedPanel(
            orientation="vertical", padding=(dp(22), dp(18), dp(22), dp(18)),
            spacing=dp(8), size_hint=(1, 1),
        )
        self.add_widget(self.card)

        heading = Label(
            text="SET ALARM", color=SUB, font_size="13sp", bold=True,
            halign="left", valign="middle", size_hint_y=None, height=dp(24),
        )
        heading.bind(size=lambda w, value: setattr(w, "text_size", value))
        self.card.add_widget(heading)

        preview = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(78), spacing=dp(5))
        self.time_label = Label(
            text="07:16", color=TEXT, font_size="44sp", bold=True,
            halign="left", valign="middle", size_hint_x=None, width=dp(180),
        )
        preview.add_widget(self.time_label)
        self.ampm_label = Label(
            text="AM", color=(0.78, 0.78, 0.82, 1), font_size="25sp", bold=True,
            halign="left", valign="middle", size_hint_x=None, width=dp(52),
        )
        preview.add_widget(self.ampm_label)

        dot = Widget(size_hint=(None, None), size=(dp(11), dp(11)))
        with dot.canvas.before:
            Color(rgba=RED)
            self.red_dot = Ellipse(pos=dot.pos, size=dot.size)
        dot.bind(pos=self._update_dot, size=self._update_dot)
        preview.add_widget(dot)
        preview.add_widget(Widget())
        self.card.add_widget(preview)

        self.card.add_widget(Widget(size_hint_y=1))

        self.wheel_panel = WheelPanel(size_hint_y=None, height=dp(280), spacing=0)
        self.hour_wheel = SpinnerWheel(
            list(range(1, 13)), self.hour,
            lambda value: self._change_time("hour", value),
            formatter=lambda value: "{:02d}".format(value),
        )
        self.minute_wheel = SpinnerWheel(
            list(range(60)), self.minute,
            lambda value: self._change_time("minute", value),
            formatter=lambda value: "{:02d}".format(value),
        )
        self.ampm_wheel = SpinnerWheel(
            ["AM", "PM"], self.ampm,
            lambda value: self._change_time("ampm", value),
        )
        self.wheel_panel.add_widget(self.hour_wheel)
        self.wheel_panel.add_widget(self.minute_wheel)
        self.wheel_panel.add_widget(self.ampm_wheel)
        self.card.add_widget(self.wheel_panel)

        self.card.add_widget(Widget(size_hint_y=1))

        buttons = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(12))
        buttons.add_widget(self._make_button("MORE OPTIONS", self.show_more_options, outlined=True))
        buttons.add_widget(self._make_button("DONE", self.confirm_time, outlined=False))
        self.card.add_widget(buttons)

        self.status_label = Label(
            text=self.status_text, color=SUB, font_size="12sp",
            halign="center", valign="middle", size_hint_y=None, height=dp(24),
        )
        self.add_widget(self.status_label)

    def _update_dot(self, widget, *_):
        self.red_dot.pos = widget.pos
        self.red_dot.size = widget.size

    def _make_button(self, text, callback, outlined):
        fill_color = (0.075, 0.075, 0.083, 1) if outlined else RED
        button = Button(
            text=text, background_normal="", background_down="",
            background_color=(0, 0, 0, 0), color=SUB if outlined else (1, 1, 1, 1),
            font_size="12sp", bold=True,
        )
        with button.canvas.before:
            Color(rgba=fill_color)
            fill = RoundedRectangle(pos=button.pos, size=button.size, radius=[dp(28)])
            Color(rgba=(0.32, 0.32, 0.35, 1) if outlined else fill_color)
            border = Line(points=[], width=dp(1.0))

        def update_shape(instance, *_):
            x, y = instance.pos
            w, h = instance.size
            fill.pos, fill.size = instance.pos, instance.size
            border.points = [
                x + dp(2), y + dp(1), x + w - dp(2), y + dp(1),
                x + w - dp(2), y + h - dp(1), x + dp(2), y + h - dp(1),
                x + dp(2), y + dp(1),
            ]
        button.bind(pos=update_shape, size=update_shape, on_release=lambda *_: callback())
        return button

    def _change_time(self, field, value):
        setattr(self, field, value)
        self.time_label.text = "{:02d}:{:02d}".format(self.hour, self.minute)
        self.ampm_label.text = self.ampm
        self.status_label.text = "Selected: {:02d}:{:02d} {}".format(self.hour, self.minute, self.ampm)

    def confirm_time(self):
        self.status_label.text = "Time selected for preview: {:02d}:{:02d} {}".format(
            self.hour, self.minute, self.ampm
        )

    def show_more_options(self):
        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        content.add_widget(Label(
            text="This is a standalone time-picker prototype.\nRepeat, sound and snooze are not connected to an alarm.",
            color=TEXT, halign="center", valign="middle",
        ))
        close_button = Button(
            text="GOT IT", size_hint_y=None, height=dp(46),
            background_normal="", background_color=RED, color=(1, 1, 1, 1),
        )
        content.add_widget(close_button)
        popup = Popup(
            title="MORE OPTIONS", content=content,
            size_hint=(0.82, 0.36), separator_color=RED,
            background_color=CARD, title_color=TEXT,
        )
        close_button.bind(on_release=popup.dismiss)
        popup.open()


class RedAlarmTimePickerTestApp(App):
    title = "RedAlarm — Spinning Time Picker Test"

    def build(self):
        Window.clearcolor = BG
        try:
            Window.minimum_width = 360
            Window.minimum_height = 650
        except Exception:
            pass
        return TimePickerTestUI()


if __name__ == "__main__":
    RedAlarmTimePickerTestApp().run()
