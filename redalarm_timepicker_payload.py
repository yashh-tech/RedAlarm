"""Reusable RedAlarm time-picker and editor UI widgets.

Integrated into the real RedAlarm editor by apply_redalarm_timepicker_integration.py.
The widgets own presentation and gestures; the application keeps alarm storage,
scheduling, sound persistence and ringing behavior in main.py.
"""
import math
import time
import os
import tempfile
import wave
import struct

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle, Rectangle, Triangle

BG = (0.014, 0.014, 0.017, 1)
CARD = (0.045, 0.045, 0.051, 1)
CARD_EDGE = (0.105, 0.105, 0.117, 1)
WHEEL_BG = (0.022, 0.022, 0.027, 1)
RED = (156 / 255.0, 12 / 255.0, 12 / 255.0, 1)
RED_SOFT = (0.17, 0.025, 0.028, 1)
TEXT = (0.975, 0.975, 0.985, 1)
SUB = (0.64, 0.64, 0.68, 1)
MUTED = (0.36, 0.36, 0.40, 1)
DIVIDER = (0.14, 0.14, 0.16, 1)

def add_rounded_background(widget, fill, radius=18, edge=None, edge_width=0.8):
    """Attach a resize-safe rounded rectangle background to a widget."""
    with widget.canvas.before:
        fill_instr = Color(rgba=fill)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
        edge_color = None
        edge_line = None
        if edge is not None:
            edge_color = Color(rgba=edge)
            edge_line = Line(
                rounded_rectangle=(widget.x, widget.y, widget.width, widget.height, dp(radius)),
                width=dp(edge_width),
            )

    def update(*_):
        rect.pos = widget.pos
        rect.size = widget.size
        rect.radius = [dp(radius)]
        if edge_line is not None:
            edge_line.rounded_rectangle = (
                widget.x + dp(0.5), widget.y + dp(0.5),
                max(0, widget.width - dp(1)), max(0, widget.height - dp(1)),
                dp(radius),
            )
    widget.bind(pos=update, size=update)
    return fill_instr, rect, edge_color, edge_line


class RoundedPanel(BoxLayout):
    def __init__(self, fill=CARD, radius=dp(28), **kwargs):
        super().__init__(**kwargs)
        self._fill = fill
        self._radius = radius
        with self.canvas.before:
            Color(rgba=fill)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])
            Color(rgba=CARD_EDGE)
            self._edge = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, radius),
                width=dp(0.8),
            )
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._bg.radius = [self._radius]
        self._edge.rounded_rectangle = (
            self.x + dp(0.5), self.y + dp(0.5),
            max(0, self.width - dp(1)), max(0, self.height - dp(1)),
            self._radius,
        )


class StatusDot(Widget):
    """Small alarm status dot whose circle stays centered in its widget."""
    def __init__(self, diameter=dp(11), **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (diameter, diameter))
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(rgba=(RED[0], RED[1], RED[2], 0.20))
            self.glow = Ellipse(pos=self.pos, size=(diameter * 1.9, diameter * 1.9))
            Color(rgba=RED)
            self.dot = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self.dot.pos = self.pos
        self.dot.size = self.size
        d = max(self.width, self.height) * 1.8
        self.glow.size = (d, d)
        self.glow.pos = (self.center_x - d / 2, self.center_y - d / 2)


class MusicNoteIcon(Widget):
    """Small sharp vector music-note icon; avoids missing-glyph squares."""
    def __init__(self, color=TEXT, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(20), dp(23)))
        super().__init__(**kwargs)
        self._icon_color = color
        with self.canvas:
            Color(rgba=self._icon_color)
            self._head = Ellipse(pos=self.pos, size=(dp(6), dp(4)))
            self._stem = Line(points=[], width=dp(1.7), cap="round")
            self._beam = Line(points=[], width=dp(1.7), cap="round")
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *_):
        x, y = self.pos
        w, h = self.size
        self._head.pos = (x + w * 0.12, y + h * 0.12)
        self._head.size = (dp(6), dp(4.5))
        self._stem.points = [x + w * 0.43, y + h * 0.30,
                             x + w * 0.43, y + h * 0.82]
        self._beam.points = [x + w * 0.43, y + h * 0.82,
                             x + w * 0.83, y + h * 0.90,
                             x + w * 0.83, y + h * 0.45]


class SpeakerIcon(Widget):
    """Visible vector volume icon with speaker body and sound-wave arcs."""
    def __init__(self, color=SUB, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(26), dp(24)))
        super().__init__(**kwargs)
        self.icon_color = color
        with self.canvas:
            Color(rgba=self.icon_color)
            self.body = Line(points=[], close=True, width=dp(1.45))
            self.waves = [Line(points=[], width=dp(1.4)) for _ in range(2)]
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *_):
        x, y = self.pos
        w, h = self.size
        self.body.points = [
            x + w * 0.08, y + h * 0.38,
            x + w * 0.30, y + h * 0.38,
            x + w * 0.57, y + h * 0.16,
            x + w * 0.57, y + h * 0.84,
            x + w * 0.30, y + h * 0.62,
            x + w * 0.08, y + h * 0.62,
        ]
        cx, cy = x + w * 0.55, y + h * 0.50
        for line, radius in zip(self.waves, (w * 0.22, w * 0.36)):
            pts = []
            for i in range(13):
                angle = math.radians(-55 + i * (110 / 12))
                pts.extend([cx + radius * math.cos(angle),
                            cy + radius * math.sin(angle)])
            line.points = pts


class VectorPlayButton(Button):
    """Crisp vector play/pause button; no emoji/glyph dependency or blurry icon image."""
    playing = BooleanProperty(False)

    def __init__(self, callback=None, accent=False, **kwargs):
        kwargs.setdefault("text", "")
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(36), dp(36)))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(**kwargs)
        self._accent = bool(accent)
        base = (0.13, 0.035, 0.04, 1) if accent else (0.075, 0.075, 0.085, 1)
        edge = RED if accent else (0.24, 0.24, 0.27, 1)
        with self.canvas.before:
            self._fill_color = Color(rgba=base)
            self._fill = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])
            self._edge_color = Color(rgba=edge)
            self._edge = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(18)),
                              width=dp(0.9))
        with self.canvas.after:
            self._play_color = Color(rgba=TEXT)
            self._play_triangle = Triangle(points=[0, 0, 0, 0, 0, 0])
            self._pause_color = Color(rgba=(0, 0, 0, 0))
            self._pause_a = RoundedRectangle(pos=self.pos, size=(dp(3), dp(12)), radius=[dp(1)])
            self._pause_b = RoundedRectangle(pos=self.pos, size=(dp(3), dp(12)), radius=[dp(1)])
        self.bind(pos=self._sync, size=self._sync, playing=self._sync)
        if callback:
            self.bind(on_release=lambda *_: callback())
        self._sync()

    def set_playing(self, value):
        self.playing = bool(value)

    def _sync(self, *_):
        x, y = self.pos
        w, h = self.size
        self._fill.pos, self._fill.size = self.pos, self.size
        self._fill.radius = [min(dp(18), h / 2)]
        self._edge.rounded_rectangle = (
            x + dp(0.5), y + dp(0.5), max(0, w - dp(1)),
            max(0, h - dp(1)), min(dp(17.5), h / 2),
        )
        self._fill_color.rgba = (
            (0.22, 0.035, 0.045, 1) if self.playing
            else ((0.13, 0.035, 0.04, 1) if self._accent else (0.075, 0.075, 0.085, 1))
        )
        cy = y + h / 2
        self._play_triangle.points = [
            x + w * 0.40, cy - h * 0.24,
            x + w * 0.40, cy + h * 0.24,
            x + w * 0.70, cy,
        ]
        bar_w = max(dp(2.5), w * 0.095)
        bar_h = h * 0.40
        self._pause_a.size = (bar_w, bar_h)
        self._pause_b.size = (bar_w, bar_h)
        self._pause_a.pos = (x + w * 0.36, cy - bar_h / 2)
        self._pause_b.pos = (x + w * 0.55, cy - bar_h / 2)
        self._play_color.rgba = TEXT if not self.playing else (0, 0, 0, 0)
        self._pause_color.rgba = TEXT if self.playing else (0, 0, 0, 0)


