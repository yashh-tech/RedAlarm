"""RedAlarm - Kivy alarm clock.

The app keeps the existing four-screen UI architecture while moving Android
alarm delivery to AlarmManager + a native BroadcastReceiver. All Python-side
alarm state, ringtone resolution, vibration, notification actions, and
Dismiss/Snooze behavior still live in this one main.py file.
"""

import datetime
import hashlib
import json
import math
import os
import traceback
import uuid
import wave
import struct

from kivy.animation import Animation
from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

APP_TITLE = "Red Alarm"
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ANDROID = platform == "android"

ANDROID_FIRE_ACTION = "com.redalarm.ACTION_ALARM_FIRE"
ANDROID_NOTIF_DISMISS_ACTION = "com.redalarm.NOTIF_DISMISS"
ANDROID_NOTIF_SNOOZE_ACTION = "com.redalarm.NOTIF_SNOOZE"
ANDROID_NOTIF_OPEN_ACTION = "com.redalarm.NOTIF_OPEN"


# ======================================================================
# Helpers
# ======================================================================

def new_alarm_id():
    return uuid.uuid4().hex


def format_time(hour, minute):
    ampm = "PM" if int(hour) >= 12 else "AM"
    h12 = int(hour) % 12 or 12
    return "{:02d}:{:02d} {}".format(h12, int(minute), ampm)


def format_days(days):
    if not days or not any(days):
        return "One-time"
    if all(days):
        return "Every day"
    return ", ".join(name for name, on in zip(DAY_NAMES, days) if on)


def compute_next_trigger_dt(alarm, now=None):
    now = now or datetime.datetime.now()
    hour = int(alarm.get("hour", 7) or 0)
    minute = int(alarm.get("minute", 0) or 0)
    days = alarm.get("days") or [False] * 7

    if not any(days):
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += datetime.timedelta(days=1)
        return candidate

    for add in range(0, 8):
        day = now + datetime.timedelta(days=add)
        if days[day.weekday()]:
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                return candidate
    return now + datetime.timedelta(days=7)


def stable_request_code(alarm_id, salt=""):
    digest = hashlib.md5((alarm_id + salt).encode("utf-8")).hexdigest()
    return int(digest[:7], 16) % 1_000_000


class _CrashLogger(ExceptionHandler):
    def __init__(self, log_path):
        super().__init__()
        self.log_path = log_path

    def handle_exception(self, inst):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write("\n---- {} ----\n".format(datetime.datetime.now()))
                traceback.print_exc(file=f)
        except Exception:
            pass
        return ExceptionManager.PASS


