"""Standalone RedAlarm 3D-style spinning time picker prototype.

Run with the Python installation that has Kivy installed:
    python RedAlarm_TimePicker_Test.py

This is a UI-only tester. It does not modify main.py or schedule alarms.
"""

import math
import time

from kivy.config import Config
Config.set("graphics", "width", "440")
Config.set("graphics", "height", "820")
Config.set("graphics", "resizable", "1")

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle, Rectangle


# RedAlarm dark palette.
BG = (0.018, 0.018, 0.022, 1)
CARD = (0.050, 0.050, 0.057, 1)
CARD_EDGE = (0.095, 0.095, 0.105, 1)
RED = (0.88, 0.035, 0.085, 1)
RED_SOFT = (0.30, 0.018, 0.035, 0.76)
TEXT = (0.975, 0.975, 0.985, 1)
SUB = (0.63, 0.63, 0.67, 1)


class RoundedPanel(BoxLayout):
    """BoxLayout with a dark rounded background and subtle edge."""

    def __init__(self, fill=CARD, radius=dp(28), **kwargs):
        super().__init__(**kwargs)
        self._fill = fill
        self._radius = radius
        with self.canvas.before:
            Color(rgba=self._fill)
            self._background = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self._radius]
            )
            Color(rgba=CARD_EDGE)
            self._edge = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._radius),
                width=dp(0.7),
            )
        self.bind(pos=self._sync_background, size=self._sync_background)

    def _sync_background(self, *_):
        self._background.pos = self.pos
        self._background.size = self.size
        self._background.radius = [self._radius]
        self._edge.rounded_rectangle = (
            self.x, self.y, self.width, self.height, self._radius
        )