class VibrationIcon(Widget):
    """Minimal phone-and-vibration-wave icon drawn with crisp vector lines."""
    def __init__(self, color=SUB, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(23), dp(25)))
        super().__init__(**kwargs)
        self.icon_color = color
        with self.canvas:
            Color(rgba=self.icon_color)
            self.phone = Line(rounded_rectangle=(self.x, self.y, dp(9), dp(18), dp(2)),
                              width=dp(1.15))
            self.waves = [Line(points=[], width=dp(1.1)) for _ in range(2)]
            self.home_dot = Ellipse(pos=self.pos, size=(dp(1.7), dp(1.7)))
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *_):
        x, y = self.pos
        w, h = self.size
        phone_w, phone_h = w * 0.43, h * 0.76
        px, py = x + (w - phone_w) / 2, y + h * 0.12
        self.phone.rounded_rectangle = (px, py, phone_w, phone_h, dp(2))
        self.home_dot.pos = (x + w / 2 - dp(0.85), py + dp(2))
        for side, line in zip((-1, 1), self.waves):
            wx = px if side < 0 else px + phone_w
            pts = []
            for j in range(5):
                yy = py + phone_h * (0.20 + j * 0.15)
                xx = wx + side * dp(2.0 if j % 2 == 0 else 3.2)
                pts.extend([xx, yy])
            line.points = pts


# A short synthesized click gives the wheel audible feedback without an external asset.
# Four independent playback voices prevent rapid ticks from cutting one another off.
_SPINNER_TICK_SOUNDS = []
_SPINNER_TICK_LAST_AT = 0.0
_SPINNER_TICK_CURSOR = 0
_SPINNER_TICK_PATH = None


def _spinner_tick_path():
    global _SPINNER_TICK_PATH
    if _SPINNER_TICK_PATH and os.path.isfile(_SPINNER_TICK_PATH):
        return _SPINNER_TICK_PATH

    folder = os.path.join(tempfile.gettempdir(), "redalarm_timepicker_test_sounds")
    os.makedirs(folder, exist_ok=True)
    # Versioned filename ensures any older, quieter test tick is not reused.
    path = os.path.join(folder, "soft_spinner_tick_v2.wav")
    if not os.path.isfile(path):
        sample_rate = 22050
        duration = 0.032
        frames = bytearray()
        for i in range(int(sample_rate * duration)):
            t = i / float(sample_rate)
            envelope = min(1.0, t * 500.0) * math.exp(-t * 105.0)
            tone = math.sin(2.0 * math.pi * 1680.0 * t) + 0.28 * math.sin(2.0 * math.pi * 2780.0 * t)
            sample = int(13500 * envelope * tone)
            frames.extend(struct.pack("<h", max(-32768, min(32767, sample))))
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(frames))
    _SPINNER_TICK_PATH = path
    return path


def _load_spinner_tick():
    """Load separate voices so fast wheel changes do not silence every other tick."""
    global _SPINNER_TICK_SOUNDS
    if _SPINNER_TICK_SOUNDS:
        return _SPINNER_TICK_SOUNDS
    try:
        path = _spinner_tick_path()
        voices = []
        for _ in range(4):
            sound = SoundLoader.load(path)
            if sound is not None:
                sound.volume = 0.40
                voices.append(sound)
        _SPINNER_TICK_SOUNDS = voices
    except Exception as exc:
        # Audio failure must never prevent time selection.
        print("[RedAlarm test] Spinner tick audio unavailable:", exc)
        _SPINNER_TICK_SOUNDS = []
    return _SPINNER_TICK_SOUNDS


def _play_spinner_tick():
    """Play a short, audible tick when a different number crosses the center."""
    global _SPINNER_TICK_LAST_AT, _SPINNER_TICK_CURSOR
    now = time.monotonic()
    # A small debounce avoids a buzz on very fast flicks but still ticks naturally.
    if now - _SPINNER_TICK_LAST_AT < 0.036:
        return
    voices = _load_spinner_tick()
    if not voices:
        return
    sound = voices[_SPINNER_TICK_CURSOR % len(voices)]
    _SPINNER_TICK_CURSOR += 1
    try:
        sound.stop()
        sound.volume = 0.40
        sound.play()
        _SPINNER_TICK_LAST_AT = now
    except Exception as exc:
        print("[RedAlarm test] Could not play spinner tick:", exc)