# ======================================================================
# Android bridge
# ======================================================================
if ANDROID:
    from jnius import autoclass, cast
    from android import activity as android_activity
    from android.permissions import Permission, request_permissions

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    AlarmReceiver = autoclass("org.kivy.android.KivyAlarmReceiver")
    Intent = autoclass("android.content.Intent")
    PendingIntent = autoclass("android.app.PendingIntent")
    Context = autoclass("android.content.Context")
    AlarmManager = autoclass("android.app.AlarmManager")
    AlarmClockInfo = autoclass("android.app.AlarmManager$AlarmClockInfo")
    PowerManager = autoclass("android.os.PowerManager")
    Build = autoclass("android.os.Build")
    Settings = autoclass("android.provider.Settings")
    Uri = autoclass("android.net.Uri")
    WindowManagerFlags = autoclass("android.view.WindowManager$LayoutParams")
    JString = autoclass("java.lang.String")

    _wake_lock = [None]
    _OPEN_DOCUMENT_REQUEST_CODE = 9001
    _RINGING_NOTIFICATION_ID = 2001

    def _activity():
        return PythonActivity.mActivity

    def _alarm_manager():
        return cast(
            "android.app.AlarmManager",
            _activity().getSystemService(Context.ALARM_SERVICE),
        )

    def _alarm_activity_pending_intent(alarm_id, action, request_code, fire_token=None):
        intent = Intent(_activity().getApplicationContext(), PythonActivity)
        intent.setAction(JString(action))
        intent.setFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK
            | Intent.FLAG_ACTIVITY_CLEAR_TOP
            | Intent.FLAG_ACTIVITY_SINGLE_TOP
        )
        intent.putExtra("alarm_id", JString(alarm_id))
        if fire_token is not None:
            intent.putExtra("fire_token", JString(str(fire_token)))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(_activity(), request_code, intent, flags)

    def _alarm_pending_intent(alarm_id, request_code, fire_token=None,
                              label="", time_text=""):
        context = _activity().getApplicationContext()
        intent = Intent(context, AlarmReceiver)
        intent.setAction(JString(ANDROID_FIRE_ACTION))
        intent.putExtra("alarm_id", JString(alarm_id))
        if fire_token is not None:
            intent.putExtra("fire_token", JString(str(fire_token)))
        if label:
            intent.putExtra("alarm_label", JString(label))
        if time_text:
            intent.putExtra("alarm_time", JString(time_text))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(_activity(), request_code, intent, flags)

    def android_schedule_alarm(alarm_id, trigger_dt, salt="", label="", time_text=""):
        request_code = stable_request_code(alarm_id, salt)
        fire_token = int(trigger_dt.timestamp() * 1000)
        pending_intent = _alarm_pending_intent(
            alarm_id, request_code, fire_token, label, time_text
        )
        show_intent = _alarm_activity_pending_intent(
            alarm_id,
            ANDROID_NOTIF_OPEN_ACTION,
            stable_request_code(alarm_id, "show"),
            fire_token,
        )
        info = AlarmClockInfo(fire_token, show_intent)
        print(
            "[RedAlarm] schedule id={} when={} label={!r} time={} salt={}".format(
                alarm_id, trigger_dt.isoformat(), label, time_text, salt
            )
        )
        _alarm_manager().setAlarmClock(info, pending_intent)

    def android_cancel_alarm(alarm_id, salt=""):
        request_code = stable_request_code(alarm_id, salt)
        pending_intent = _alarm_pending_intent(alarm_id, request_code)
        _alarm_manager().cancel(pending_intent)
        print("[RedAlarm] cancel id={} salt={}".format(alarm_id, salt))

    def android_can_schedule_exact_alarms():
        try:
            return bool(_alarm_manager().canScheduleExactAlarms())
        except AttributeError:
            return True

    def android_request_exact_alarm_permission():
        intent = Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM)
        intent.setData(Uri.parse("package:" + _activity().getPackageName()))
        _activity().startActivity(intent)

    def android_is_ignoring_battery_optimizations():
        try:
            pm = cast(
                "android.os.PowerManager",
                _activity().getSystemService(Context.POWER_SERVICE),
            )
            return bool(pm.isIgnoringBatteryOptimizations(_activity().getPackageName()))
        except Exception:
            return True

    def android_request_ignore_battery_optimizations():
        intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        intent.setData(Uri.parse("package:" + _activity().getPackageName()))
        _activity().startActivity(intent)

    def android_request_runtime_permissions():
        perms = []
        if Build.VERSION.SDK_INT >= 33:
            perms.append(Permission.POST_NOTIFICATIONS)
        if perms:
            request_permissions(perms)

    def android_show_over_lockscreen(show):
        window = _activity().getWindow()
        flags = (
            WindowManagerFlags.FLAG_SHOW_WHEN_LOCKED
            | WindowManagerFlags.FLAG_TURN_SCREEN_ON
            | WindowManagerFlags.FLAG_KEEP_SCREEN_ON
        )
        if show:
            window.addFlags(flags)
            if Build.VERSION.SDK_INT >= 27:
                _activity().setShowWhenLocked(True)
                _activity().setTurnScreenOn(True)
            try:
                keyguard = _activity().getSystemService(Context.KEYGUARD_SERVICE)
                power = _activity().getSystemService(Context.POWER_SERVICE)
                print(
                    "[RedAlarm] lockscreen show keyguard={} interactive={}".format(
                        bool(keyguard.isKeyguardLocked()), bool(power.isInteractive())
                    )
                )
            except Exception:
                pass
        else:
            window.clearFlags(flags)
            if Build.VERSION.SDK_INT >= 27:
                _activity().setShowWhenLocked(False)
                _activity().setTurnScreenOn(False)

    def android_acquire_wake_lock():
        pm = cast(
            "android.os.PowerManager",
            _activity().getSystemService(Context.POWER_SERVICE),
        )
        old = _wake_lock[0]
        if old is not None:
            try:
                if old.isHeld():
                    old.release()
            except Exception:
                pass
        wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RedAlarm:AlarmWakeLock")
        wl.acquire(10 * 60 * 1000)
        _wake_lock[0] = wl

    def android_release_wake_lock():
        wl = _wake_lock[0]
        if wl is None:
            return
        try:
            if wl.isHeld():
                wl.release()
        except Exception:
            pass
        _wake_lock[0] = None

    def android_take_persistable_uri_permission(uri_string, flags):
        resolver = _activity().getContentResolver()
        uri = Uri.parse(uri_string)
        persistable = flags & (
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        )
        if persistable == 0:
            persistable = Intent.FLAG_GRANT_READ_URI_PERMISSION
        try:
            resolver.takePersistableUriPermission(uri, persistable)
            print("[RedAlarm] persisted URI permission:", uri_string)
        except Exception as exc:
            print("[RedAlarm] persistable URI permission unavailable:", exc)

    def android_get_mime_type(uri_string):
        try:
            return _activity().getContentResolver().getType(Uri.parse(uri_string))
        except Exception:
            return None

    def android_copy_content_uri_to_file(uri_string, dest_path):
        resolver = _activity().getContentResolver()
        input_stream = resolver.openInputStream(Uri.parse(uri_string))
        if input_stream is None:
            raise IOError("ContentResolver.openInputStream returned null")

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        temp_path = dest_path + ".tmp"
        total = 0
        try:
            with open(temp_path, "wb") as f:
                buf = bytearray(32768)
                while True:
                    n = input_stream.read(buf)
                    if n == -1:
                        break
                    if n <= 0:
                        continue
                    f.write(bytes(buf[:n]))
                    total += int(n)
            os.replace(temp_path, dest_path)
        finally:
            try:
                input_stream.close()
            except Exception:
                pass
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

        if total <= 0:
            raise IOError("Selected audio file was empty")
        print("[RedAlarm] cached URI={} -> {} ({} bytes)".format(
            uri_string, dest_path, total
        ))
        return dest_path

    def android_pick_audio_file(on_result):
        def _on_activity_result(request_code, result_code, data):
            if request_code != _OPEN_DOCUMENT_REQUEST_CODE:
                return
            uri_string = None
            try:
                if result_code == -1 and data is not None:
                    uri = data.getData()
                    if uri is not None:
                        uri_string = uri.toString()
                        android_take_persistable_uri_permission(uri_string, data.getFlags())
            except Exception as exc:
                print("[RedAlarm] file picker result error:", exc)
            try:
                android_activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass
            Clock.schedule_once(lambda dt: on_result(uri_string), 0)

        android_activity.bind(on_activity_result=_on_activity_result)
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("audio/*")
        intent.addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        )
        _activity().startActivityForResult(intent, _OPEN_DOCUMENT_REQUEST_CODE)

    def android_get_display_name(uri_string):
        OpenableColumns = autoclass("android.provider.OpenableColumns")
        resolver = _activity().getContentResolver()
        cursor = resolver.query(Uri.parse(uri_string), None, None, None, None)
        name = None
        try:
            if cursor is not None and cursor.moveToFirst():
                idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if idx >= 0:
                    name = cursor.getString(idx)
        except Exception:
            pass
        finally:
            if cursor is not None:
                cursor.close()
        return name

    def android_start_vibration(enabled):
        try:
            vibrator = cast(
                "android.os.Vibrator",
                _activity().getSystemService(Context.VIBRATOR_SERVICE),
            )
            if not enabled:
                vibrator.cancel()
                print("[RedAlarm] vibration disabled")
                return
            pattern = [0, 550, 750]
            if Build.VERSION.SDK_INT >= 26:
                VibrationEffect = autoclass("android.os.VibrationEffect")
                vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0))
            else:
                vibrator.vibrate(pattern, 0)
            print("[RedAlarm] vibration started")
        except Exception as exc:
            print("[RedAlarm] vibration start error:", exc)

    def android_stop_vibration():
        try:
            vibrator = cast(
                "android.os.Vibrator",
                _activity().getSystemService(Context.VIBRATOR_SERVICE),
            )
            vibrator.cancel()
        except Exception as exc:
            print("[RedAlarm] vibration stop error:", exc)

    def android_cancel_ringing_notification():
        context = _activity().getApplicationContext()
        manager = cast(
            "android.app.NotificationManager",
            context.getSystemService(Context.NOTIFICATION_SERVICE),
        )
        manager.cancel(_RINGING_NOTIFICATION_ID)

    def android_is_samsung():
        try:
            manufacturer = str(Build.MANUFACTURER or "").lower()
            brand = str(Build.BRAND or "").lower()
            return "samsung" in manufacturer or "samsung" in brand
        except Exception:
            return False

    def android_open_samsung_never_sleeping_apps():
        try:
            intent = Intent()
            intent.setAction(
                "com.samsung.android.sm.ACTION_OPEN_CHECKABLE_LISTACTIVITY"
            )
            intent.setPackage("com.samsung.android.lool")
            intent.putExtra("activity_type", 2)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            _activity().startActivity(intent)
            print("[RedAlarm] opened Samsung Never sleeping apps")
            return True
        except Exception as exc:
            print("[RedAlarm] Samsung deeplink failed:", exc)

        for action in (
            Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS,
            Settings.ACTION_BATTERY_SAVER_SETTINGS,
        ):
            try:
                intent = Intent(action)
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                _activity().startActivity(intent)
                print("[RedAlarm] battery fallback:", action)
                return True
            except Exception:
                pass
        return False


# ======================================================================
# Storage and scheduler
# ======================================================================
class AlarmStore:
    def __init__(self, path):
        self.path = path
        self._alarms = {}
        self.load()

    def load(self):
        self._alarms = {}
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._alarms = {
                a["id"]: a for a in data if isinstance(a, dict) and "id" in a
            }
        except (ValueError, IOError, OSError):
            self._alarms = {}

    def save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(self._alarms.values()), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def all(self):
        return sorted(
            self._alarms.values(),
            key=lambda a: (a.get("hour", 0), a.get("minute", 0)),
        )

    def get(self, alarm_id):
        return self._alarms.get(alarm_id)

    def put(self, alarm):
        self._alarms[alarm["id"]] = alarm
        self.save()

    def delete(self, alarm_id):
        self._alarms.pop(alarm_id, None)
        self.save()