class SpinnerWheel(Widget):
    """Custom wheel: fixed shared center, curved/fading rows, fling and snap.

    Unlike three independent ScrollViews, every value is positioned from the
    same center coordinate. This prevents one column drifting out of alignment.
    """

    position = NumericProperty(0.0)
    selected_text = StringProperty("")

    def __init__(self, values, selected_value, on_change,
                 formatter=None, **kwargs):
        super().__init__(**kwargs)
        self.values = list(values)
        if not self.values:
            raise ValueError("SpinnerWheel needs at least one value")
        self.period = len(self.values)
        self.formatter = formatter or (lambda value: str(value))
        self.on_change = on_change
        self.row_height = dp(56)
        self._active_value = selected_value if selected_value in self.values else self.values[0]
        self._center_index = self.values.index(self._active_value)
        # Start every wheel with its selected value at the true visual center.
        # Without this, the wheel can initially show 1/00 while the preview
        # reports a different time.
        self.position = float(self._center_index)
        self._dragging = False
        self._touch = None
        self._last_y = 0.0
        self._last_motion_at = time.monotonic()
        self._velocity = 0.0  # rows per second; positive advances to the next value
        self._fling_event = None
        self._settle_animation = None
        self._initialized = False
        self._labels = []
        self.selected_text = self.formatter(self._active_value)

        # Five carefully positioned labels make the cylindrical wheel readable.
        for _ in range(5):
            label = Label(
                text="",
                size_hint=(None, None),
                halign="center",
                valign="middle",
                color=(0.34, 0.34, 0.37, 0.28),
                font_size=sp(18),
            )
            self._labels.append(label)
            self.add_widget(label)

        self.bind(position=self._on_position, pos=self._redraw, size=self._redraw)
        Clock.schedule_once(self._finish_init, 0)

    def _finish_init(self, *_):
        self._initialized = True
        self._redraw()
        self._publish_selection()

    def _on_position(self, *_):
        if not self._initialized:
            return
        self._redraw()
        self._publish_selection()

    def _publish_selection(self):
        index = int(round(self.position))
        value = self.values[index % self.period]
        if value != self._active_value:
            self._active_value = value
            self.selected_text = self.formatter(value)
            if self.on_change:
                self.on_change(value)

    def _redraw(self, *_):
        if not self._labels:
            return
        if self.width <= 0 or self.height <= 0:
            return

        floating_center = self.position
        nearest_center = int(round(floating_center))
        self._center_index = nearest_center
        center_x = self.center_x
        center_y = self.center_y
        row_h = self.row_height
        label_h = row_h
        label_w = self.width

        # Offset order is consistent for all columns: prior values above,
        # following values below. Each row shares the exact same center band.
        for label, visual_offset in zip(self._labels, (2, 1, 0, -1, -2)):
            absolute_index = nearest_center + visual_offset
            value = self.values[absolute_index % self.period]
            delta = absolute_index - floating_center
            distance = abs(delta)

            # Mild cylindrical curvature: outer rows compress toward the wheel.
            angle = delta * 0.34
            curved_distance = math.sin(angle) / 0.34 * row_h
            y_center = center_y - curved_distance

            # Values shrink and fade as they rotate away from the viewer.
            if distance < 1.0:
                t = distance
                size_sp = 33.0 - 8.0 * t
                alpha = 1.0 - 0.22 * t
                grey = 0.98 - 0.26 * t
            elif distance < 2.0:
                t = distance - 1.0
                size_sp = 25.0 - 6.0 * t
                alpha = 0.78 - 0.38 * t
                grey = 0.72 - 0.27 * t
            else:
                size_sp = 18.0
                alpha = 0.23
                grey = 0.34

            # Slight horizontal inward movement gives the rows a barrel-like feel.
            inward = min(distance, 2.0) * dp(1.8)
            row_x = self.x + inward
            row_width = max(dp(1), self.width - inward * 2)

            label.text = self.formatter(value)
            label.font_size = sp(size_sp)
            label.color = (grey, grey, min(1.0, grey + 0.02), alpha)
            label.size = (row_width, label_h)
            label.pos = (row_x, y_center - label_h / 2.0)
            label.text_size = label.size

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        # Mouse wheel support on desktop for quick testing.
        if getattr(touch, "is_mouse_scrolling", False):
            if getattr(touch, "button", "") == "scrollup":
                self.position += 1.0
            elif getattr(touch, "button", "") == "scrolldown":
                self.position -= 1.0
            self._start_settle()
            return True

        Animation.cancel_all(self, "position")
        if self._fling_event is not None:
            self._fling_event.cancel()
            self._fling_event = None

        self._dragging = True
        self._touch = touch
        self._last_y = touch.y
        self._last_motion_at = time.monotonic()
        self._velocity = 0.0
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self or touch is not self._touch:
            return super().on_touch_move(touch)

        now = time.monotonic()
        dt = max(0.001, now - self._last_motion_at)
        dy = touch.y - self._last_y
        self.position += dy / self.row_height
        self._velocity = (dy / self.row_height) / dt
        self._last_y = touch.y
        self._last_motion_at = now
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self or touch is not self._touch:
            return super().on_touch_up(touch)

        touch.ungrab(self)
        self._touch = None
        self._dragging = False

        # A quick swipe carries momentum, followed by an animated center snap.
        if abs(self._velocity) > 1.15:
            self._fling_event = Clock.schedule_interval(self._fling_step, 1 / 60.0)
        else:
            self._start_settle()
        return True

    def _fling_step(self, dt):
        if self._dragging:
            self._fling_event = None
            return False

        dt = min(dt, 0.04)
        self.position += self._velocity * dt
        self._velocity *= math.exp(-4.2 * dt)

        if abs(self._velocity) < 0.55:
            self._fling_event = None
            self._start_settle()
            return False
        return True

    def _start_settle(self):
        if self._fling_event is not None:
            self._fling_event.cancel()
            self._fling_event = None
        Animation.cancel_all(self, "position")
        target = float(round(self.position))
        animation = Animation(position=target, duration=0.20, t="out_cubic")
        self._settle_animation = animation
        animation.start(self)