class SpinnerWheel(Widget):
    """A touch/mouse-driven cylindrical wheel with inertial flick + slow snap."""
    position = NumericProperty(0.0)
    selected_text = StringProperty("")

    def __init__(self, values, selected_value, on_change, formatter=None, wrap=True, **kwargs):
        super().__init__(**kwargs)
        self.values = list(values)
        if not self.values:
            raise ValueError("SpinnerWheel requires values")
        self.period = len(self.values)
        self.wrap = bool(wrap)
        self.formatter = formatter or (lambda value: str(value))
        self.on_change = on_change
        self.row_height = dp(56)
        # Natural one-finger response: a normal drag advances the dial without feeling sticky.
        self.drag_sensitivity = 1.014  # 30% more responsive than 0.78, while velocity remains smoothed
        self.max_fling_velocity = 3.10  # cap velocity so a flick still feels controlled
        if selected_value not in self.values:
            selected_value = self.values[0]
        self._active_value = selected_value
        self.position = float(self.values.index(selected_value))
        self.selected_text = self.formatter(selected_value)
        self._labels = []
        self._dragging = False
        self._touch = None
        self._touch_start_y = 0
        self._last_y = 0
        self._last_motion_at = time.monotonic()
        self._velocity = 0.0
        self._fling_event = None
        self._settle_animation = None
        self._ready = False

        for _ in range(5):
            label = Label(
                text="", size_hint=(None, None), halign="center", valign="middle",
                color=(0.34, 0.34, 0.38, 0.25), font_size=sp(18),
            )
            self._labels.append(label)
            self.add_widget(label)
        self.bind(position=self._position_changed, pos=self._redraw, size=self._redraw)
        Clock.schedule_once(self._finish_init, 0)

    @staticmethod
    def _round_index(value):
        return int(math.floor(value + 0.5))

    def _bounded(self, value):
        if self.wrap:
            return float(value)
        return max(0.0, min(float(self.period - 1), float(value)))

    def _set_position(self, value):
        self.position = self._bounded(value)

    def set_value(self, value):
        """Set a wheel value programmatically without firing a false user change."""
        if value not in self.values:
            value = self.values[0]
        self._active_value = value
        self.selected_text = self.formatter(value)
        self.position = float(self.values.index(value))
        self._redraw()

    def _finish_init(self, *_):
        self._ready = True
        self._redraw()
        self._publish_selection()

    def _position_changed(self, *_):
        if not self._ready:
            return
        if not self.wrap:
            bounded = self._bounded(self.position)
            if abs(bounded - self.position) > 0.000001:
                self.position = bounded
                return
        self._redraw()
        self._publish_selection()

    def _publish_selection(self):
        idx = self._round_index(self.position)
        idx = idx % self.period if self.wrap else max(0, min(self.period - 1, idx))
        value = self.values[idx]
        if value != self._active_value:
            self._active_value = value
            self.selected_text = self.formatter(value)
            # Native-clock style audio feedback: one soft click per value that
            # crosses the selection center, not a continuous sound while dragging.
            _play_spinner_tick()
            if self.on_change:
                self.on_change(value)

    def _value_at(self, index):
        if self.wrap:
            return self.values[index % self.period]
        return self.values[index] if 0 <= index < self.period else None

    def _redraw(self, *_):
        if not self._labels or self.width <= 0 or self.height <= 0:
            return
        pos = self.position
        center_idx = self._round_index(pos)
        cy = self.center_y
        row_h = self.row_height
        for label, offset in zip(self._labels, (-2, -1, 0, 1, 2)):
            index = center_idx + offset
            delta = index - pos
            distance = abs(delta)
            value = self._value_at(index)
            if value is None:
                label.text = ""
                label.color = (0, 0, 0, 0)
                label.size = (dp(1), dp(1))
                label.pos = (self.center_x, self.center_y)
                continue

            # Cylindrical projection: adjacent rows bend and compress gently.
            angle = delta * 0.34
            y_center = cy - (math.sin(angle) / 0.34 * row_h)
            if distance <= 1.0:
                size_sp = 38.0 - 12.0 * distance
                alpha = 1.0 - 0.20 * distance
                grey = 0.99 - 0.25 * distance
            elif distance <= 2.0:
                d = distance - 1.0
                size_sp = 26.0 - 7.0 * d
                alpha = 0.80 - 0.56 * d
                grey = 0.74 - 0.38 * d
            else:
                size_sp, alpha, grey = 19.0, 0.20, 0.35
            squeeze = min(distance, 2.0) * dp(2.3)
            label.text = self.formatter(value)
            label.font_size = sp(size_sp)
            label.bold = distance < 0.42
            label.color = (grey, grey, min(1.0, grey + 0.025), alpha)
            label.size = (max(dp(1), self.width - squeeze * 2), row_h)
            label.pos = (self.x + squeeze, y_center - row_h / 2)
            label.text_size = label.size

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if getattr(touch, "is_mouse_scrolling", False):
            self._set_position(self.position + (1 if touch.button == "scrollup" else -1))
            self._start_settle()
            return True
        Animation.cancel_all(self, "position")
        if self._fling_event:
            self._fling_event.cancel()
            self._fling_event = None
        self._dragging = True
        self._touch = touch
        self._touch_start_y = touch.y
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
        delta_rows = ((touch.y - self._last_y) / self.row_height) * self.drag_sensitivity
        self._set_position(self.position + delta_rows)
        # Blend velocity samples and cap peak fling speed so quick mouse/touch
        # events don't send the wheel racing past several values.
        instantaneous = delta_rows / dt
        estimate = self._velocity * 0.58 + instantaneous * 0.42
        self._velocity = max(
            -self.max_fling_velocity,
            min(self.max_fling_velocity, estimate),
        )
        self._last_y = touch.y
        self._last_motion_at = now
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self or touch is not self._touch:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        self._touch = None
        self._dragging = False
        is_tap = abs(touch.y - self._touch_start_y) < dp(8)
        if not self.wrap and is_tap:
            target = self._bounded(self._round_index(self.position + (self.center_y - touch.y) / self.row_height))
            Animation.cancel_all(self, "position")
            Animation(position=float(target), duration=0.34, t="out_cubic").start(self)
            return True
        if abs(self._velocity) > 1.15:
            self._fling_event = Clock.schedule_interval(self._fling_step, 1.0 / 60.0)
        else:
            self._start_settle()
        return True

    def _fling_step(self, dt):
        if self._dragging:
            self._fling_event = None
            return False
        dt = min(float(dt), 0.04)
        # Moderate friction allows a satisfying flick, then a gradual slowdown.
        next_pos = self.position + self._velocity * dt
        if not self.wrap:
            bounded = self._bounded(next_pos)
            if abs(bounded - next_pos) > 0.000001:
                self.position = bounded
                self._velocity = 0.0
                self._fling_event = None
                self._start_settle()
                return False
        self._set_position(next_pos)
        self._velocity *= math.exp(-4.70 * dt)
        if abs(self._velocity) < 0.48:
            self._fling_event = None
            self._start_settle()
            return False
        return True

    def _start_settle(self):
        if self._fling_event:
            self._fling_event.cancel()
            self._fling_event = None
        Animation.cancel_all(self, "position")
        target = self._bounded(self._round_index(self.position))
        # Longer eased settle is intentionally gentle near the selected value.
        animation = Animation(position=float(target), duration=0.36, t="out_cubic")
        self._settle_animation = animation
        animation.start(self)