class AlarmScheduler:
    def __init__(self, on_desktop_fire):
        self._pending = {}
        self._on_desktop_fire = on_desktop_fire
        self._poll_event = Clock.schedule_interval(self._poll, 1.0)

    def schedule(self, alarm, now=None):
        trigger_dt = compute_next_trigger_dt(alarm, now=now)
        self._pending[alarm["id"]] = (alarm["id"], trigger_dt)
        if ANDROID:
            android_schedule_alarm(
                alarm["id"], trigger_dt, salt="",
                label=alarm.get("label") or "Alarm",
                time_text=format_time(alarm["hour"], alarm["minute"]),
            )
        return trigger_dt

    def cancel(self, alarm):
        self._pending.pop(alarm["id"], None)
        if ANDROID:
            android_cancel_alarm(alarm["id"], salt="")

    def schedule_snooze(self, alarm, trigger_dt):
        self._pending[alarm["id"] + "snooze"] = (alarm["id"], trigger_dt)
        if ANDROID:
            android_schedule_alarm(
                alarm["id"], trigger_dt, salt="snooze",
                label=alarm.get("label") or "Alarm",
                time_text=format_time(alarm["hour"], alarm["minute"]),
            )

    def cancel_snooze(self, alarm):
        self._pending.pop(alarm["id"] + "snooze", None)
        if ANDROID:
            android_cancel_alarm(alarm["id"], salt="snooze")

    def forget_fired(self, alarm_id):
        self._pending.pop(alarm_id, None)
        self._pending.pop(alarm_id + "snooze", None)

    def next_trigger_for(self, alarm_id):
        times = [t for aid, t in self._pending.values() if aid == alarm_id]
        return min(times) if times else None

    def _poll(self, dt):
        if ANDROID or not self._pending:
            return
        now = datetime.datetime.now()
        due = [key for key, (_, t) in self._pending.items() if t <= now]
        for key in due:
            alarm_id, _ = self._pending.pop(key)
            try:
                self._on_desktop_fire(alarm_id)
            except Exception as exc:
                print("[RedAlarm] desktop fire error {}: {}".format(alarm_id, exc))


# ======================================================================
# Ringtones
# ======================================================================
DEFAULT_RINGTONE_NAME = "Default Alarm Tone"


def ensure_default_ringtone(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "default_alarm.wav")
    if os.path.exists(path):
        return path

    rate = 22050

    def tone(freq, seconds, volume=0.55):
        n = int(rate * seconds)
        return [
            int(volume * 32767 * math.sin(2 * math.pi * freq * i / rate))
            for i in range(n)
        ]

    def silence(seconds):
        return [0] * int(rate * seconds)

    samples = []
    for _ in range(2):
        samples += tone(1100, 0.14)
        samples += silence(0.09)
    samples += silence(0.38)

    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return path


def pick_ringtone_file(on_chosen, on_error):
    def _deliver(path):
        Clock.schedule_once(lambda dt: on_chosen(path), 0)

    if ANDROID:
        try:
            android_pick_audio_file(_deliver)
            return
        except Exception as exc:
            print("[RedAlarm] native picker error:", exc)
            on_error("Couldn't open the file picker: {}".format(exc))
            return

    def _plyer_cb(selection):
        _deliver(selection[0] if selection else None)

    try:
        from plyer import filechooser
        filechooser.open_file(
            on_selection=_plyer_cb,
            filters=[["Audio files", "*.mp3", "*.wav", "*.ogg", "*.m4a"]],
            multiple=False,
        )
        return
    except Exception:
        pass

    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.mp3 *.wav *.ogg *.m4a")]
        )
        root.destroy()
        _deliver(path or None)
        return
    except Exception:
        on_error("Couldn't open the file picker.")


def resolve_ringtone_for_playback(raw_path, app_storage_dir):
    """Resolve at actual playback time.

    Android content:// values are copied to private storage with a real audio
    extension. The previous implementation used '.audio', which could cause
    SoundLoader to fail to select an audio decoder and appear as Silent.
    """
    if not raw_path:
        return None

    if raw_path.startswith("content://"):
        if not ANDROID:
            return None
        os.makedirs(app_storage_dir, exist_ok=True)

        try:
            name = android_get_display_name(raw_path) or ""
        except Exception:
            name = ""

        ext = os.path.splitext(name)[1].lower()
        valid = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
        if ext not in valid:
            mime = android_get_mime_type(raw_path)
            ext = {
                "audio/mpeg": ".mp3",
                "audio/mp3": ".mp3",
                "audio/wav": ".wav",
                "audio/x-wav": ".wav",
                "audio/wave": ".wav",
                "audio/ogg": ".ogg",
                "audio/mp4": ".m4a",
                "audio/x-m4a": ".m4a",
                "audio/aac": ".aac",
                "audio/flac": ".flac",
            }.get(mime, ".mp3")

        dest = os.path.join(
            app_storage_dir,
            hashlib.md5(raw_path.encode("utf-8")).hexdigest() + ext,
        )
        try:
            android_copy_content_uri_to_file(raw_path, dest)
            print(
                "[RedAlarm] ringtone resolved URI={} name={!r} mime={!r} -> {}".format(
                    raw_path, name, android_get_mime_type(raw_path), dest
                )
            )
            return dest
        except Exception as exc:
            print("[RedAlarm] ringtone URI resolution failed:", exc)
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                print("[RedAlarm] using cached ringtone:", dest)
                return dest
            return None

    return raw_path


# ======================================================================
# Custom widgets
# ======================================================================
class AnalogClock(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_second = None
        self._numerals = {}
        self.bind(pos=self._force_redraw, size=self._force_redraw)
        self._tick_event = Clock.schedule_interval(self._tick, 0.1)
        self._redraw()

    def _force_redraw(self, *_):
        self._last_second = None
        self._redraw()

    def _tick(self, dt):
        if datetime.datetime.now().second != self._last_second:
            self._redraw()

    def _numeral_texture(self, number, font_px):
        key = (number, font_px)
        tex = self._numerals.get(key)
        if tex is None:
            lbl = CoreLabel(text=str(number), font_size=font_px, bold=True)
            lbl.refresh()
            tex = lbl.texture
            self._numerals[key] = tex
        return tex

    def _redraw(self):
        self.canvas.clear()
        cx, cy = self.center
        radius = min(self.width, self.height) / 2 * 0.94
        if radius < 20:
            return

        now = datetime.datetime.now()
        self._last_second = now.second
        minute = now.minute + now.second / 60.0
        hour = (now.hour % 12) + minute / 60.0

        def pt(deg, r):
            a = math.radians(90 - deg)
            return cx + r * math.cos(a), cy + r * math.sin(a)

        font_px = max(12, int(radius * 0.15))
        with self.canvas:
            Color(0.42, 0.06, 0.08, 0.30)
            Ellipse(
                pos=(cx - radius * 1.07, cy - radius * 1.07),
                size=(radius * 2.14, radius * 2.14),
            )
            Color(0.055, 0.05, 0.055, 1)
            Ellipse(pos=(cx - radius, cy - radius), size=(radius * 2, radius * 2))
            Color(0.82, 0.10, 0.13, 1)
            Line(circle=(cx, cy, radius), width=dp(2.4))

            for i in range(60):
                deg = i * 6
                if i % 15 == 0:
                    Color(0.82, 0.10, 0.13, 1)
                    r_in, width = 0.855, dp(2.8)
                elif i % 5 == 0:
                    Color(0.85, 0.82, 0.82, 1)
                    r_in, width = 0.885, dp(2.0)
                else:
                    Color(0.40, 0.36, 0.36, 1)
                    r_in, width = 0.925, dp(1.0)
                Line(
                    points=[*pt(deg, radius * r_in), *pt(deg, radius * 0.965)],
                    width=width,
                )

            for n in range(1, 13):
                tex = self._numeral_texture(n, font_px)
                x, y = pt(n * 30, radius * 0.72)
                Color(0.96, 0.96, 0.96, 1) if n % 3 == 0 else Color(0.62, 0.58, 0.58, 1)
                Rectangle(texture=tex, size=tex.size, pos=(x - tex.width / 2, y - tex.height / 2))

            Color(0.96, 0.96, 0.96, 1)
            Line(points=[cx, cy, *pt(hour * 30, radius * 0.48)], width=dp(3.8))
            Color(0.86, 0.83, 0.83, 1)
            Line(points=[cx, cy, *pt(minute * 6, radius * 0.78)], width=dp(2.6))
            Color(0.90, 0.12, 0.15, 1)
            Line(
                points=[*pt(now.second * 6 + 180, radius * 0.16), *pt(now.second * 6, radius * 0.86)],
                width=dp(1.3),
            )
            Ellipse(pos=(cx - dp(6), cy - dp(6)), size=(dp(12), dp(12)))
            Color(0.05, 0.05, 0.05, 1)
            Ellipse(pos=(cx - dp(2.5), cy - dp(2.5)), size=(dp(5), dp(5)))


class IOSToggle(ButtonBehavior, Widget):
    active = BooleanProperty(False)
    _thumb = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._thumb = 1 if self.active else 0
        self.bind(pos=self._redraw, size=self._redraw, _thumb=self._redraw)
        self._redraw()

    def on_active(self, *_):
        Animation.cancel_all(self, "_thumb")
        Animation(_thumb=1 if self.active else 0, duration=0.15, t="out_quad").start(self)
        self._redraw()

    def on_release(self):
        self.active = not self.active

    def _redraw(self, *_):
        self.canvas.clear()
        if self.width <= 0 or self.height <= 0:
            return
        track = (0.82, 0.10, 0.13, 1) if self.active else (0.40, 0.38, 0.38, 1)
        pad = self.height * 0.10
        d = self.height - 2 * pad
        travel = self.width - d - 2 * pad
        with self.canvas:
            Color(*track)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.height / 2])
            Color(1, 1, 1, 1)
            Ellipse(pos=(self.x + pad + travel * self._thumb, self.y + pad), size=(d, d))