class WheelPanel(BoxLayout):
    """Three equal columns and one shared red center highlight."""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", spacing=0, **kwargs)
        with self.canvas.before:
            Color(rgba=(0.028, 0.028, 0.033, 0.98))
            self._background = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(24)]
            )
            Color(rgba=RED_SOFT)
            self._center_fill = RoundedRectangle(
                pos=self.pos, size=(self.width, dp(56)), radius=[dp(18)]
            )
            Color(rgba=(0.86, 0.035, 0.085, 0.98))
            self._center_border = Line(points=[], width=dp(1.25))
            Color(rgba=(0.28, 0.28, 0.30, 0.58))
            self._divider_a = Line(points=[], width=dp(0.7))
            self._divider_b = Line(points=[], width=dp(0.7))

        # Faux top/bottom shading on top of the children suggests a recessed
        # cylindrical wheel. Several thin bands approximate a soft gradient.
        with self.canvas.after:
            self._fade_colors = []
            self._fade_rects = []
            for alpha in (0.17, 0.10, 0.045):
                Color(0.015, 0.015, 0.019, alpha)
                top = Rectangle(pos=self.pos, size=(self.width, dp(9)))
                bottom = Rectangle(pos=self.pos, size=(self.width, dp(9)))
                self._fade_rects.extend([top, bottom])
                self._fade_colors.append(alpha)

        self.bind(pos=self._update_canvas, size=self._update_canvas)

    def _update_canvas(self, *_):
        x, y = self.pos
        width, height = self.size
        self._background.pos = self.pos
        self._background.size = self.size
        self._center_fill.pos = (x + dp(2), self.center_y - dp(28))
        self._center_fill.size = (max(0, width - dp(4)), dp(56))

        left = x + dp(4)
        right = x + width - dp(4)
        band_y = self.center_y - dp(28)
        self._center_border.points = [
            left + dp(5), band_y,
            right - dp(5), band_y,
            right - dp(5), band_y + dp(56),
            left + dp(5), band_y + dp(56),
            left + dp(5), band_y,
        ]

        one_x = x + width / 3.0
        two_x = x + width * 2.0 / 3.0
        self._divider_a.points = [one_x, y + dp(18), one_x, y + height - dp(18)]
        self._divider_b.points = [two_x, y + dp(18), two_x, y + height - dp(18)]

        # Three shallow shadow bands at both ends; keep the central selection clear.
        band_h = dp(12)
        for i in range(3):
            top_rect = self._fade_rects[i * 2]
            bottom_rect = self._fade_rects[i * 2 + 1]
            top_rect.pos = (x, y + height - band_h * (i + 1))
            bottom_rect.pos = (x, y + band_h * i)
            top_rect.size = (width, band_h)
            bottom_rect.size = (width, band_h)