class WheelPanel(BoxLayout):
    """Opaque recessed dial with an aligned rounded red highlight."""
    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", spacing=0, **kwargs)
        with self.canvas.before:
            Color(rgba=WHEEL_BG)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(24)])
            # Keep fill subtle and opaque, same shared bounds as the outline.
            Color(rgba=RED_SOFT)
            self._fill = RoundedRectangle(pos=self.pos, size=(self.width, dp(56)), radius=[dp(20)])
            Color(rgba=(RED[0], RED[1], RED[2], 1))
            self._outline = Line(rounded_rectangle=(self.x, self.y, self.width, dp(56), dp(20)), width=dp(1.35))
            Color(rgba=(0.22, 0.22, 0.24, 0.65))
            self._div_a = Line(points=[], width=dp(0.7))
            self._div_b = Line(points=[], width=dp(0.7))
        self._fades = []
        with self.canvas.after:
            for alpha in (0.04, 0.07, 0.11, 0.16):
                Color(0.012, 0.012, 0.016, alpha)
                top = Rectangle(pos=self.pos, size=(self.width, dp(9)))
                bottom = Rectangle(pos=self.pos, size=(self.width, dp(9)))
                self._fades.extend((top, bottom))
        self.bind(pos=self._update, size=self._update)

    def _update(self, *_):
        x, y = self.pos
        w, h = self.size
        self._bg.pos, self._bg.size = self.pos, self.size
        bx, bw = x - dp(10), w + dp(20)
        by, bh, radius = self.center_y - dp(28), dp(56), dp(20)
        self._fill.pos, self._fill.size = (bx, by), (bw, bh)
        self._fill.radius = [radius]
        self._outline.rounded_rectangle = (bx, by, bw, bh, radius)
        xx1, xx2 = x + w / 3, x + (2 * w / 3)
        self._div_a.points = [xx1, y + dp(18), xx1, y + h - dp(18)]
        self._div_b.points = [xx2, y + dp(18), xx2, y + h - dp(18)]
        strip = dp(14)
        for i in range(4):
            top, bottom = self._fades[2 * i], self._fades[2 * i + 1]
            top.pos = (x, y + h - strip * (i + 1))
            bottom.pos = (x, y + strip * i)
            top.size = bottom.size = (w, strip)


class RoundedActionButton(Button):
    def __init__(self, text, callback=None, accent=False, **kwargs):
        super().__init__(
            text=text, background_normal="", background_down="",
            background_color=(0, 0, 0, 0), color=TEXT if accent else SUB,
            font_size=sp(12), bold=True, **kwargs
        )
        fill = RED if accent else (0.065, 0.065, 0.075, 1)
        border = RED if accent else (0.29, 0.29, 0.32, 1)
        with self.canvas.before:
            Color(rgba=fill)
            self._fill = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(24)])
            Color(rgba=border)
            self._border = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(24)), width=dp(1))
        def sync(*_):
            self._fill.pos, self._fill.size = self.pos, self.size
            self._border.rounded_rectangle = (
                self.x + dp(0.5), self.y + dp(0.5), max(0, self.width-dp(1)),
                max(0, self.height-dp(1)), dp(23.5)
            )
        self.bind(pos=sync, size=sync)
        if callback:
            self.bind(on_release=lambda *_: callback())


class AlarmLabelInput(TextInput):
    """Text input that reliably receives pointer focus in the custom picker UI."""
    def on_touch_down(self, touch):
        inside = self.collide_point(*touch.pos)
        handled = super().on_touch_down(touch)
        if inside:
            Clock.schedule_once(self._ensure_focus, 0.02)
            return True
        return handled

    def _ensure_focus(self, _dt):
        if self.get_root_window() is not None:
            self.focus = True


class TimePickerPage(BoxLayout):
    def __init__(self, state, on_next, on_time_change=None, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(10), dp(10), dp(10), dp(10)), **kwargs)
        self.state = state
        self.on_next = on_next
        self.on_time_change = on_time_change
        self.card = RoundedPanel(
            orientation="vertical", padding=(dp(22), dp(18), dp(22), dp(18)),
            spacing=dp(7), radius=dp(28), size_hint=(1, 1),
        )
        self.add_widget(self.card)
        self.card.add_widget(self._label("S E T   A L A R M", 13, SUB, height=24, bold=True))

        preview = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(78), spacing=dp(5))
        self.time_label = Label(
            text=self._time_string(), color=TEXT, font_size=sp(44), bold=True,
            halign="left", valign="middle", size_hint=(None, 1), width=dp(170),
        )
        self.time_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        preview.add_widget(self.time_label)
        self.ampm_label = Label(
            text=self.state["ampm"], color=(0.80, 0.80, 0.84, 1), font_size=sp(24), bold=True,
            halign="left", valign="middle", size_hint=(None, 1), width=dp(52),
        )
        self.ampm_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        preview.add_widget(self.ampm_label)
        dot_anchor = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(22))
        dot_anchor.add_widget(StatusDot(diameter=dp(11)))
        preview.add_widget(dot_anchor)
        preview.add_widget(Widget())
        self.card.add_widget(preview)


        # Editable label for this alarm (e.g. Wake up, Office, Gym). It lives in
        # the shared state so it survives page transitions and appears in summary.
        label_block = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(58), spacing=dp(3)
        )
        label_block.add_widget(self._label("ALARM LABEL", 12.0, SUB, height=17, bold=True))
        self.label_input = AlarmLabelInput(
            text=self.state.get("label", ""),
            hint_text="e.g. Wake up, Office, Gym",
            multiline=False, write_tab=False,
            background_normal="", background_active="",
            background_color=(0, 0, 0, 0),
            foreground_color=TEXT, hint_text_color=(0.43, 0.43, 0.47, 1),
            cursor_color=RED, selection_color=(RED[0], RED[1], RED[2], 0.45),
            font_size=sp(14.5), padding=(dp(12), dp(7)),
            size_hint_y=None, height=dp(35),
        )
        add_rounded_background(
            self.label_input, (0.065, 0.065, 0.075, 1), radius=13,
            edge=(0.20, 0.20, 0.23, 1), edge_width=0.8,
        )
        self.label_input.bind(text=self._label_changed)
        label_block.add_widget(self.label_input)
        self.card.add_widget(label_block)
        self.wheel_panel = WheelPanel(size_hint_y=None, height=dp(284))
        self.hour_wheel = SpinnerWheel(
            list(range(1, 13)), self.state["hour"],
            lambda value: self._change("hour", value), formatter=lambda v: str(v), wrap=True,
        )
        self.minute_wheel = SpinnerWheel(
            list(range(60)), self.state["minute"],
            lambda value: self._change("minute", value), formatter=lambda v: "{:02d}".format(v), wrap=True,
        )
        self.ampm_wheel = SpinnerWheel(
            ["AM", "PM"], self.state["ampm"],
            lambda value: self._change("ampm", value), formatter=lambda v: v, wrap=False,
        )
        for wheel in (self.hour_wheel, self.minute_wheel, self.ampm_wheel):
            self.wheel_panel.add_widget(wheel)
        self.card.add_widget(self.wheel_panel)
        self.card.add_widget(Widget(size_hint_y=None, height=dp(5)))

        action_row = BoxLayout(orientation="horizontal", spacing=dp(12), size_hint_y=None, height=dp(48))
        action_row.add_widget(RoundedActionButton("MORE OPTIONS", callback=self.on_next, accent=False))
        action_row.add_widget(RoundedActionButton("DONE", callback=self.on_next, accent=True))
        self.card.add_widget(action_row)

    @staticmethod
    def _label(text, font_size, color, height, bold=False):
        label = Label(
            text=text, color=color, font_size=sp(font_size), bold=bold,
            halign="left", valign="middle", size_hint_y=None, height=dp(height),
        )
        label.bind(size=lambda w, v: setattr(w, "text_size", v))
        return label

    def _time_string(self):
        return "{:02d}:{:02d}".format(self.state["hour"], self.state["minute"])

    def set_values(self, hour, minute, ampm, label=""):
        """Refresh the editor UI after loading a new or existing alarm."""
        self.state["hour"] = int(hour)
        self.state["minute"] = int(minute)
        self.state["ampm"] = str(ampm).upper()
        self.state["label"] = str(label or "")
        self.label_input.text = self.state["label"]
        self.hour_wheel.set_value(self.state["hour"])
        self.minute_wheel.set_value(self.state["minute"])
        self.ampm_wheel.set_value(self.state["ampm"])
        self.time_label.text = self._time_string()
        self.ampm_label.text = self.state["ampm"]

    def _label_changed(self, _widget, text):
        # Do not rewrite an in-progress edit; keep spaces while the user types.
        self.state["label"] = text

    def on_touch_down(self, touch):
        # Route taps inside the label to TextInput first, so custom sibling UI
        # cannot consume the click before the field gets keyboard focus.
        label_input = getattr(self, "label_input", None)
        if label_input is not None and label_input.collide_point(*touch.pos):
            return label_input.on_touch_down(touch)
        return super().on_touch_down(touch)

    def _change(self, key, value):
        self.state[key] = value
        self.time_label.text = self._time_string()
        self.ampm_label.text = self.state["ampm"]
        if self.on_time_change:
            self.on_time_change(self.state)