class HomeButton(Button):
    bg_color = ListProperty([0.11, 0.09, 0.09, 1])
    text_color = ListProperty([0.96, 0.96, 0.96, 1])


class DigitInput(TextInput):
    max_chars = NumericProperty(2)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(focus=self._on_focus_change)

    def insert_text(self, substring, from_undo=False):
        digits = "".join(ch for ch in substring if ch.isdigit())
        room = self.max_chars - len(self.text) + len(self.selection_text)
        return super().insert_text(digits[:max(0, room)], from_undo=from_undo)

    def _on_focus_change(self, _instance, focused):
        if focused:
            Clock.schedule_once(lambda dt: self.select_all(), 0)


class AlarmInfoButton(ButtonBehavior, BoxLayout):
    row = ObjectProperty(None)
    time_text = StringProperty("")
    sub_text = StringProperty("")
    dim = BooleanProperty(False)

    def on_release(self):
        if self.row is not None:
            self.row.on_row_press()


class TimeDial(Widget):
    mode = StringProperty("hour")
    selected = NumericProperty(12)
    on_value = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, mode=self._redraw, selected=self._redraw)
        Clock.schedule_once(self._redraw, 0)

    def _values(self):
        return list(range(1, 13)) if self.mode == "hour" else [i * 5 for i in range(12)]

    def _label_text(self, value):
        return str(value) if self.mode == "hour" else "{:02d}".format(value)

    def _redraw(self, *_):
        self.canvas.clear()
        if self.opacity <= 0:
            return
        cx, cy = self.center
        radius = min(self.width, self.height) * 0.38
        tick_radius = radius * 0.82
        values = self._values()
        idx = int(self.selected) % 12 if self.mode == "hour" else int(round(self.selected / 5.0)) % 12
        selected_angle = 2 * math.pi * idx / 12.0
        sx = cx + tick_radius * math.sin(selected_angle)
        sy = cy + tick_radius * math.cos(selected_angle)

        with self.canvas:
            Color(0.18, 0.12, 0.12, 1)
            Ellipse(pos=(cx - radius, cy - radius), size=(2 * radius, 2 * radius))
            Color(0.82, 0.10, 0.13, 1)
            Line(points=[cx, cy, sx, sy], width=dp(1.4))
            Ellipse(pos=(cx - dp(4), cy - dp(4)), size=(dp(8), dp(8)))

            for i, value in enumerate(values):
                angle = 2 * math.pi * i / 12.0
                x = cx + tick_radius * math.sin(angle)
                y = cy + tick_radius * math.cos(angle)
                is_selected = i == idx
                if is_selected:
                    Color(0.96, 0.88, 0.88, 1)
                    Ellipse(pos=(x - dp(16), y - dp(16)), size=(dp(32), dp(32)))
                label = CoreLabel(
                    text=self._label_text(value),
                    font_size=int(dp(13)),
                    color=(0.12, 0.08, 0.08, 1) if is_selected else (0.92, 0.88, 0.88, 1),
                )
                label.refresh()
                tw, th = label.texture.size
                Color(1, 1, 1, 1)
                Rectangle(texture=label.texture, pos=(x - tw / 2.0, y - th / 2.0), size=(tw, th))

    def on_touch_up(self, touch):
        if self.opacity <= 0 or not self.collide_point(*touch.pos):
            return super().on_touch_up(touch)
        cx, cy = self.center
        dx, dy = touch.x - cx, touch.y - cy
        if (dx * dx + dy * dy) ** 0.5 > min(self.width, self.height) * 0.49:
            return super().on_touch_up(touch)
        angle = math.atan2(dx, dy)
        if angle < 0:
            angle += 2 * math.pi
        idx = int(round(angle / (2 * math.pi / 12.0))) % 12
        value = (12 if idx == 0 else idx) if self.mode == "hour" else idx * 5
        self.selected = value
        if self.on_value:
            self.on_value(value)
        return True