class TimePickerTestUI(BoxLayout):
    hour = NumericProperty(7)
    minute = NumericProperty(16)
    ampm = StringProperty("AM")
    status_text = StringProperty("Swipe a wheel to spin it")

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=(dp(18), dp(16), dp(18), dp(10)),
            spacing=dp(8),
            **kwargs
        )
        self._build_ui()

    def _build_ui(self):
        self.card = RoundedPanel(
            orientation="vertical",
            padding=(dp(26), dp(20), dp(26), dp(20)),
            spacing=dp(8),
            size_hint=(1, 1),
        )
        self.add_widget(self.card)

        heading = Label(
            text="S E T   A L A R M",
            color=SUB,
            font_size=sp(13),
            bold=True,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(28),
        )
        heading.bind(size=lambda widget, value: setattr(widget, "text_size", value))
        self.card.add_widget(heading)

        preview = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(82),
            spacing=dp(6),
        )
        self.time_label = Label(
            text="07:16",
            color=TEXT,
            font_size=sp(43),
            bold=True,
            halign="left",
            valign="middle",
            size_hint_x=None,
            width=dp(184),
        )
        preview.add_widget(self.time_label)

        self.ampm_label = Label(
            text="AM",
            color=(0.80, 0.80, 0.83, 1),
            font_size=sp(24),
            bold=True,
            halign="left",
            valign="middle",
            size_hint_x=None,
            width=dp(50),
        )
        preview.add_widget(self.ampm_label)

        dot = Widget(size_hint=(None, None), size=(dp(11), dp(11)))
        with dot.canvas.before:
            Color(rgba=RED)
            self._dot = Ellipse(pos=dot.pos, size=dot.size)
        dot.bind(pos=self._update_dot, size=self._update_dot)
        preview.add_widget(dot)
        preview.add_widget(Widget())
        self.card.add_widget(preview)

        self.card.add_widget(Widget(size_hint_y=1))

        self.wheel_panel = WheelPanel(size_hint_y=None, height=dp(300))
        self.hour_wheel = SpinnerWheel(
            list(range(1, 13)), self.hour,
            lambda value: self._change_time("hour", value),
            # Picker rows use natural numbers: 1, 2, 3 ... rather than 01, 02, 03.
            formatter=lambda value: str(value),
        )
        self.minute_wheel = SpinnerWheel(
            list(range(60)), self.minute,
            lambda value: self._change_time("minute", value),
            # Keep the wheel values natural (01 becomes 1) for consistency.
            formatter=lambda value: str(value),
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

        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(14),
        )
        buttons.add_widget(
            self._make_button("MORE OPTIONS", self.show_more_options, outlined=True)
        )
        buttons.add_widget(
            self._make_button("DONE", self.confirm_time, outlined=False)
        )
        self.card.add_widget(buttons)

        self.status_label = Label(
            text=self.status_text,
            color=SUB,
            font_size=sp(11),
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(22),
        )
        self.add_widget(self.status_label)

    def _update_dot(self, widget, *_):
        self._dot.pos = widget.pos
        self._dot.size = widget.size

    def _make_button(self, text, callback, outlined):
        fill_color = (0.075, 0.075, 0.083, 1) if outlined else RED
        button = Button(
            text=text,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=SUB if outlined else (1, 1, 1, 1),
            font_size=sp(12),
            bold=True,
        )
        with button.canvas.before:
            Color(rgba=fill_color)
            fill = RoundedRectangle(pos=button.pos, size=button.size, radius=[dp(28)])
            Color(rgba=(0.32, 0.32, 0.35, 1) if outlined else fill_color)
            border = Line(points=[], width=dp(1.0))

        def update_shape(instance, *_):
            x, y = instance.pos
            width, height = instance.size
            fill.pos, fill.size = instance.pos, instance.size
            border.points = [
                x + dp(2), y + dp(1),
                x + width - dp(2), y + dp(1),
                x + width - dp(2), y + height - dp(1),
                x + dp(2), y + height - dp(1),
                x + dp(2), y + dp(1),
            ]

        button.bind(pos=update_shape, size=update_shape)
        button.bind(on_release=lambda *_: callback())
        return button

    def _change_time(self, field, value):
        setattr(self, field, value)
        self.time_label.text = "{:02d}:{:02d}".format(self.hour, self.minute)
        self.ampm_label.text = self.ampm
        self.status_label.text = "Selected: {:02d}:{:02d} {}".format(
            self.hour, self.minute, self.ampm
        )

    def confirm_time(self):
        self.status_label.text = "Preview time: {:02d}:{:02d} {}".format(
            self.hour, self.minute, self.ampm
        )

    def show_more_options(self):
        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        content.add_widget(Label(
            text=(
                "Standalone time-picker prototype.\n"
                "Repeat, sound, snooze and alarm saving are not connected."
            ),
            color=TEXT,
            halign="center",
            valign="middle",
        ))
        close_button = Button(
            text="GOT IT",
            size_hint_y=None,
            height=dp(46),
            background_normal="",
            background_color=RED,
            color=(1, 1, 1, 1),
        )
        content.add_widget(close_button)
        popup = Popup(
            title="MORE OPTIONS",
            content=content,
            size_hint=(0.82, 0.36),
            separator_color=RED,
            background_color=CARD,
            title_color=TEXT,
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