class DayPill(ToggleButton):
    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (1, None))
        kwargs.setdefault("height", dp(39))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("color", SUB)
        kwargs.setdefault("font_size", sp(12.5))
        kwargs.setdefault("bold", True)
        super().__init__(**kwargs)
        with self.canvas.before:
            self._fill_color = Color(rgba=(0.075, 0.018, 0.020, 1))
            self._fill = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(20)])
            self._edge_color = Color(rgba=(RED[0] * 0.72, RED[1] * 0.72, RED[2] * 0.72, 1))
            self._edge = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(20)), width=dp(1))
        self.bind(pos=self._sync, size=self._sync, state=self._sync)
        self._sync()

    def _sync(self, *_):
        self._fill.pos, self._fill.size = self.pos, self.size
        self._fill.radius = [dp(20)]
        self._edge.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(20))
        if self.state == "down":
            self._fill_color.rgba = RED
            self._edge_color.rgba = RED
            self.color = TEXT
        else:
            self._fill_color.rgba = (0.075, 0.018, 0.020, 1)
            self._edge_color.rgba = (RED[0] * 0.72, RED[1] * 0.72, RED[2] * 0.72, 1)
            self.color = SUB


class VolumeControl(Widget):
    """Custom volume slider, avoiding Kivy's default blue slider thumb."""
    value = NumericProperty(0.58)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            Color(rgba=(0.17, 0.17, 0.19, 1))
            self.track = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(4)])
            Color(rgba=RED)
            self.active_track = RoundedRectangle(pos=self.pos, size=(0, self.height), radius=[dp(4)])
            Color(rgba=(0.90, 0.90, 0.93, 1))
            self.thumb = Ellipse(pos=self.pos, size=(dp(18), dp(18)))
        self.bind(pos=self._sync, size=self._sync, value=self._sync)
        self._sync()
        Clock.schedule_once(lambda *_: self._sync(), 0)
        Clock.schedule_once(lambda *_: self._sync(), 0.12)

    def _sync(self, *_):
        h = dp(4)
        d = dp(18)
        y = self.center_y - h / 2
        # Inset the track by half a thumb on both ends. This keeps the red
        # active line ending exactly under the thumb, including at startup.
        track_x = self.x + d / 2
        track_w = max(0.0, self.width - d)
        self.track.pos = (track_x, y)
        self.track.size = (track_w, h)
        fill_width = max(0.0, min(track_w, track_w * float(self.value)))
        self.active_track.pos = (track_x, y)
        self.active_track.size = (fill_width, h)
        cx = track_x + fill_width
        self.thumb.pos = (cx - d / 2, self.center_y - d / 2)
        self.thumb.size = (d, d)

    def _set_from_x(self, x):
        d = dp(18)
        usable = max(1.0, self.width - d)
        if self.width > 0:
            self.value = max(0.0, min(1.0, (x - (self.x + d / 2)) / usable))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._set_from_x(touch.x)
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._set_from_x(touch.x)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._set_from_x(touch.x)
            return True
        return super().on_touch_up(touch)


class PillSwitch(Widget):
    """Compact vibration toggle with an animated knob and color transition."""
    value = BooleanProperty(True)
    progress = NumericProperty(1.0)

    def __init__(self, value=True, on_change=None, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(64), dp(29)))
        super().__init__(**kwargs)
        self.on_change = on_change
        self.value = bool(value)
        self.progress = 1.0 if self.value else 0.0
        with self.canvas.before:
            self._fill_color = Color(rgba=RED if self.value else (0.16, 0.16, 0.18, 1))
            self._fill = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(15)])
        with self.canvas.after:
            Color(rgba=(0.97, 0.97, 0.98, 1))
            self._knob = Ellipse(pos=self.pos, size=(dp(22), dp(22)))
        self.bind(pos=self._sync, size=self._sync, progress=self._sync)
        self._sync()
        Clock.schedule_once(lambda *_: self._sync(), 0)

    def on_value(self, instance, value):
        # Kivy invokes this on state changes; animate instead of jumping.
        if not hasattr(self, "_fill"):
            return
        Animation.cancel_all(self, "progress")
        Animation(
            progress=1.0 if value else 0.0,
            duration=0.19,
            t="out_cubic",
        ).start(self)

    def _sync(self, *_):
        if not hasattr(self, "_fill"):
            return
        self._fill.pos, self._fill.size = self.pos, self.size
        self._fill.radius = [self.height / 2]
        off = (0.16, 0.16, 0.18, 1)
        self._fill_color.rgba = tuple(
            off[i] + (RED[i] - off[i]) * self.progress for i in range(4)
        )
        d = min(dp(22), max(dp(10), self.height - dp(5)))
        margin = dp(3) + d / 2
        left = self.x + margin
        right = self.right - margin
        cx = left + (right - left) * self.progress
        self._knob.size = (d, d)
        self._knob.pos = (cx - d / 2, self.center_y - d / 2)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.value = not self.value
            if self.on_change:
                self.on_change(self.value)
            return True
        return super().on_touch_down(touch)