class TimePickerPopup(Popup):
    def __init__(self, hour12, minute, ampm, on_ok, **kwargs):
        super().__init__(
            title="",
            size_hint=(0.92, None),
            height=dp(535),
            auto_dismiss=False,
            separator_height=0,
            background_color=(0.06, 0.045, 0.045, 0.98),
            **kwargs,
        )
        self.hour12 = int(hour12)
        self.minute = int(minute)
        self.ampm = ampm if ampm in ("AM", "PM") else "AM"
        self.mode = "hour"
        self._on_ok_callback = on_ok

        root = BoxLayout(orientation="vertical", padding=[dp(18), dp(18), dp(18), dp(12)], spacing=dp(8))
        root.add_widget(Label(
            text="Select time", color=(0.92, 0.86, 0.86, 1), font_size="17sp",
            size_hint_y=None, height=dp(28), halign="left"
        ))

        header = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(6))
        self.hour_button = HomeButton(text="{:02d}".format(self.hour12), bg_color=[0.82, 0.10, 0.13, 1], text_color=[1, 1, 1, 1])
        self.minute_button = HomeButton(text="{:02d}".format(self.minute), bg_color=[0.16, 0.12, 0.12, 1], text_color=[0.92, 0.86, 0.86, 1])
        header.add_widget(self.hour_button)
        header.add_widget(Label(text=":", color=(0.82, 0.10, 0.13, 1), font_size="32sp", bold=True, size_hint_x=None, width=dp(18)))
        header.add_widget(self.minute_button)

        ampm_box = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(70), spacing=dp(5))
        self.am_button = HomeButton(text="AM", bg_color=[0.16, 0.12, 0.12, 1], text_color=[0.92, 0.86, 0.86, 1])
        self.pm_button = HomeButton(text="PM", bg_color=[0.16, 0.12, 0.12, 1], text_color=[0.92, 0.86, 0.86, 1])
        ampm_box.add_widget(self.am_button)
        ampm_box.add_widget(self.pm_button)
        header.add_widget(ampm_box)
        root.add_widget(header)

        self.mode_label = Label(text="Select hour", color=(0.62, 0.58, 0.58, 1), font_size="12sp", size_hint_y=None, height=dp(20))
        root.add_widget(self.mode_label)

        self.dial = TimeDial(mode="hour", selected=self.hour12)
        self.dial.on_value = self._dial_value
        root.add_widget(self.dial)

        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        buttons.add_widget(Widget())
        cancel = HomeButton(text="Cancel", bg_color=[0.11, 0.09, 0.09, 1], text_color=[0.75, 0.70, 0.70, 1])
        ok = HomeButton(text="OK", bg_color=[0.82, 0.10, 0.13, 1], text_color=[1, 1, 1, 1])
        cancel.bind(on_release=lambda *_: self.dismiss())
        ok.bind(on_release=self._ok)
        self.hour_button.bind(on_release=lambda *_: self._set_mode("hour"))
        self.minute_button.bind(on_release=lambda *_: self._set_mode("minute"))
        self.am_button.bind(on_release=lambda *_: self._set_ampm("AM"))
        self.pm_button.bind(on_release=lambda *_: self._set_ampm("PM"))
        buttons.add_widget(cancel)
        buttons.add_widget(ok)
        root.add_widget(buttons)
        self.content = root
        self._sync_header()

    def _set_mode(self, mode):
        self.mode = mode
        if mode == "hour":
            self.dial.opacity = 1
            self.dial.mode = "hour"
            self.dial.selected = self.hour12
            self.mode_label.text = "Select hour"
        elif mode == "minute":
            self.dial.opacity = 1
            self.dial.mode = "minute"
            self.dial.selected = (int(round(self.minute / 5.0) * 5) % 60)
            self.mode_label.text = "Select minutes"
        else:
            self.dial.opacity = 0
            self.mode_label.text = "Select AM or PM"
        self._sync_header()

    def _dial_value(self, value):
        if self.mode == "hour":
            self.hour12 = int(value)
            self._set_mode("minute")
        elif self.mode == "minute":
            self.minute = int(value)
            self._set_mode("ampm")

    def _set_ampm(self, value):
        self.ampm = value
        self._sync_header()

    def _sync_header(self):
        active = [0.82, 0.10, 0.13, 1]
        inactive = [0.16, 0.12, 0.12, 1]
        self.hour_button.text = "{:02d}".format(self.hour12)
        self.minute_button.text = "{:02d}".format(self.minute)
        self.hour_button.bg_color = active if self.mode == "hour" else inactive
        self.minute_button.bg_color = active if self.mode == "minute" else inactive
        self.am_button.bg_color = active if self.ampm == "AM" else inactive
        self.pm_button.bg_color = active if self.ampm == "PM" else inactive

    def _ok(self, *_):
        self._on_ok_callback(self.hour12, self.minute, self.ampm)
        self.dismiss()


# ======================================================================
# Screens
# ======================================================================
class HomeScreen(Screen):
    date_text = StringProperty("")
    next_alarm_text = StringProperty("")
    _next_alarm_event = None

    def on_pre_enter(self, *args):
        self.date_text = datetime.datetime.now().strftime("%A, %d %B")
        self._refresh_next_alarm()
        if self._next_alarm_event is None:
            self._next_alarm_event = Clock.schedule_interval(lambda dt: self._refresh_next_alarm(), 1)

    def on_leave(self, *args):
        if self._next_alarm_event is not None:
            self._next_alarm_event.cancel()
            self._next_alarm_event = None

    def _refresh_next_alarm(self, *args):
        app = App.get_running_app()
        if not hasattr(app, "store"):
            return
        now = datetime.datetime.now()
        best = None
        for alarm in app.store.all():
            if not alarm.get("enabled", True):
                continue
            trigger = compute_next_trigger_dt(alarm, now=now)
            if best is None or trigger < best:
                best = trigger
        if best is None:
            self.next_alarm_text = "No alarms set"
            return
        total = max(0, int((best - now).total_seconds()))
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days:
            when = "{}d {}h {}m".format(days, hours, minutes)
        elif hours:
            when = "{}h {}m {}s".format(hours, minutes, seconds)
        else:
            when = "{}m {}s".format(minutes, seconds)
        self.next_alarm_text = "Next alarm in {}".format(when)

    def go_alarms(self):
        App.get_running_app().root.current = "list"

    def go_new_alarm(self):
        app = App.get_running_app()
        app.root.get_screen("edit").load_alarm(None)
        app.root.current = "edit"


class AlarmRow(BoxLayout):
    alarm_id = StringProperty("")
    time_text = StringProperty("")
    sub_text = StringProperty("")
    enabled = BooleanProperty(True)
    list_screen = ObjectProperty(None)

    def on_switch_active(self, value):
        value = bool(value)
        if value == self.enabled:
            return
        self.enabled = value
        if self.list_screen is not None:
            self.list_screen.on_toggle_alarm(self.alarm_id, value)

    def on_row_press(self):
        if self.list_screen is not None:
            self.list_screen.open_edit(self.alarm_id)

    def on_delete_press(self):
        if self.list_screen is not None:
            self.list_screen.confirm_delete(self.alarm_id)


class AlarmListScreen(Screen):
    _delete_popup = None
    exact_alarm_ok = BooleanProperty(True)
    battery_ok = BooleanProperty(True)

    def on_pre_enter(self, *args):
        self.refresh()
        self._refresh_permission_banners()

    def go_home(self):
        App.get_running_app().root.current = "home"

    def _refresh_permission_banners(self):
        if ANDROID:
            try:
                self.exact_alarm_ok = android_can_schedule_exact_alarms()
            except Exception:
                self.exact_alarm_ok = True
            try:
                self.battery_ok = android_is_ignoring_battery_optimizations()
            except Exception:
                self.battery_ok = True
        else:
            self.exact_alarm_ok = True
            self.battery_ok = True

    def refresh(self):
        app = App.get_running_app()
        box = self.ids.alarms_box
        box.clear_widgets()
        alarms = app.store.all()
        if not alarms:
            box.add_widget(Label(
                text="No alarms yet.\nTap + to add one.",
                color=(0.55, 0.5, 0.5, 1),
                halign="center", valign="middle",
                text_size=(dp(280), None),
                size_hint_y=None, height=dp(120),
            ))
        for alarm in alarms:
            row = AlarmRow(list_screen=self)
            row.alarm_id = alarm["id"]
            row.time_text = format_time(alarm["hour"], alarm["minute"])
            label = alarm.get("label") or ""
            days_str = format_days(alarm.get("days"))
            row.sub_text = (label + " · " + days_str) if label else days_str
            row.enabled = bool(alarm.get("enabled", True))
            box.add_widget(row)

    def open_permission_settings(self):
        if ANDROID:
            try:
                android_request_exact_alarm_permission()
            except Exception as exc:
                print("[RedAlarm] exact-alarm settings error:", exc)

    def open_battery_settings(self):
        if ANDROID:
            try:
                android_request_ignore_battery_optimizations()
            except Exception as exc:
                print("[RedAlarm] battery settings error:", exc)

    def open_new_alarm(self):
        app = App.get_running_app()
        app.root.get_screen("edit").load_alarm(None)
        app.root.current = "edit"

    def open_edit(self, alarm_id):
        app = App.get_running_app()
        if app.store.get(alarm_id):
            app.root.get_screen("edit").load_alarm(alarm_id)
            app.root.current = "edit"

    def on_toggle_alarm(self, alarm_id, enabled):
        app = App.get_running_app()
        alarm = app.store.get(alarm_id)
        if not alarm:
            return
        alarm["enabled"] = bool(enabled)
        app.store.put(alarm)
        app.scheduler.cancel_snooze(alarm)
        if enabled:
            app.scheduler.schedule(alarm)
        else:
            app.scheduler.cancel(alarm)

    def confirm_delete(self, alarm_id):
        app = App.get_running_app()

        def do_delete(*_):
            alarm = app.store.get(alarm_id)
            if alarm:
                app.scheduler.cancel(alarm)
                app.scheduler.cancel_snooze(alarm)
            ring = app.root.get_screen("ring")
            if ring.alarm_id == alarm_id:
                app.finish_ringing_alarm(alarm_id, "delete")
            app.store.delete(alarm_id)
            popup.dismiss()
            self.refresh()

        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        content.add_widget(Label(text="Delete this alarm?", color=(1, 1, 1, 1)))
        buttons = BoxLayout(spacing=dp(12), size_hint_y=None, height=dp(44))
        cancel_btn = Button(text="Cancel")
        yes_btn = Button(text="Delete", background_color=(0.8, 0.1, 0.1, 1))
        buttons.add_widget(cancel_btn)
        buttons.add_widget(yes_btn)
        content.add_widget(buttons)
        popup = Popup(title="", content=content, size_hint=(0.8, 0.3), separator_height=0, background_color=(0.07, 0.07, 0.07, 1))
        cancel_btn.bind(on_release=popup.dismiss)
        yes_btn.bind(on_release=do_delete)
        self._delete_popup = popup
        popup.open()