def format_duration(seconds):
    """Format seconds/minutes normally and longer durations compactly in hours.

    Examples: 30 sec, 5 min, 1 Hr, 1.25 Hr, 1.5 Hr, 1.75 Hr, 2 Hr, 3 Hr.
    Decimal-hour labels represent the exact duration (1.5 Hr = 1 hour 30 min).
    """
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "{} sec".format(seconds)
    if seconds >= 3600:
        hours = seconds / 3600.0
        label = ("{:.2f}".format(hours)).rstrip("0").rstrip(".")
        return "{} Hr".format(label)
    if seconds % 60 == 0:
        return "{} min".format(seconds // 60)
    return "{} sec".format(seconds)


def _parse_duration(text, current_value):
    """Parse custom durations such as 10s, 30 sec, 5m or 1h.

    Plain integers are interpreted as minutes to preserve familiar behavior.
    """
    value = (text or "").strip().lower().replace(" ", "")
    if not value:
        return int(current_value)
    units = [("seconds", 1), ("second", 1), ("secs", 1), ("sec", 1), ("s", 1),
             ("minutes", 60), ("minute", 60), ("mins", 60), ("min", 60), ("m", 60),
             ("hours", 3600), ("hour", 3600), ("hrs", 3600), ("hr", 3600), ("h", 3600)]
    for suffix, multiplier in units:
        if value.endswith(suffix):
            number = value[:-len(suffix)]
            return int(float(number) * multiplier)
    # A bare number means minutes.
    return int(float(value) * 60)


class DurationRow(BoxLayout):
    """Bounded duration control: seconds presets, then minutes up to 3 Hr."""
    # Numeric order is used for the +/- stepper so it behaves naturally.
    PRESETS = ([3, 5, 10, 15, 30] + [60 * m for m in range(1, 11)]
               + [15 * 60, 30 * 60] + list(range(45 * 60, 180 * 60 + 1, 15 * 60)))
    # The selection sheet presents short test intervals in the requested order.
    DISPLAY_PRESETS = ([30, 15, 10, 5, 3] + [60 * m for m in range(1, 11)]
                       + [15 * 60, 30 * 60] + list(range(45 * 60, 180 * 60 + 1, 15 * 60)))

    def __init__(self, title, subtitle, value, min_value, max_value, on_change, **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(7), **kwargs)
        self.value = int(value)
        self.min_value = int(min_value)
        self.max_value = int(max_value)
        self.on_change = on_change

        labels = BoxLayout(orientation="vertical", spacing=dp(1), size_hint_x=1)
        title_label = Label(
            text=title, color=SUB, font_size=sp(12), bold=True,
            halign="left", valign="middle", size_hint_y=None, height=dp(21),
        )
        title_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        labels.add_widget(title_label)
        sub_label = Label(
            text=subtitle, color=(0.54, 0.54, 0.58, 1), font_size=sp(10),
            halign="left", valign="middle", size_hint_y=None, height=dp(18),
        )
        sub_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        labels.add_widget(sub_label)
        self.add_widget(labels)

        # One continuous capsule; the three inner controls have no separate boxes.
        controls = BoxLayout(
            orientation="horizontal", spacing=dp(0), size_hint=(None, None),
            width=dp(148), height=dp(36), pos_hint={"center_y": 0.5},
        )
        add_rounded_background(
            controls, (0.055, 0.055, 0.063, 1), radius=18,
            edge=(0.23, 0.23, 0.26, 1), edge_width=0.8,
        )
        self.minus = Button(
            text="−", size_hint=(None, 1), width=dp(34),
            background_normal="", background_down="", background_color=(0, 0, 0, 0),
            color=TEXT, font_size=sp(18), bold=True,
        )
        self.minus.bind(on_release=lambda *_: self._step(-1))
        self.value_button = Button(
            text="", background_normal="", background_down="", background_color=(0, 0, 0, 0),
            color=TEXT, font_size=sp(11.5), bold=True, size_hint_x=1,
        )
        self.value_button.bind(on_release=self._edit_value)
        self.plus = Button(
            text="+", size_hint=(None, 1), width=dp(34),
            background_normal="", background_down="", background_color=(0, 0, 0, 0),
            color=TEXT, font_size=sp(18), bold=True,
        )
        self.plus.bind(on_release=lambda *_: self._step(1))
        controls.add_widget(self.minus)
        controls.add_widget(self.value_button)
        controls.add_widget(self.plus)
        self.add_widget(controls)
        self._refresh()

    def _allowed_presets(self):
        return [v for v in self.PRESETS if self.min_value <= v <= self.max_value]

    def _step(self, direction):
        values = self._allowed_presets()
        if direction > 0:
            next_values = [v for v in values if v > self.value]
            target = next_values[0] if next_values else self.max_value
        else:
            prev_values = [v for v in values if v < self.value]
            target = prev_values[-1] if prev_values else self.min_value
        self._set_value(target)

    def _set_value(self, value):
        self.value = max(self.min_value, min(self.max_value, int(value)))
        self._refresh()
        if self.on_change:
            self.on_change(self.value)

    def _refresh(self):
        self.value_button.text = format_duration(self.value)
        self.minus.disabled = self.value <= self.min_value
        self.plus.disabled = self.value >= self.max_value
        self.minus.opacity = 0.40 if self.minus.disabled else 1
        self.plus.opacity = 0.40 if self.plus.disabled else 1

    def _edit_value(self, *_):
        """Open a compact duration menu with seconds first, then longer periods."""
        content = BoxLayout(
            orientation="vertical", padding=dp(12), spacing=dp(8)
        )
        title = Label(
            text="CHOOSE DURATION", color=TEXT, font_size=sp(13), bold=True,
            size_hint_y=None, height=dp(24),
        )
        content.add_widget(title)

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        choices = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(8),
            padding=(0, dp(2), dp(2), dp(4)),
        )
        choices.bind(minimum_height=choices.setter("height"))

        seconds_title = Label(
            text="SECONDS", color=SUB, font_size=sp(10.5), bold=True,
            halign="left", valign="middle", size_hint_y=None, height=dp(18),
        )
        seconds_title.bind(size=lambda w, v: setattr(w, "text_size", v))
        choices.add_widget(seconds_title)

        second_values = [30, 15, 10, 5, 3]
        seconds_grid = GridLayout(
            cols=3, spacing=dp(6), padding=0,
            size_hint_y=None, row_default_height=dp(36), row_force_default=True,
        )
        seconds_grid.height = math.ceil(len(second_values) / 3.0) * dp(36) + dp(6)
        for value in second_values:
            button = RoundedActionButton(
                format_duration(value),
                callback=lambda val=value: self._choose_preset(val, popup),
                accent=(value == self.value), size_hint_y=None, height=dp(36),
            )
            seconds_grid.add_widget(button)
        choices.add_widget(seconds_grid)

        minutes_title = Label(
            text="MINUTES / HOURS", color=SUB, font_size=sp(10.5), bold=True,
            halign="left", valign="middle", size_hint_y=None, height=dp(18),
        )
        minutes_title.bind(size=lambda w, v: setattr(w, "text_size", v))
        choices.add_widget(minutes_title)

        longer_values = ([60 * m for m in range(1, 11)] + [15 * 60, 30 * 60]
                         + list(range(45 * 60, 180 * 60 + 1, 15 * 60)))
        longer_grid = GridLayout(
            cols=3, spacing=dp(6), padding=0,
            size_hint_y=None, row_default_height=dp(36), row_force_default=True,
        )
        longer_grid.height = math.ceil(len(longer_values) / 3.0) * dp(36) + dp(6)
        for value in longer_values:
            button = RoundedActionButton(
                format_duration(value),
                callback=lambda val=value: self._choose_preset(val, popup),
                accent=(value == self.value), size_hint_y=None, height=dp(36),
            )
            longer_grid.add_widget(button)
        choices.add_widget(longer_grid)
        scroll.add_widget(choices)
        content.add_widget(scroll)

        footer = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(8)
        )
        custom = RoundedActionButton(
            "CUSTOM…", callback=lambda: self._open_custom_duration(popup),
            accent=True, size_hint_x=1,
        )
        close = RoundedActionButton(
            "CLOSE", callback=lambda: popup.dismiss(), accent=False,
            size_hint_x=None, width=dp(92),
        )
        footer.add_widget(custom)
        footer.add_widget(close)
        content.add_widget(footer)

        popup = Popup(
            title="", content=content, size_hint=(0.84, 0.78),
            background_color=CARD, separator_height=0, auto_dismiss=True,
        )
        popup.open()

    def _choose_preset(self, value, popup):
        self._set_value(value)
        popup.dismiss()

    def _open_custom_duration(self, parent_popup):
        parent_popup.dismiss()
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(9))
        hint = Label(
            text="Enter seconds, minutes or hours\nExamples: 10s, 30s, 5m, 1h",
            color=SUB, font_size=sp(12), halign="center", valign="middle",
            size_hint_y=None, height=dp(42),
        )
        content.add_widget(hint)
        entry = TextInput(
            text=format_duration(self.value).replace(" sec", "s").replace(" min", "m").replace(" Hr", "h"),
            hint_text="e.g. 30s or 5m", multiline=False,
            size_hint_y=None, height=dp(42), font_size=sp(17), halign="center",
            background_normal="", background_active="", background_color=(0.08, 0.08, 0.09, 1),
            foreground_color=TEXT, cursor_color=RED,
        )
        content.add_widget(entry)
        row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(
            title="CUSTOM DURATION", title_color=TEXT, separator_color=RED,
            content=content, size_hint=(0.82, 0.34), background_color=CARD,
            auto_dismiss=True,
        )

        def apply_value():
            try:
                value = _parse_duration(entry.text, self.value)
            except (ValueError, TypeError, OverflowError):
                value = self.value
            self._set_value(max(self.min_value, min(self.max_value, value)))
            popup.dismiss()

        row.add_widget(RoundedActionButton("CANCEL", callback=popup.dismiss, accent=False))
        row.add_widget(RoundedActionButton("APPLY", callback=apply_value, accent=True))
        content.add_widget(row)
        popup.open()



class AlarmAppSettingsPage(BoxLayout):
    """Compact settings page wired directly to the real AlarmEditScreen."""
    DAYS = [("M", "Mon"), ("T", "Tue"), ("W", "Wed"),
            ("T", "Thu"), ("F", "Fri"), ("S", "Sat"), ("S", "Sun")]

    def __init__(self, editor, on_back, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(8), dp(8), dp(8), dp(8)), **kwargs)
        self.editor = editor
        self.on_back = on_back
        self.day_buttons = []
        self._build()

    def _label(self, text, size=12, color=SUB, bold=False, height=dp(20), halign="left"):
        label = Label(text=text, color=color, font_size=sp(size), bold=bold,
                      halign=halign, valign="middle", size_hint_y=None, height=height)
        label.bind(size=lambda w, v: setattr(w, "text_size", v))
        return label

    def _separator(self):
        line = Widget(size_hint_y=None, height=dp(1))
        with line.canvas.before:
            Color(rgba=DIVIDER)
            line.rect = Rectangle(pos=line.pos, size=line.size)
        line.bind(pos=lambda w, *_: setattr(w.rect, "pos", w.pos),
                  size=lambda w, *_: setattr(w.rect, "size", w.size))
        return line

    def _build(self):
        self.card = RoundedPanel(fill=CARD, radius=dp(26), orientation="vertical",
                                 padding=(dp(16), dp(12), dp(16), dp(12)),
                                 spacing=dp(5), size_hint=(1, 1))
        self.add_widget(self.card)

        header = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(106), spacing=dp(1))
        header.add_widget(self._label("A L A R M   S E T T I N G S", 12.5, SUB, True, dp(21)))
        preview = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(70), spacing=dp(5))
        self.time_label = Label(text="07:16", color=TEXT, font_size=sp(44), bold=True,
                                halign="left", valign="middle", size_hint=(None, 1), width=dp(174))
        self.time_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        preview.add_widget(self.time_label)
        self.ampm_label = Label(text="AM", color=(0.82, 0.82, 0.85, 1), font_size=sp(24), bold=True,
                                halign="left", valign="middle", size_hint=(None, 1), width=dp(48))
        self.ampm_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        preview.add_widget(self.ampm_label)
        dot = StatusDot(diameter=dp(10), size_hint=(None, None))
        dot_wrap = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(20))
        dot_wrap.add_widget(dot)
        preview.add_widget(dot_wrap)
        preview.add_widget(Widget())
        header.add_widget(preview)
        self.card.add_widget(header)
        self.alarm_label_summary = self._label("Alarm", 10.5, MUTED, False, dp(17))
        self.card.add_widget(self.alarm_label_summary)
        self.card.add_widget(self._separator())

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=0,
                            scroll_type=["content"], size_hint=(1, 1), scroll_y=1.0)
        self.content = BoxLayout(orientation="vertical", size_hint_y=None,
                                 spacing=dp(5), padding=(0, dp(3), 0, dp(4)))
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.card.add_widget(scroll)

        repeat = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(72), spacing=dp(3))
        repeat.add_widget(self._label("REPEAT", 11.5, SUB, True, dp(18)))
        repeat.add_widget(self._label("Once if no days are selected", 10.5, TEXT, False, dp(16)))
        day_row = BoxLayout(orientation="horizontal", spacing=dp(5), size_hint_y=None, height=dp(34))
        for index, (short, full) in enumerate(self.DAYS):
            button = DayPill(text=short, height=dp(34), size_hint=(1, None))
            button.bind(state=lambda inst, state, i=index: self.editor.set_day(i, state == "down"))
            self.day_buttons.append(button)
            day_row.add_widget(button)
        repeat.add_widget(day_row)
        self.content.add_widget(repeat)
        self.content.add_widget(self._separator())

        sound_block = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(78), spacing=dp(3))
        sound_block.add_widget(self._label("SOUND", 11.5, SUB, True, dp(18)))
        sound_row = BoxLayout(orientation="horizontal", spacing=dp(7), size_hint_y=None, height=dp(38))
        note_holder = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(25))
        note_holder.add_widget(MusicNoteIcon(color=RED, size=(dp(20), dp(23))))
        sound_row.add_widget(note_holder)
        self.sound_name_label = Label(text="Default beep", color=TEXT, font_size=sp(12), bold=True,
                                      halign="left", valign="middle", size_hint_x=1)
        self.sound_name_label.bind(size=lambda w, v: setattr(w, "text_size", v))
        sound_row.add_widget(self.sound_name_label)
        self.preview_button = VectorPlayButton(callback=self.editor.preview_sound,
                                               size_hint=(None, None), size=(dp(34), dp(34)))
        sound_row.add_widget(self.preview_button)
        choose = RoundedActionButton("CHOOSE", callback=self.editor.choose_sound,
                                     accent=True, size_hint=(None, None), size=(dp(80), dp(34)))
        choose.font_size = sp(9.5)
        sound_row.add_widget(choose)
        sound_block.add_widget(sound_row)
        self.content.add_widget(sound_block)

        volume_row = BoxLayout(orientation="horizontal", spacing=dp(8),
                               size_hint_y=None, height=dp(38))
        speaker_holder = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(27))
        speaker_holder.add_widget(SpeakerIcon(color=SUB, size=(dp(25), dp(24))))
        volume_row.add_widget(speaker_holder)
        self.volume_control = VolumeControl(value=float(getattr(self.editor, "volume", 0.80)),
                                            size_hint=(1, 1))
        self.volume_control.bind(value=self._volume_changed)
        volume_row.add_widget(self.volume_control)
        volume_row.add_widget(self._label("VOL", 9.5, SUB, True, dp(18), halign="right"))
        self.content.add_widget(volume_row)
        self.content.add_widget(self._separator())

        vibration = BoxLayout(orientation="horizontal", spacing=dp(8),
                              size_hint_y=None, height=dp(40))
        vib_holder = AnchorLayout(anchor_x="center", anchor_y="center", size_hint=(None, 1), width=dp(28))
        vib_holder.add_widget(VibrationIcon(color=SUB, size=(dp(23), dp(25))))
        vibration.add_widget(vib_holder)
        vib_title = self._label("Vibration", 12, TEXT, False, dp(26))
        vib_title.size_hint_x = 1
        vibration.add_widget(vib_title)
        self.vibration_switch = PillSwitch(value=bool(self.editor.vibrate),
                                           on_change=self._vibration_changed,
                                           size=(dp(60), dp(27)))
        vibration.add_widget(self.vibration_switch)
        self.content.add_widget(vibration)
        self.content.add_widget(self._separator())

        self.dismiss_control = DurationRow(
            "AUTO-DISMISS", "Stop alarm automatically", int(self.editor.auto_dismiss_sec),
            3, 10800, lambda val: setattr(self.editor, "auto_dismiss_sec", val),
            size_hint_y=None, height=dp(58),
        )
        self.content.add_widget(self.dismiss_control)
        self.content.add_widget(self._separator())
        self.snooze_control = DurationRow(
            "SNOOZE", "Repeat alarm after", int(self.editor.snooze_sec),
            3, 10800, lambda val: setattr(self.editor, "snooze_sec", val),
            size_hint_y=None, height=dp(58),
        )
        self.content.add_widget(self.snooze_control)
        self.content.add_widget(self._separator())
        self.error_label = self._label("", 11.5, RED, False, dp(20))
        self.content.add_widget(self.error_label)

        self.footer = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(46), spacing=dp(10))
        self.footer.add_widget(RoundedActionButton("BACK", callback=self.on_back, accent=False))
        self.delete_button = RoundedActionButton(
            "DELETE", callback=self.editor.delete_alarm, accent=False,
            size_hint_x=None, width=dp(82),
        )
        self.done_button = RoundedActionButton("DONE", callback=self.editor.save_alarm, accent=True)
        self.footer.add_widget(self.done_button)
        self.card.add_widget(self.footer)
        Clock.schedule_once(lambda *_: self.refresh_from_editor(), 0)

    def _volume_changed(self, _widget, value):
        self.editor.volume = max(0.0, min(1.0, float(value)))

    def _vibration_changed(self, value):
        self.editor.vibrate = bool(value)

    def refresh_time(self):
        state = self.editor.time_state
        self.time_label.text = "{:02d}:{:02d}".format(int(state["hour"]), int(state["minute"]))
        self.ampm_label.text = state["ampm"]
        self.alarm_label_summary.text = (state.get("label") or "Alarm").strip() or "Alarm"

    def refresh_sound(self):
        self.sound_name_label.text = self.editor.sound_name or "Default beep"

    def refresh_days(self):
        for i, button in enumerate(self.day_buttons):
            desired = "down" if self.editor.days_selected[i] else "normal"
            if button.state != desired:
                button.state = desired

    def refresh_from_editor(self):
        self.refresh_time()
        self.refresh_sound()
        self.refresh_days()
        self.volume_control.value = float(self.editor.volume)
        self.vibration_switch.value = bool(self.editor.vibrate)
        self.dismiss_control._set_value(int(self.editor.auto_dismiss_sec))
        self.snooze_control._set_value(int(self.editor.snooze_sec))
        self.error_label.text = self.editor.error_message
        # Keep the legacy delete feature available only when editing a saved alarm.
        editing_existing = bool(self.editor.editing_id)
        if editing_existing and self.delete_button.parent is None:
            self.footer.add_widget(self.delete_button, index=1)
        elif not editing_existing and self.delete_button.parent is self.footer:
            self.footer.remove_widget(self.delete_button)


class AlarmEditorUI(ScreenManager):
    """The real app's two-page alarm editor with an animated slide transition."""
    def __init__(self, editor, **kwargs):
        kwargs.setdefault("transition", SlideTransition(duration=0.28, direction="left"))
        super().__init__(**kwargs)
        self.editor = editor
        self.picker_screen = Screen(name="picker")
        self.settings_screen = Screen(name="settings")
        self.picker_page = TimePickerPage(
            editor.time_state, self.show_settings,
            on_time_change=editor._picker_state_changed,
        )
        self.settings_page = AlarmAppSettingsPage(editor, self.show_picker)
        self.picker_screen.add_widget(self.picker_page)
        self.settings_screen.add_widget(self.settings_page)
        self.add_widget(self.picker_screen)
        self.add_widget(self.settings_screen)
        self.current = "picker"

    def show_settings(self):
        self.settings_page.refresh_from_editor()
        self.transition.direction = "left"
        self.current = "settings"

    def show_picker(self):
        self.transition.direction = "right"
        self.current = "picker"