class AlarmEditScreen(Screen):
    editing_id = StringProperty("")
    ampm = StringProperty("AM")
    days_selected = ListProperty([False] * 7)
    sound_path = StringProperty("")
    sound_name = StringProperty("No sound chosen")
    vibrate_enabled = BooleanProperty(True)
    _new_picker_event = None

    def load_alarm(self, alarm_id):
        ids = self.ids
        ids.error_label.text = ""

        if alarm_id is None:
            self.editing_id = ""
            try:
                now = datetime.datetime.now()
                current_hour, current_minute = now.hour, now.minute
            except Exception:
                current_hour, current_minute = 0, 0
            self.ampm = "PM" if current_hour >= 12 else "AM"
            h12 = current_hour % 12 or 12
            ids.input_hour.text = "{:02d}".format(h12)
            ids.input_minute.text = "{:02d}".format(current_minute)
            self.days_selected = [False] * 7
            self.sound_path = ""
            self.sound_name = "Default beep (tap to change)"
            self.vibrate_enabled = True
            ids.dismiss_min.text = "5"
            ids.dismiss_sec.text = "0"
            ids.snooze_min.text = "5"
            ids.snooze_sec.text = "0"
            ids.label_input.text = ""
            ids.delete_btn.opacity = 0
            ids.delete_btn.disabled = True
            if self._new_picker_event is not None:
                try:
                    self._new_picker_event.cancel()
                except Exception:
                    pass
            self._new_picker_event = Clock.schedule_once(lambda dt: self.open_time_picker(), 0.12)
        else:
            alarm = App.get_running_app().store.get(alarm_id)
            if not alarm:
                return
            self.editing_id = alarm_id
            h, m = int(alarm["hour"]), int(alarm["minute"])
            self.ampm = "PM" if h >= 12 else "AM"
            h12 = h % 12 or 12
            ids.input_hour.text = "{:02d}".format(h12)
            ids.input_minute.text = "{:02d}".format(m)
            self.days_selected = list(alarm.get("days") or [False] * 7)
            self.sound_path = alarm.get("sound_path", "")
            self.sound_name = alarm.get("sound_name") or "Default beep"
            self.vibrate_enabled = bool(alarm.get("vibrate", True))
            dismiss_sec = int(alarm.get("auto_dismiss_sec", 300))
            ids.dismiss_min.text = str(dismiss_sec // 60)
            ids.dismiss_sec.text = str(dismiss_sec % 60)
            snooze_sec = int(alarm.get("snooze_sec", 300))
            ids.snooze_min.text = str(snooze_sec // 60)
            ids.snooze_sec.text = str(snooze_sec % 60)
            ids.label_input.text = alarm.get("label", "")
            ids.delete_btn.opacity = 1
            ids.delete_btn.disabled = False

        self._refresh_day_buttons()

    def _refresh_day_buttons(self):
        for i in range(7):
            btn = self.ids.get("day_{}".format(i))
            if btn:
                btn.state = "down" if self.days_selected[i] else "normal"

    def set_day(self, index, on):
        if self.days_selected[index] != on:
            days = list(self.days_selected)
            days[index] = on
            self.days_selected = days

    def set_ampm(self, value):
        self.ampm = value

    def set_vibration(self, value):
        self.vibrate_enabled = bool(value)

    def open_time_picker(self):
        try:
            h12 = int(self.ids.input_hour.text or "12")
            minute = int(self.ids.input_minute.text or "0")
        except (TypeError, ValueError):
            h12, minute = 12, 0
        h12 = min(12, max(1, h12))
        minute = min(59, max(0, minute))
        picker = TimePickerPopup(h12, minute, self.ampm, self._apply_picked_time)
        self._new_picker_event = None
        picker.open()

    def _apply_picked_time(self, h12, minute, ampm):
        self.ids.input_hour.text = "{:02d}".format(int(h12))
        self.ids.input_minute.text = "{:02d}".format(int(minute))
        self.ampm = ampm

    def choose_sound(self):
        self.ids.error_label.text = ""
        pick_ringtone_file(self._on_sound_picked, self._on_picker_error)

    def _on_picker_error(self, message):
        self.ids.error_label.text = message

    def _on_sound_picked(self, path):
        if not path:
            return
        self.sound_path = path
        name = None
        if ANDROID and path.startswith("content://"):
            try:
                name = android_get_display_name(path)
            except Exception as exc:
                print("[RedAlarm] display-name lookup failed:", exc)
        self.sound_name = name or os.path.basename(path.replace("\\", "/"))
        print("[RedAlarm] selected ringtone raw={!r} name={!r}".format(path, self.sound_name))

    def preview_sound(self):
        self.ids.error_label.text = ""
        app = App.get_running_app()
        raw_path = self.sound_path
        path = raw_path and resolve_ringtone_for_playback(raw_path, app.ringtone_cache_dir)
        if not path:
            path = ensure_default_ringtone(app.ringtone_cache_dir)
        try:
            print("[RedAlarm] preview raw={!r} resolved={!r}".format(raw_path, path))
            sound = SoundLoader.load(path)
        except Exception as exc:
            self.ids.error_label.text = "Preview failed: {}".format(exc)
            print("[RedAlarm] preview load error:", exc)
            return
        if sound is None:
            self.ids.error_label.text = "Couldn't load that sound."
            return
        sound.play()
        Clock.schedule_once(lambda dt: sound.stop(), 2.5)

    def cancel_edit(self):
        App.get_running_app().root.current = "list"

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
            app.finish_ringing_alarm(self.editing_id, "delete")
        app.store.delete(self.editing_id)
        app.root.current = "list"

    def _fail(self, message):
        self.ids.error_label.text = message

    def save_alarm(self):
        ids = self.ids
        try:
            h12 = int(ids.input_hour.text)
            minute = int(ids.input_minute.text)
        except (TypeError, ValueError):
            return self._fail("Enter a valid time.")
        if not 1 <= h12 <= 12:
            return self._fail("Hour must be between 1 and 12.")
        if not 0 <= minute <= 59:
            return self._fail("Minutes must be between 00 and 59.")

        if self.ampm == "PM":
            hour = 12 if h12 == 12 else h12 + 12
        else:
            hour = 0 if h12 == 12 else h12

        try:
            total_dismiss = int(ids.dismiss_min.text or "0") * 60 + int(ids.dismiss_sec.text or "0")
            total_snooze = int(ids.snooze_min.text or "0") * 60 + int(ids.snooze_sec.text or "0")
        except (TypeError, ValueError):
            return self._fail("Enter valid durations.")
        if total_dismiss <= 0:
            return self._fail("Auto-dismiss must be at least 1 second.")
        if total_snooze <= 0:
            return self._fail("Snooze must be at least 1 second.")

        app = App.get_running_app()
        alarm = app.store.get(self.editing_id) or {}
        sound_path = self.sound_path
        sound_name = self.sound_name if self.sound_path else "Default beep"
        alarm.update({
            "id": self.editing_id or new_alarm_id(),
            "hour": hour,
            "minute": minute,
            "days": list(self.days_selected),
            "label": ids.label_input.text.strip(),
            "sound_path": sound_path,
            "sound_name": sound_name,
            "vibrate": bool(self.vibrate_enabled),
            "auto_dismiss_sec": total_dismiss,
            "snooze_sec": total_snooze,
            "enabled": True,
        })
        app.store.put(alarm)
        app.scheduler.cancel(alarm)
        app.scheduler.cancel_snooze(alarm)
        app.scheduler.schedule(alarm)
        app.root.current = "list"


class AlarmRingScreen(Screen):
    alarm_id = StringProperty("")
    time_text = StringProperty("")
    label_text = StringProperty("")
    countdown_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sound = None
        self._countdown_event = None
        self._remaining_seconds = 0
        self._ringing = False
        self._ring_session = 0

    def on_leave(self, *args):
        self._stop_common()

    def start_ringing(self, alarm):
        self._stop_common()
        self._ring_session += 1
        session = self._ring_session
        self._ringing = True
        self.alarm_id = alarm["id"]
        self.time_text = format_time(alarm["hour"], alarm["minute"])
        self.label_text = alarm.get("label") or "Alarm"

        if ANDROID:
            try:
                android_acquire_wake_lock()
                android_show_over_lockscreen(True)
            except Exception as exc:
                print("[RedAlarm] wake/lockscreen error:", exc)

        app = App.get_running_app()
        raw_path = alarm.get("sound_path", "")
        if raw_path:
            path = resolve_ringtone_for_playback(raw_path, app.ringtone_cache_dir)
        else:
            path = ensure_default_ringtone(app.ringtone_cache_dir)

        if not path or not os.path.exists(path):
            print("[RedAlarm] ringtone unavailable raw={!r}; using default".format(raw_path))
            path = ensure_default_ringtone(app.ringtone_cache_dir)

        try:
            print("[RedAlarm] ALARM AUDIO raw={!r} resolved={!r}".format(raw_path, path))
            sound = SoundLoader.load(path)
            if sound is None:
                print("[RedAlarm] SoundLoader returned None: {}".format(path))
            else:
                sound.loop = True
                sound.play()
                self._sound = sound
                print("[RedAlarm] ringtone playback started")
        except Exception as exc:
            print("[RedAlarm] Sound playback error path={!r}: {}".format(path, exc))

        if ANDROID:
            try:
                android_start_vibration(bool(alarm.get("vibrate", True)))
            except Exception as exc:
                print("[RedAlarm] vibration error:", exc)

        self._remaining_seconds = max(1, int(alarm.get("auto_dismiss_sec", 300) or 300))
        self._update_countdown_text()
        self._countdown_event = Clock.schedule_interval(lambda dt: self._tick_countdown(dt, session), 1)

    def _tick_countdown(self, dt, session):
        if not self._ringing or session != self._ring_session:
            return False
        self._remaining_seconds = max(0, self._remaining_seconds - 1)
        self._update_countdown_text()
        if self._remaining_seconds <= 0:
            self.finish(reason="auto")
            return False
        return True

    def _update_countdown_text(self):
        minutes, seconds = divmod(self._remaining_seconds, 60)
        self.countdown_text = "{:02d}:{:02d}".format(minutes, seconds)

    def _stop_common(self):
        was_active = self._ringing or self._sound is not None
        self._ringing = False
        self._ring_session += 1
        event, self._countdown_event = self._countdown_event, None
        if event is not None:
            event.cancel()

        sound, self._sound = self._sound, None
        if sound is not None:
            try:
                sound.stop()
            except Exception:
                pass
            try:
                sound.unload()
            except Exception:
                pass

        if ANDROID and was_active:
            try:
                android_stop_vibration()
                android_cancel_ringing_notification()
                android_show_over_lockscreen(False)
                android_release_wake_lock()
            except Exception as exc:
                print("[RedAlarm] Android ring cleanup error:", exc)

    def dismiss_pressed(self):
        if self._ringing:
            self.finish(reason="dismiss")

    def snooze_pressed(self):
        if self._ringing:
            self.finish(reason="snooze")

    def finish(self, reason):
        app = App.get_running_app()
        if self.alarm_id:
            app.finish_ringing_alarm(self.alarm_id, reason)


# ======================================================================
# App
# ======================================================================
class SplashScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        box = BoxLayout(orientation="vertical", padding=[dp(24)] * 4, spacing=dp(8))
        box.add_widget(Widget())
        box.add_widget(Label(
            text="[color=d11a21][b]RED[/b][/color] [b]ALARM[/b]",
            markup=True, color=(0.96, 0.96, 0.96, 1), font_size="34sp",
            size_hint_y=None, height=dp(50)
        ))
        box.add_widget(Label(
            text="Loading alarms…", color=(0.62, 0.58, 0.58, 1), font_size="13sp",
            size_hint_y=None, height=dp(22)
        ))
        box.add_widget(Widget())
        self.add_widget(box)


class RootManager(ScreenManager):
    pass


class RedAlarmApp(App):
    def build(self):
        self.title = APP_TITLE
        self._startup_ready = False
        self._startup_event = Clock.schedule_once(self._finish_startup, 0.05)
        self._last_fire_token = None
        self.active_alarm_id = ""

        root = RootManager()
        root.add_widget(SplashScreen(name="splash"))
        root.current = "splash"
        self.root = root
        return root

    def _finish_startup(self, *_):
        if self._startup_ready:
            return
        self._startup_ready = True
        try:
            Builder.load_file("alarm.kv")
            self.store = AlarmStore(os.path.join(self.user_data_dir, "alarms.json"))
            self.ringtone_cache_dir = os.path.join(self.user_data_dir, "ringtones")
            self.default_ringtone_path = os.path.join(self.ringtone_cache_dir, "default_alarm.wav")
            self.scheduler = AlarmScheduler(self.handle_alarm_fired)
            self.crash_log_path = os.path.join(self.user_data_dir, "crash_log.txt")
            ExceptionManager.add_handler(_CrashLogger(self.crash_log_path))

            if not ANDROID:
                Window.size = (380, 720)
            else:
                android_activity.bind(on_new_intent=self._on_new_intent)
                try:
                    android_request_runtime_permissions()
                except Exception as exc:
                    print("[RedAlarm] runtime permission request error:", exc)

            self.root.add_widget(HomeScreen(name="home"))
            self.root.add_widget(AlarmListScreen(name="list"))
            self.root.add_widget(AlarmEditScreen(name="edit"))
            self.root.add_widget(AlarmRingScreen(name="ring"))
            self.root.remove_widget(self.root.get_screen("splash"))
            self.root.current = "home"

            self._resync_all_alarms()
            self._check_incoming_intent()

            if ANDROID and android_is_samsung():
                Clock.schedule_once(self._maybe_show_samsung_prompt, 0.8)
        except Exception as exc:
            print("[RedAlarm] startup error:", exc)
            traceback.print_exc()

    def on_start(self):
        if not self._startup_ready and self._startup_event is None:
            self._startup_event = Clock.schedule_once(self._finish_startup, 0.05)

    def _resync_all_alarms(self):
        for alarm in self.store.all():
            if alarm.get("enabled", True):
                try:
                    self.scheduler.schedule(alarm)
                except Exception as exc:
                    print("[RedAlarm] could not schedule {}: {}".format(alarm.get("id"), exc))

    def on_resume(self):
        if not self._startup_ready:
            return
        self._check_incoming_intent()
        if self.root.current == "list":
            self.root.get_screen("list")._refresh_permission_banners()

    def _read_android_intent(self):
        if not ANDROID:
            return None, None, None
        try:
            intent = PythonActivity.mActivity.getIntent()
            if intent is None:
                return None, None, None
            return (
                intent.getAction(),
                intent.getStringExtra("alarm_id"),
                intent.getStringExtra("fire_token"),
            )
        except Exception as exc:
            print("[RedAlarm] incoming intent read error:", exc)
            return None, None, None

    def _process_android_intent(self, intent):
        if not ANDROID or intent is None:
            return
        try:
            action = intent.getAction()
            alarm_id = intent.getStringExtra("alarm_id")
            fire_token = intent.getStringExtra("fire_token")
        except Exception as exc:
            print("[RedAlarm] on_new_intent read error:", exc)
            return

        print("[RedAlarm] intent action={!r} alarm_id={!r} token={!r}".format(action, alarm_id, fire_token))

        if action == ANDROID_FIRE_ACTION:
            if alarm_id and fire_token and fire_token != self._last_fire_token:
                self._last_fire_token = fire_token
                Clock.schedule_once(lambda dt, aid=alarm_id: self.handle_alarm_fired(aid), 0)
            return
        if action == ANDROID_NOTIF_DISMISS_ACTION and alarm_id:
            Clock.schedule_once(lambda dt, aid=alarm_id: self.finish_ringing_alarm(aid, "dismiss"), 0)
            return
        if action == ANDROID_NOTIF_SNOOZE_ACTION and alarm_id:
            Clock.schedule_once(lambda dt, aid=alarm_id: self.finish_ringing_alarm(aid, "snooze"), 0)
            return
        if action == ANDROID_NOTIF_OPEN_ACTION and alarm_id:
            self.root.current = "home"

    def _check_incoming_intent(self):
        action, alarm_id, fire_token = self._read_android_intent()
        if not ANDROID:
            return
        if action == ANDROID_FIRE_ACTION:
            if alarm_id and fire_token and fire_token != self._last_fire_token:
                self._last_fire_token = fire_token
                self.handle_alarm_fired(alarm_id)
        elif action == ANDROID_NOTIF_DISMISS_ACTION and alarm_id:
            self.finish_ringing_alarm(alarm_id, "dismiss")
        elif action == ANDROID_NOTIF_SNOOZE_ACTION and alarm_id:
            self.finish_ringing_alarm(alarm_id, "snooze")

    def _on_new_intent(self, intent):
        self._process_android_intent(intent)

    def finish_ringing_alarm(self, alarm_id, reason):
        if not self._startup_ready:
            return
        ring = self.root.get_screen("ring")
        if ring._ringing and ring.alarm_id and ring.alarm_id != alarm_id:
            print("[RedAlarm] ignoring stale notification action for {}".format(alarm_id))
            return

        ring._stop_common()
        if ANDROID:
            try:
                android_cancel_ringing_notification()
            except Exception:
                pass

        alarm = self.store.get(alarm_id)
        if alarm:
            if reason == "snooze":
                try:
                    snooze_sec = max(1, int(alarm.get("snooze_sec", 300) or 300))
                except (TypeError, ValueError):
                    snooze_sec = 300
                self.scheduler.cancel_snooze(alarm)
                self.scheduler.schedule_snooze(
                    alarm,
                    datetime.datetime.now() + datetime.timedelta(seconds=snooze_sec),
                )
            elif reason != "delete":
                self.scheduler.cancel_snooze(alarm)
                if not any(alarm.get("days") or []):
                    alarm["enabled"] = False
                    self.store.put(alarm)
                    self.scheduler.cancel(alarm)

        if ring.alarm_id == alarm_id:
            ring.alarm_id = ""
            ring.countdown_text = ""
            self.active_alarm_id = ""
            self.root.current = "home"

    def handle_alarm_fired(self, alarm_id):
        alarm = self.store.get(alarm_id)
        if not alarm or not alarm.get("enabled", True):
            print("[RedAlarm] ignored fire for missing/disabled alarm:", alarm_id)
            return

        self.scheduler.forget_fired(alarm_id)
        if any(alarm.get("days") or []):
            self.scheduler.schedule(
                alarm,
                now=datetime.datetime.now() + datetime.timedelta(seconds=30),
            )

        print("[RedAlarm] ALARM FIRED id={}".format(alarm_id))
        ring = self.root.get_screen("ring")
        ring.start_ringing(alarm)
        self.root.current = "ring"

    def _maybe_show_samsung_prompt(self, *_):
        if not ANDROID or not android_is_samsung() or self.root.current == "ring":
            return
        marker = os.path.join(self.user_data_dir, "samsung_prompt_seen")
        if os.path.exists(marker):
            return
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("1")
        except Exception as exc:
            print("[RedAlarm] Samsung marker error:", exc)

        content = BoxLayout(orientation="vertical", padding=[dp(20)] * 4, spacing=dp(12))
        content.add_widget(Label(
            text="Samsung may put background apps to sleep.\n\nAdd RedAlarm to Samsung's 'Never sleeping apps' to reduce the chance of delayed alarms.",
            color=(0.88, 0.84, 0.84, 1), font_size="14sp", halign="left", valign="top"
        ))
        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        later = HomeButton(text="Maybe later", bg_color=[0.11, 0.09, 0.09, 1], text_color=[0.82, 0.78, 0.78, 1])
        open_btn = HomeButton(text="Open Samsung settings", bg_color=[0.82, 0.10, 0.13, 1], text_color=[1, 1, 1, 1], font_size="14sp")
        popup = Popup(title="Keep alarms reliable", content=content, size_hint=(0.88, 0.34), auto_dismiss=False, separator_height=0, background_color=(0.08, 0.06, 0.06, 0.98))
        later.bind(on_release=popup.dismiss)
        def _open(_):
            android_open_samsung_never_sleeping_apps()
            popup.dismiss()
        open_btn.bind(on_release=_open)
        buttons.add_widget(later)
        buttons.add_widget(open_btn)
        content.add_widget(buttons)
        popup.open()

    def on_stop(self):
        if self._startup_ready:
            self.root.get_screen("ring")._stop_common()


if __name__ == "__main__":
    RedAlarmApp().run()
