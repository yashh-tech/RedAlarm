"""
Red Alarm - Kivy alarm clock (desktop-first, Android-ready).

Screens (all managed by one ScreenManager):
    home  -> analog clock + "Check Alarms" / "Set New Alarm"
    list  -> all saved alarms with iOS-style on/off toggles
    edit  -> add / edit an alarm (12-hour time + AM/PM)
    ring  -> full-screen ringing alert with a big auto-dismiss countdown

Read alarm.kv next to this file: every `id:` used via `self.ids.xxx` here
is defined there.
"""

import os
import math
import json
import uuid
import hashlib
import traceback
import datetime

from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.animation import Animation
from kivy.core.audio import SoundLoader
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.utils import platform
from kivy.properties import (
    StringProperty,
    NumericProperty,
    BooleanProperty,
    ListProperty,
    ObjectProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget


APP_TITLE = "Red Alarm"
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

ANDROID = platform == "android"


# ======================================================================
# 1. SMALL HELPERS
# ======================================================================

def new_alarm_id():
    return uuid.uuid4().hex


def format_time(hour, minute):
    """24h storage -> 12h display, e.g. (13, 5) -> '01:05 PM'."""
    ampm = "PM" if hour >= 12 else "AM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    return "{:02d}:{:02d} {}".format(h12, minute, ampm)


def format_days(days):
    if not days or not any(days):
        return "One-time"
    if all(days):
        return "Every day"
    return ", ".join(name for name, on in zip(DAY_NAMES, days) if on)


def compute_next_trigger_dt(alarm, now=None):
    """Next datetime this alarm should ring, strictly after `now`. Uses
    .get() with defaults throughout so one malformed/legacy record (e.g.
    missing a key from an older save) can't raise and break scheduling
    for every other alarm sitting after it in a loop."""
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
    """Deterministic int for Android PendingIntent request codes."""
    digest = hashlib.md5((alarm_id + salt).encode("utf-8")).hexdigest()
    return int(digest[:7], 16) % 1_000_000


class _CrashLogger(ExceptionHandler):
    """A silent exception anywhere used to be able to look exactly like 'the
    alarm just never fired' — Kivy's default behaviour is to let it crash
    the whole app, which is invisible if you're not watching a console
    window. This logs the full traceback to a file and tells Kivy to keep
    the app running instead of dying, so one bad alarm can't take the rest
    of the app down with it."""

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


# ----------------------------------------------------------------------
# ANDROID BRIDGE — every native call lives here, nowhere else in the file.
#
# How this actually wakes the phone, without any background service:
# AlarmManager.setAlarmClock() is the API Android reserves specifically for
# user-visible alarm clocks — the OS itself wakes the CPU at the exact time
# and directly re-launches THIS activity via a PendingIntent (no
# BroadcastReceiver, no 24/7 service needed; this is the same mechanism the
# stock Android Clock app uses). Once relaunched, this code acquires a
# WAKE_LOCK and sets window flags that draw over the lock screen and turn
# the screen on — that's what actually makes it "wake the phone" on top of
# merely firing on time.
# ----------------------------------------------------------------------
if ANDROID:
    from jnius import autoclass, cast
    from android.permissions import request_permissions, Permission
    from android import activity as android_activity

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
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
    KeyguardManager = autoclass("android.app.KeyguardManager")
    JString = autoclass("java.lang.String")

    def _activity():
        return PythonActivity.mActivity

    def _alarm_manager():
        return cast("android.app.AlarmManager",
                    _activity().getSystemService(Context.ALARM_SERVICE))

    def _alarm_pending_intent(alarm_id, request_code, fire_token=None):
        intent = Intent(_activity().getApplicationContext(), PythonActivity)
        intent.setAction("com.redalarm.FIRE_" + alarm_id)
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP)
        # putExtra(String, ...) is heavily overloaded (String, CharSequence,
        # char[], Object...), and pyjnius's overload resolution for a plain
        # Python str picked the char[] one here on a real device, which
        # getStringExtra() then rejects with a ClassCastException it
        # swallows and returns null for — the alarm fires, singleTask
        # correctly reuses the activity, onNewIntent correctly runs, and
        # then this one line is why it silently never reaches
        # handle_alarm_fired(). Wrapping in an explicit java.lang.String
        # removes the ambiguity entirely.
        intent.putExtra("alarm_id", JString(alarm_id))
        if fire_token is not None:
            intent.putExtra("fire_token", JString(str(fire_token)))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(_activity(), request_code, intent, flags)

    def android_schedule_alarm(alarm_id, trigger_dt, salt=""):
        request_code = stable_request_code(alarm_id, salt)
        fire_token = int(trigger_dt.timestamp() * 1000)
        pending_intent = _alarm_pending_intent(alarm_id, request_code, fire_token)
        info = AlarmClockInfo(fire_token, pending_intent)
        # setAlarmClock() fires exactly on time even through Doze, and the
        # OS shows its own little alarm-clock glyph in the status bar.
        _alarm_manager().setAlarmClock(info, pending_intent)

    def android_cancel_alarm(alarm_id, salt=""):
        request_code = stable_request_code(alarm_id, salt)
        # Extras don't matter for cancellation — only action/component/
        # request-code need to match the PendingIntent being cancelled.
        pending_intent = _alarm_pending_intent(alarm_id, request_code)
        _alarm_manager().cancel(pending_intent)

    def android_can_schedule_exact_alarms():
        try:
            return bool(_alarm_manager().canScheduleExactAlarms())
        except AttributeError:
            return True  # API < 31: no such restriction exists

    def android_request_exact_alarm_permission():
        intent = Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM)
        intent.setData(Uri.parse("package:" + _activity().getPackageName()))
        _activity().startActivity(intent)

    def android_is_ignoring_battery_optimizations():
        pm = cast("android.os.PowerManager",
                   _activity().getSystemService(Context.POWER_SERVICE))
        try:
            return bool(pm.isIgnoringBatteryOptimizations(_activity().getPackageName()))
        except AttributeError:
            return True  # API < 23: no battery-optimization concept

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

    def android_read_incoming_alarm():
        """(alarm_id, fire_token, action_kind) the activity was (re)launched
        with, or (None, None, None). fire_token changes every time (for a
        real fire AND for each notification-action tap), so comparing it
        against the last-seen value is how we avoid re-triggering the same
        event twice. action_kind is 'dismiss'/'snooze' for a notification
        action tap, or None for a genuine alarm firing / plain tap."""
        intent = _activity().getIntent()
        if intent is None:
            return None, None, None
        return (intent.getStringExtra("alarm_id"),
                intent.getStringExtra("fire_token"),
                intent.getStringExtra("action_kind"))

    _wake_lock = [None]

    def android_acquire_wake_lock():
        pm = cast("android.os.PowerManager",
                   _activity().getSystemService(Context.POWER_SERVICE))
        wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RedAlarm:AlarmWakeLock")
        wl.acquire(10 * 60 * 1000)  # 10-minute safety cap, released explicitly on stop
        _wake_lock[0] = wl

    def android_release_wake_lock():
        wl = _wake_lock[0]
        if wl is not None:
            try:
                if wl.isHeld():
                    wl.release()
            except Exception:
                pass
            _wake_lock[0] = None

    def android_show_over_lockscreen(show):
        """Draw above the lock screen and turn the display on (or undo it).
        This — not a 'display over other apps' permission — is the actual
        mechanism alarm apps use; it needs no user-grantable permission."""
        window = _activity().getWindow()
        flags = (WindowManagerFlags.FLAG_SHOW_WHEN_LOCKED
                | WindowManagerFlags.FLAG_TURN_SCREEN_ON
                | WindowManagerFlags.FLAG_KEEP_SCREEN_ON
                | WindowManagerFlags.FLAG_DISMISS_KEYGUARD)
        if show:
            window.addFlags(flags)
            if Build.VERSION.SDK_INT >= 27:
                _activity().setShowWhenLocked(True)
                _activity().setTurnScreenOn(True)
                keyguard = cast("android.app.KeyguardManager",
                                _activity().getSystemService(Context.KEYGUARD_SERVICE))
                keyguard.requestDismissKeyguard(_activity(), None)
        else:
            window.clearFlags(flags)
            if Build.VERSION.SDK_INT >= 27:
                _activity().setShowWhenLocked(False)
                _activity().setTurnScreenOn(False)

    def android_copy_content_uri_to_file(uri_string, dest_path):
        """Ringtone picks come back as content:// URIs; Kivy's audio
        backends want a plain file path, so copy the bytes once."""
        resolver = _activity().getContentResolver()
        input_stream = resolver.openInputStream(Uri.parse(uri_string))
        buf = bytearray(4096)
        with open(dest_path, "wb") as f:
            while True:
                n = input_stream.read(buf)
                if n == -1:
                    break
                f.write(bytes(buf[:n]))
        input_stream.close()
        return dest_path

    def android_take_persistable_permission(uri_string):
        """Extra safety net alongside copying the bytes immediately: asks
        for the read grant to survive app restarts/reboots too, in case
        anything ever needs to re-read the original URI later."""
        resolver = _activity().getContentResolver()
        resolver.takePersistableUriPermission(
            Uri.parse(uri_string), Intent.FLAG_GRANT_READ_URI_PERMISSION
        )

    # ---- "display over other apps" — the extra background-launch
    # exemption some OEM skins (MIUI/ColorOS/FuntouchOS/etc.) need on top
    # of the standard exact-alarm/battery permissions before they'll let a
    # backgrounded app pop an activity over the lock screen -------------
    def android_can_draw_overlays():
        try:
            return bool(Settings.canDrawOverlays(_activity()))
        except AttributeError:
            return True  # API < 23: permission doesn't exist

    def android_request_overlay_permission():
        intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
        intent.setData(Uri.parse("package:" + _activity().getPackageName()))
        _activity().startActivity(intent)

    # ---- native document picker for ringtones, replacing plyer on
    # Android (plyer's filechooser is flaky across OEM skins/API levels;
    # this gives full control and plain Android APIs only) --------------
    _OPEN_DOCUMENT_REQUEST_CODE = 9001

    def android_pick_audio_file(on_result):
        """on_result(uri_string_or_None) runs on the Kivy thread."""
        def _on_activity_result(request_code, result_code, data):
            if request_code != _OPEN_DOCUMENT_REQUEST_CODE:
                return
            uri_string = None
            try:
                if result_code == -1 and data is not None:  # RESULT_OK
                    uri = data.getData()
                    if uri is not None:
                        uri_string = uri.toString()
            except Exception as exc:
                print("[RedAlarm] file pick result error:", exc)
            try:
                android_activity.unbind(on_activity_result=_on_activity_result)
            except Exception:
                pass
            Clock.schedule_once(lambda dt: on_result(uri_string), 0)

        android_activity.bind(on_activity_result=_on_activity_result)
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("audio/*")
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        _activity().startActivityForResult(intent, _OPEN_DOCUMENT_REQUEST_CODE)

    def android_get_display_name(uri_string):
        """Best-effort human-readable file name for a content:// URI."""
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

    # ---- active-alarm notification (shown ONLY while ringing, normally
    # dismissible, with working Dismiss/Snooze action buttons) -----------
    # No "permanent" notification of any kind — this one is posted the
    # moment an alarm starts ringing and cancelled the moment it stops,
    # same as any ordinary Android notification. Its *other* job is the
    # lock-screen fix: its full-screen intent is the mechanism Android
    # actually wants for reliably launching an activity over the lock
    # screen on API 29+ (not the "display over other apps" permission) —
    # a HIGH-importance, CATEGORY_ALARM notification the system is allowed
    # to full-screen-launch even with no app window visible. Used
    # alongside the direct PendingIntent.getActivity() relaunch and the
    # show-over-lockscreen window flags; together these three are what
    # "properly appears when locked" requires in practice.
    _RING_CHANNEL_ID = "redalarm_ringing"
    _RING_NOTIF_ID = 1002

    def android_ensure_ring_channel():
        if Build.VERSION.SDK_INT >= 26:
            NotificationManager = autoclass("android.app.NotificationManager")
            NotificationChannel = autoclass("android.app.NotificationChannel")
            manager = cast("android.app.NotificationManager",
                            _activity().getSystemService(Context.NOTIFICATION_SERVICE))
            channel = NotificationChannel(JString(_RING_CHANNEL_ID), JString("Alarm ringing"),
                                          NotificationManager.IMPORTANCE_HIGH)
            channel.setBypassDnd(True)
            channel.enableVibration(False)   # we handle vibration ourselves
            manager.createNotificationChannel(channel)

    def _notification_action_pending_intent(alarm_id, kind):
        """kind is 'dismiss' or 'snooze' — tapping the action re-delivers to
        PythonActivity (same mechanism as a real alarm firing) with an
        action_kind extra so RedAlarmApp routes it to the ringing screen's
        dismiss/snooze instead of starting the alarm over again."""
        intent = Intent(_activity().getApplicationContext(), PythonActivity)
        intent.setAction("com.redalarm.{}_{}".format(kind.upper(), alarm_id))
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP)
        intent.putExtra("alarm_id", JString(alarm_id))
        intent.putExtra("action_kind", JString(kind))
        nonce = kind + str(int(datetime.datetime.now().timestamp() * 1000))
        intent.putExtra("fire_token", JString(nonce))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        request_code = stable_request_code(alarm_id, "notif_" + kind)
        return PendingIntent.getActivity(_activity(), request_code, intent, flags)

    def android_show_ring_notification(alarm_id, title, text):
        context = _activity().getApplicationContext()
        Notification = autoclass("android.app.Notification")
        AndroidR_drawable = autoclass("android.R$drawable")

        tap_pending_intent = _alarm_pending_intent(
            alarm_id, stable_request_code(alarm_id, "ring_tap"),
            fire_token="tap" + str(int(datetime.datetime.now().timestamp() * 1000)),
        )
        dismiss_pi = _notification_action_pending_intent(alarm_id, "dismiss")
        snooze_pi = _notification_action_pending_intent(alarm_id, "snooze")

        if Build.VERSION.SDK_INT >= 26:
            builder = autoclass("android.app.Notification$Builder")(context, JString(_RING_CHANNEL_ID))
        else:
            builder = autoclass("android.app.Notification$Builder")(context)
            builder.setPriority(2)  # Notification.PRIORITY_MAX
        builder.setContentTitle(JString(title))
        builder.setContentText(JString(text))
        builder.setSmallIcon(AndroidR_drawable.ic_lock_idle_alarm)
        builder.setCategory(Notification.CATEGORY_ALARM)
        builder.setFullScreenIntent(tap_pending_intent, True)
        builder.setContentIntent(tap_pending_intent)
        builder.addAction(AndroidR_drawable.ic_menu_close_clear_cancel, JString("Dismiss"), dismiss_pi)
        builder.addAction(AndroidR_drawable.ic_popup_reminder, JString("Snooze"), snooze_pi)
        builder.setOngoing(False)    # normal, swipeable notification
        builder.setAutoCancel(True)  # tapping it (body or an action) clears it
        manager = cast("android.app.NotificationManager",
                        context.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.notify(_RING_NOTIF_ID, builder.build())

    def android_cancel_ring_notification():
        context = _activity().getApplicationContext()
        manager = cast("android.app.NotificationManager",
                        context.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.cancel(_RING_NOTIF_ID)

    # ---- vibration -------------------------------------------------------
    _vibrator = [None]

    def android_vibrate_start():
        vibrator = cast("android.os.Vibrator",
                         _activity().getSystemService(Context.VIBRATOR_SERVICE))
        if vibrator is None or not vibrator.hasVibrator():
            return
        pattern = [0, 800, 500]   # wait, buzz, pause — repeats from index 1
        if Build.VERSION.SDK_INT >= 26:
            VibrationEffect = autoclass("android.os.VibrationEffect")
            effect = VibrationEffect.createWaveform(pattern, 1)
            vibrator.vibrate(effect)
        else:
            vibrator.vibrate(pattern, 1)
        _vibrator[0] = vibrator

    def android_vibrate_stop():
        vibrator = _vibrator[0]
        if vibrator is not None:
            try:
                vibrator.cancel()
            except Exception:
                pass
            _vibrator[0] = None

    # ---- full-screen-intent permission (Android 14+ can gate it) --------
    def android_can_use_full_screen_intent():
        if Build.VERSION.SDK_INT < 34:
            return True
        manager = cast("android.app.NotificationManager",
                        _activity().getSystemService(Context.NOTIFICATION_SERVICE))
        return bool(manager.canUseFullScreenIntent())

    def android_request_full_screen_intent_permission():
        if Build.VERSION.SDK_INT < 34:
            return
        intent = Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT)
        intent.setData(Uri.parse("package:" + _activity().getPackageName()))
        _activity().startActivity(intent)

    # ---- Samsung "Never sleeping apps" guidance --------------------------
    def android_is_samsung():
        try:
            return str(Build.MANUFACTURER).lower() == "samsung"
        except Exception:
            return False

    # Samsung has no public intent for the exact "Never sleeping apps"
    # screen, and the Device Care component names move between One UI
    # versions — so try the known Device Care battery screens in order,
    # then fall back to standard Android screens that always exist.
    _SAMSUNG_BATTERY_COMPONENTS = [
        ("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity"),
        ("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),
        ("com.samsung.android.sm_cn", "com.samsung.android.sm.ui.battery.BatteryActivity"),
        ("com.samsung.android.sm", "com.samsung.android.sm.ui.battery.BatteryActivity"),
    ]

    def android_open_samsung_battery_settings():
        """Returns a short string saying which screen actually opened."""
        ComponentName = autoclass("android.content.ComponentName")
        for pkg, cls in _SAMSUNG_BATTERY_COMPONENTS:
            try:
                intent = Intent()
                intent.setComponent(ComponentName(JString(pkg), JString(cls)))
                intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                _activity().startActivity(intent)
                print("[RedAlarm] opened Samsung battery screen:", pkg, cls)
                return "samsung-device-care"
            except Exception as exc:
                print("[RedAlarm] samsung component not available:", cls, exc)
        try:
            intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            _activity().startActivity(intent)
            return "battery-optimization-list"
        except Exception as exc:
            print("[RedAlarm] battery optimization list unavailable:", exc)
        intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        intent.setData(Uri.parse("package:" + _activity().getPackageName()))
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        _activity().startActivity(intent)
        return "app-details"


# ======================================================================
# 2. STORAGE + SCHEDULING
# ======================================================================

class AlarmStore:
    """Alarms as plain JSON, written atomically."""

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
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(list(self._alarms.values()), f, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.path)

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
    """On desktop, alarms are simulated purely in Python/Kivy (Android would
    use AlarmManager instead — no OS-level wakeup here).

    IMPORTANT FIX: this used to schedule one long `Clock.schedule_once(fn,
    big_delay)` per alarm. That is fragile in practice on Windows: if the
    window is minimized/unfocused for a while, Kivy's render-driven Clock
    can stall, and a single timer computed *in advance* has no way to
    "catch up" afterwards — it just never fires. That matches exactly what
    you were seeing (alarms silently not buzzing after a while).

    The fix is a small POLLING loop instead: every pending alarm's target
    time is just a value in a dict, and a `schedule_interval` ticking once
    a second checks "has this time already passed?". Even if the Clock
    gets throttled for a stretch, the very next tick after it resumes will
    notice the time has passed and fire immediately — it's self-correcting
    instead of depending on one long timer firing exactly on schedule.
    """

    def __init__(self, on_desktop_fire):
        self._pending = {}    # key (alarm_id[+salt]) -> (alarm_id, trigger_dt)
        self._on_desktop_fire = on_desktop_fire
        self._poll_event = Clock.schedule_interval(self._poll, 1.0)

    def schedule(self, alarm, now=None):
        trigger_dt = compute_next_trigger_dt(alarm, now=now)
        # Kept on both platforms — desktop uses it to self-fire via _poll,
        # Android just uses it for the Home screen's "next alarm in..." line
        # (the real Android firing comes from AlarmManager relaunching the
        # activity, not from this dict).
        self._pending[alarm["id"]] = (alarm["id"], trigger_dt)
        if ANDROID:
            android_schedule_alarm(alarm["id"], trigger_dt, salt="")
        return trigger_dt

    def cancel(self, alarm):
        self._pending.pop(alarm["id"], None)
        if ANDROID:
            android_cancel_alarm(alarm["id"], salt="")

    def schedule_snooze(self, alarm, trigger_dt):
        self._pending[alarm["id"] + "snooze"] = (alarm["id"], trigger_dt)
        if ANDROID:
            android_schedule_alarm(alarm["id"], trigger_dt, salt="snooze")

    def cancel_snooze(self, alarm):
        self._pending.pop(alarm["id"] + "snooze", None)
        if ANDROID:
            android_cancel_alarm(alarm["id"], salt="snooze")

    def next_trigger_for(self, alarm_id):
        """Soonest pending trigger_dt for this alarm (regular or snoozed),
        or None. Used by the Home screen's "next alarm in..." line."""
        times = [t for key, (aid, t) in self._pending.items() if aid == alarm_id]
        return min(times) if times else None

    def _poll(self, dt):
        # On Android, firing is driven by AlarmManager relaunching the
        # activity (see RedAlarmApp._check_incoming_alarm) — polling here
        # would be redundant and risks a double-fire.
        if ANDROID or not self._pending:
            return
        now = datetime.datetime.now()
        due = [key for key, (_, t) in self._pending.items() if t <= now]
        for key in due:
            alarm_id, _ = self._pending.pop(key)
            try:
                self._on_desktop_fire(alarm_id)
            except Exception as exc:
                # One bad alarm record must never take the others down with
                # it — print and keep going.
                print("[RedAlarm] error firing alarm {}: {}".format(alarm_id, exc))


DEFAULT_RINGTONE_NAME = "Default Alarm Tone"


def ensure_default_ringtone(cache_dir):
    """Synthesize a small looping "beep-beep... beep-beep..." WAV once
    (pure stdlib — no bundled audio asset, no copyright/licensing to worry
    about) so every new alarm has a working sound without the user ever
    having to open a file picker."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "default_alarm.wav")
    if os.path.exists(path):
        return path

    import wave
    import struct

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
    for _ in range(2):                 # two quick beeps...
        samples += tone(1100, 0.14)
        samples += silence(0.09)
    samples += silence(0.38)           # ...then a pause before it loops

    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return path


def pick_ringtone_file(on_chosen, on_error):
    """Open a file picker. On Android this goes straight to the native
    document picker (plyer's filechooser is flaky on several OEM skins/API
    levels — the symptom is exactly "I can see the files but picking one
    does nothing"). On desktop it tries plyer, then falls back to tkinter."""

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
            filters=[["Audio files", "*.mp3", "*.wav", "*.ogg"]],
            multiple=False,
        )
        return
    except Exception:
        pass

    if not ANDROID:
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                filetypes=[("Audio files", "*.mp3 *.wav *.ogg")]
            )
            root.destroy()
            _deliver(path or None)
            return
        except Exception:
            pass

    on_error("Couldn't open the file picker (try: pip install plyer).")


def resolve_ringtone_for_playback(raw_path, app_storage_dir):
    """Desktop paths are used as-is. An Android content:// URI is copied
    into app storage once (SoundLoader can't open content:// directly),
    then the cached copy is reused on every later ring."""
    if raw_path and raw_path.startswith("content://"):
        if not ANDROID:
            return None
        os.makedirs(app_storage_dir, exist_ok=True)
        dest = os.path.join(
            app_storage_dir,
            hashlib.md5(raw_path.encode("utf-8")).hexdigest() + ".audio",
        )
        if not os.path.exists(dest):
            try:
                android_copy_content_uri_to_file(raw_path, dest)
            except Exception as exc:
                print("[RedAlarm] couldn't copy ringtone URI:", exc)
                return None
        return dest
    return raw_path


# ======================================================================
# 3. CUSTOM WIDGETS (auto-registered with Kivy's Factory, so alarm.kv can
#    use them by class name)
# ======================================================================

class AnalogClock(Widget):
    """Canvas-drawn analog clock. Fills whatever box it is given and draws
    a centred circle, so it never gets squashed into an ellipse."""

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
            a = math.radians(90 - deg)   # 0 deg = 12 o'clock, clockwise
            return cx + r * math.cos(a), cy + r * math.sin(a)

        font_px = max(12, int(radius * 0.15))

        with self.canvas:
            # soft red glow, face, rim
            Color(0.42, 0.06, 0.08, 0.30)
            Ellipse(pos=(cx - radius * 1.07, cy - radius * 1.07),
                    size=(radius * 2.14, radius * 2.14))
            Color(0.055, 0.05, 0.055, 1)
            Ellipse(pos=(cx - radius, cy - radius), size=(radius * 2, radius * 2))
            Color(0.82, 0.10, 0.13, 1)
            Line(circle=(cx, cy, radius), width=dp(2.4))

            # 60 ticks: thin grey minutes, brighter hours, red quarters
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
                Line(points=[*pt(deg, radius * r_in), *pt(deg, radius * 0.965)],
                     width=width)

            # numerals 1..12
            for n in range(1, 13):
                tex = self._numeral_texture(n, font_px)
                x, y = pt(n * 30, radius * 0.72)
                if n % 3 == 0:
                    Color(0.96, 0.96, 0.96, 1)
                else:
                    Color(0.62, 0.58, 0.58, 1)
                Rectangle(texture=tex, size=tex.size,
                          pos=(x - tex.width / 2, y - tex.height / 2))

            # hour + minute hands
            Color(0.96, 0.96, 0.96, 1)
            Line(points=[cx, cy, *pt(hour * 30, radius * 0.48)],
                 width=dp(3.8), cap="round")
            Color(0.86, 0.83, 0.83, 1)
            Line(points=[cx, cy, *pt(minute * 6, radius * 0.78)],
                 width=dp(2.6), cap="round")

            # second hand (with a short tail) + centre pin
            Color(0.90, 0.12, 0.15, 1)
            Line(points=[*pt(now.second * 6 + 180, radius * 0.16),
                         *pt(now.second * 6, radius * 0.86)],
                 width=dp(1.3), cap="round")
            Ellipse(pos=(cx - dp(6), cy - dp(6)), size=(dp(12), dp(12)))
            Color(0.05, 0.05, 0.05, 1)
            Ellipse(pos=(cx - dp(2.5), cy - dp(2.5)), size=(dp(5), dp(5)))


class IOSToggle(ButtonBehavior, Widget):
    """Rounded iOS-style switch: RED when on, GREY when off. Exposes a normal
    `active` BooleanProperty, so `on_active:` works in kv like a Switch."""

    active = BooleanProperty(False)
    _thumb = NumericProperty(0)   # 0 = left/off, 1 = right/on (animated)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._thumb = 1 if self.active else 0
        self.bind(pos=self._redraw, size=self._redraw, _thumb=self._redraw)
        self._redraw()

    def on_active(self, *_):
        Animation.cancel_all(self, "_thumb")
        Animation(_thumb=1 if self.active else 0, duration=0.15,
                  t="out_quad").start(self)
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
            RoundedRectangle(pos=self.pos, size=self.size,
                             radius=[self.height / 2])
            Color(1, 1, 1, 1)
            Ellipse(pos=(self.x + pad + travel * self._thumb, self.y + pad),
                    size=(d, d))


class HomeButton(Button):
    """Rounded flat-colour button (colours set from kv)."""
    bg_color = ListProperty([0.11, 0.09, 0.09, 1])
    text_color = ListProperty([0.96, 0.96, 0.96, 1])


class DigitInput(TextInput):
    """Digits only, capped length, and selects its content when tapped so you
    can just type a new value instead of deleting the old one."""
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
    """The tappable time/label area of a row (opens the edit screen).
    Gets its own text properties (bound from AlarmRow in alarm.kv) instead
    of reaching through `root.row.xxx`, which proved unreliable."""
    row = ObjectProperty(None)
    time_text = StringProperty("")
    sub_text = StringProperty("")
    dim = BooleanProperty(False)

    def on_release(self):
        if self.row is not None:
            self.row.on_row_press()


# ======================================================================
# 4. SCREENS
# ======================================================================

class HomeScreen(Screen):
    date_text = StringProperty("")
    next_alarm_text = StringProperty("")
    _next_alarm_event = None

    def on_pre_enter(self, *args):
        self.date_text = datetime.datetime.now().strftime("%A, %d %B")
        self._refresh_next_alarm()
        if self._next_alarm_event is None:
            # Ticks every second so the countdown at the bottom of the
            # clock is actually live, not a stale snapshot from whenever
            # you last opened this screen.
            self._next_alarm_event = Clock.schedule_interval(
                lambda dt: self._refresh_next_alarm(), 1
            )

    def on_leave(self, *args):
        if self._next_alarm_event is not None:
            self._next_alarm_event.cancel()
            self._next_alarm_event = None

    def _refresh_next_alarm(self, *args):
        now = datetime.datetime.now()
        best = None
        for alarm in App.get_running_app().store.all():
            if not alarm.get("enabled", True):
                continue
            trigger = compute_next_trigger_dt(alarm, now=now)
            if best is None or trigger < best:
                best = trigger

        if best is None:
            self.next_alarm_text = "No alarms set"
            return

        total_seconds = max(0, int((best - now).total_seconds()))
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days > 0:
            when = "{}d {}h {}m".format(days, hours, minutes)
        elif hours > 0:
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
        if value == self.enabled:      # programmatic sync, not a user tap
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
    overlay_ok = BooleanProperty(True)
    fsi_ok = BooleanProperty(True)

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
            try:
                self.overlay_ok = android_can_draw_overlays()
            except Exception:
                self.overlay_ok = True
            try:
                self.fsi_ok = android_can_use_full_screen_intent()
            except Exception:
                self.fsi_ok = True
        else:
            self.exact_alarm_ok = True
            self.battery_ok = True
            self.overlay_ok = True
            self.fsi_ok = True

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

    def open_fsi_settings(self):
        if ANDROID:
            try:
                android_request_full_screen_intent_permission()
            except Exception as exc:
                print("[RedAlarm] full-screen-intent settings error:", exc)

    def open_overlay_settings(self):
        if ANDROID:
            try:
                android_request_overlay_permission()
            except Exception as exc:
                print("[RedAlarm] overlay settings error:", exc)

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
                ring.finish(reason="delete")
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

        popup = Popup(title="", content=content, size_hint=(0.8, 0.3),
                      separator_height=0, background_color=(0.07, 0.07, 0.07, 1))
        popup.yes_btn = yes_btn
        cancel_btn.bind(on_release=popup.dismiss)
        yes_btn.bind(on_release=do_delete)
        self._delete_popup = popup
        popup.open()


class TimePickerPopup(Popup):
    """Automatic HOUR -> MINUTES -> AM/PM time picker.

    Opens on HOUR; picking an hour jumps to MINUTES (5-minute steps);
    picking minutes jumps to AM/PM. The three step chips along the top
    always show which part is active (and can be tapped to go back), the
    live preview updates as you pick, and Cancel/OK are always visible so
    OK works at any point (the pickers are pre-filled with the starting
    time). on_confirm(hour12, minute, ampm) fires once, on OK."""

    RED = (0.82, 0.10, 0.13, 1)
    CARD = (0.11, 0.09, 0.09, 1)
    SUB = (0.62, 0.58, 0.58, 1)
    STEPS = ("hour", "minute", "ampm")
    STEP_TITLES = {"hour": "HOUR", "minute": "MINUTES", "ampm": "AM / PM"}

    def __init__(self, hour12, minute, ampm, on_confirm, **kwargs):
        self.hour12 = hour12
        self.minute = (minute // 5) * 5      # snap to the 5-minute grid
        self.ampm = ampm
        self.step = "hour"
        self._on_confirm = on_confirm
        self._grid_container = BoxLayout(orientation="vertical")
        super().__init__(
            title="", separator_height=0,
            background_color=(0.03, 0.03, 0.035, 1),
            size_hint=(0.9, 0.78),
            **kwargs
        )
        self.content = self._build_content()
        self._rebuild()

    def _build_content(self):
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))

        self._preview_label = Label(
            text="", font_size="40sp", bold=True, color=(0.96, 0.96, 0.96, 1),
            size_hint_y=None, height=dp(64),
        )
        root.add_widget(self._preview_label)

        chips = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        self._chips = {}
        for key in self.STEPS:
            chip = Button(text=self.STEP_TITLES[key], background_normal="",
                          background_down="", bold=True, font_size="12.5sp")
            chip.bind(on_release=lambda inst, k=key: self._goto(k))
            self._chips[key] = chip
            chips.add_widget(chip)
        root.add_widget(chips)

        root.add_widget(self._grid_container)

        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(12))
        cancel_btn = Button(text="Cancel", background_normal="", background_down="",
                            background_color=(0, 0, 0, 0), color=self.SUB)
        ok_btn = Button(text="OK", background_normal="", background_down="",
                        background_color=(0, 0, 0, 0), color=self.RED, bold=True)
        cancel_btn.bind(on_release=lambda *_: self.dismiss())
        ok_btn.bind(on_release=self._confirm)
        buttons.add_widget(Widget())
        buttons.add_widget(cancel_btn)
        buttons.add_widget(ok_btn)
        root.add_widget(buttons)
        return root

    def _goto(self, step):
        self.step = step
        self._rebuild()

    def _rebuild(self):
        # live preview, with the part being edited drawn in red
        hh = "{:02d}".format(self.hour12)
        mm = "{:02d}".format(self.minute)
        ap = self.ampm
        def mark(text, active):
            return "[color=d11a21]{}[/color]".format(text) if active else text
        self._preview_label.markup = True
        self._preview_label.text = "{}:{} {}".format(
            mark(hh, self.step == "hour"),
            mark(mm, self.step == "minute"),
            mark(ap, self.step == "ampm"),
        )
        for key, chip in self._chips.items():
            active = (key == self.step)
            chip.background_color = self.RED if active else self.CARD
            chip.color = (1, 1, 1, 1) if active else self.SUB

        self._grid_container.clear_widgets()
        if self.step == "ampm":
            grid = GridLayout(cols=2, spacing=dp(12), padding=(0, dp(10)))
            for value in ("AM", "PM"):
                btn = Button(text=value, background_normal="", background_down="",
                             bold=True, font_size="30sp")
                btn.background_color = self.RED if value == self.ampm else self.CARD
                btn.color = (1, 1, 1, 1) if value == self.ampm else self.SUB
                btn.bind(on_release=lambda inst, v=value: self._pick(v))
                grid.add_widget(btn)
        else:
            grid = GridLayout(cols=4, spacing=dp(8), padding=(0, dp(6)))
            if self.step == "hour":
                values, current = list(range(1, 13)), self.hour12
            else:
                values, current = list(range(0, 60, 5)), self.minute
            for v in values:
                btn = Button(text="{:02d}".format(v), background_normal="",
                             background_down="", bold=True, font_size="17sp")
                btn.background_color = self.RED if v == current else self.CARD
                btn.color = (1, 1, 1, 1)
                btn.bind(on_release=lambda inst, val=v: self._pick(val))
                grid.add_widget(btn)
        self._grid_container.add_widget(grid)

    def _pick(self, value):
        if self.step == "hour":
            self.hour12 = value
            self.step = "minute"        # auto-advance: HOUR -> MINUTES
        elif self.step == "minute":
            self.minute = value
            self.step = "ampm"          # auto-advance: MINUTES -> AM/PM
        else:
            self.ampm = value           # AM/PM is the last step; OK confirms
        self._rebuild()

    def _confirm(self, *_):
        if self._on_confirm:
            self._on_confirm(self.hour12, self.minute, self.ampm)
        self.dismiss()


class AlarmEditScreen(Screen):
    editing_id = StringProperty("")
    ampm = StringProperty("AM")
    days_selected = ListProperty([False] * 7)
    sound_path = StringProperty("")
    sound_name = StringProperty("No sound chosen")
    vibrate = BooleanProperty(False)
    _auto_picker_pending = False

    def on_enter(self, *args):
        # "Add New Alarm" opens straight into the HOUR -> MINUTES -> AM/PM
        # picker, pre-filled with the current time (editing an existing
        # alarm just shows its saved time; tap "Pick time" to change it).
        if self._auto_picker_pending:
            self._auto_picker_pending = False
            Clock.schedule_once(lambda dt: self.open_time_picker(), 0.15)

    def load_alarm(self, alarm_id):
        ids = self.ids
        ids.error_label.text = ""
        self._auto_picker_pending = alarm_id is None

        if alarm_id is None:
            self.editing_id = ""
            # New alarm defaults to the device's current time, not a fixed
            # 7:00 AM — falls back to 00:00 if anything about "now" fails.
            try:
                now = datetime.datetime.now()
                h12 = now.hour % 12 or 12
                ids.input_hour.text = "{:02d}".format(h12)
                ids.input_minute.text = "{:02d}".format(now.minute)
                self.ampm = "PM" if now.hour >= 12 else "AM"
            except Exception:
                ids.input_hour.text = "12"
                ids.input_minute.text = "00"
                self.ampm = "AM"
            self.days_selected = [False] * 7
            self.sound_path = ""
            self.sound_name = "Default beep (tap to change)"
            self.vibrate = False
            ids.dismiss_min.text = "5"
            ids.dismiss_sec.text = "0"
            ids.snooze_min.text = "5"
            ids.snooze_sec.text = "0"
            ids.label_input.text = ""
            ids.delete_btn.opacity = 0
            ids.delete_btn.disabled = True
        else:
            alarm = App.get_running_app().store.get(alarm_id)
            if not alarm:
                return
            self.editing_id = alarm_id
            h, m = alarm["hour"], alarm["minute"]
            self.ampm = "PM" if h >= 12 else "AM"
            h12 = h % 12 or 12
            ids.input_hour.text = "{:02d}".format(h12)
            ids.input_minute.text = "{:02d}".format(m)
            self.days_selected = list(alarm.get("days") or [False] * 7)
            self.sound_path = alarm.get("sound_path", "")
            self.sound_name = alarm.get("sound_name") or "Default beep"
            self.vibrate = bool(alarm.get("vibrate", False))
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
        """Driven by each day button's own state, so the data can never
        drift out of sync with what's drawn."""
        if self.days_selected[index] != on:
            days = list(self.days_selected)
            days[index] = on
            self.days_selected = days

    def set_ampm(self, value):
        self.ampm = value

    def open_time_picker(self):
        try:
            h12 = int(self.ids.input_hour.text)
        except (TypeError, ValueError):
            h12 = 12
        try:
            minute = int(self.ids.input_minute.text)
        except (TypeError, ValueError):
            minute = 0
        popup = TimePickerPopup(h12, minute, self.ampm, self._apply_picked_time)
        popup.open()

    def _apply_picked_time(self, hour12, minute, ampm):
        self.ids.input_hour.text = "{:02d}".format(hour12)
        self.ids.input_minute.text = "{:02d}".format(minute)
        self.ampm = ampm

    def choose_sound(self):
        self.ids.error_label.text = ""
        pick_ringtone_file(self._on_sound_picked, self._on_picker_error)

    def _on_picker_error(self, message):
        self.ids.error_label.text = message

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

            # ROOT CAUSE of "selected but plays Silent": a content:// URI's
            # read permission is only reliably valid for the current app
            # session unless explicitly persisted, and alarms often fire
            # hours/days later after the process has been killed and
            # restarted by AlarmManager — by then the grant can be gone and
            # the file read silently fails at ring time with no fallback.
            # Fix: copy the bytes to our own storage right now, at pick
            # time, while the grant is definitely still valid, and store
            # that durable local path instead of the URI.
            try:
                android_take_persistable_permission(path)
            except Exception as exc:
                print("[RedAlarm] could not persist URI permission:", exc)
            app = App.get_running_app()
            try:
                local_path = resolve_ringtone_for_playback(path, app.ringtone_cache_dir)
            except Exception as exc:
                local_path = None
                print("[RedAlarm] immediate ringtone copy raised:", exc)
            if not local_path or not os.path.exists(local_path):
                print("[RedAlarm] immediate ringtone copy FAILED for", path)
                self.ids.error_label.text = (
                    "Couldn't read that file — try picking it again."
                )
                return
            print("[RedAlarm] ringtone copied to durable local path:", local_path)
            self.sound_path = local_path
        else:
            self.sound_path = path

        self.sound_name = name or os.path.basename(path.replace("\\", "/"))

    def preview_sound(self):
        """Plays the chosen (or default) sound for ~2.5s, completely outside
        the alarm-firing pipeline — the fastest way to tell whether audio
        works on this machine at all, separate from scheduling."""
        self.ids.error_label.text = ""
        app = App.get_running_app()
        path = self.sound_path or app.default_ringtone_path
        try:
            sound = SoundLoader.load(path)
        except Exception as exc:
            self.ids.error_label.text = "Preview failed: {}".format(exc)
            return
        if sound is None:
            self.ids.error_label.text = (
                "Couldn't load that sound on this machine's audio backend."
            )
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
            ring.finish(reason="delete")
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

        # 12h + AM/PM -> 24h for storage
        if self.ampm == "PM":
            hour = 12 if h12 == 12 else h12 + 12
        else:
            hour = 0 if h12 == 12 else h12

        try:
            total_dismiss = (int(ids.dismiss_min.text or "0") * 60
                             + int(ids.dismiss_sec.text or "0"))
            total_snooze = (int(ids.snooze_min.text or "0") * 60
                            + int(ids.snooze_sec.text or "0"))
        except (TypeError, ValueError):
            return self._fail("Enter valid durations.")
        if total_dismiss <= 0:
            return self._fail("Auto-dismiss must be at least 1 second.")
        if total_snooze <= 0:
            return self._fail("Snooze must be at least 1 second.")

        app = App.get_running_app()
        alarm = app.store.get(self.editing_id) or {}
        # No custom sound picked -> fall back to the built-in default beep,
        # so a missing/failed file picker can never block saving an alarm.
        sound_path = self.sound_path or app.default_ringtone_path
        sound_name = self.sound_name if self.sound_path else "Default beep"
        alarm.update({
            "id": self.editing_id or new_alarm_id(),
            "hour": hour,
            "minute": minute,
            "days": list(self.days_selected),
            "label": ids.label_input.text.strip(),
            "sound_path": sound_path,
            "sound_name": sound_name,
            "auto_dismiss_sec": total_dismiss,
            "snooze_sec": total_snooze,
            "vibrate": self.vibrate,
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
        # Safety net: whichever way we leave this screen, sound + timer stop.
        self._stop_common()

    def start_ringing(self, alarm):
        self._stop_common()                  # kill any previous ring first
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
            try:
                android_show_ring_notification(
                    alarm["id"], self.label_text, self.time_text
                )
            except Exception as exc:
                print("[RedAlarm] full-screen notification error:", exc)
            if alarm.get("vibrate", False):
                try:
                    android_vibrate_start()
                    print("[RedAlarm] ring: vibration started")
                except Exception as exc:
                    print("[RedAlarm] vibration start error:", exc)

        app = App.get_running_app()
        saved_path = alarm.get("sound_path", "")
        print("[RedAlarm] ring: saved sound_path =", saved_path)
        path = resolve_ringtone_for_playback(saved_path, app.ringtone_cache_dir)
        print("[RedAlarm] ring: resolved playback path =", path)

        # Never actually "play nothing" just because the saved ringtone
        # couldn't be read (deleted file, a legacy content:// URI whose
        # grant expired, etc.) — fall back to the built-in default beep so
        # "Silent" only ever happens if the user genuinely picked Silent.
        if not path or not os.path.exists(path):
            print("[RedAlarm] ring: resolved path missing, falling back to default")
            path = app.default_ringtone_path

        if path:
            try:
                sound = SoundLoader.load(path)
                if sound is not None:
                    sound.loop = True
                    sound.play()
                    self._sound = sound
                    print("[RedAlarm] ring: playback started:", path)
                else:
                    print("[RedAlarm] ring: SoundLoader returned None for", path)
                    if path != app.default_ringtone_path:
                        self._sound = self._try_load_and_play(app.default_ringtone_path)
            except Exception as exc:
                print("[RedAlarm] ring: sound error:", exc)
                self._sound = None
                if path != app.default_ringtone_path:
                    self._sound = self._try_load_and_play(app.default_ringtone_path)
        else:
            print("[RedAlarm] ring: no sound path available at all (not even default)")

        self._remaining_seconds = max(1, int(alarm.get("auto_dismiss_sec", 300) or 300))
        self._update_countdown_text()

        # ONE timer drives both the digits and the auto-dismiss: the tick
        # that reaches zero is the tick that ends the alarm, so the display
        # and the real cutoff can never disagree.
        self._countdown_event = Clock.schedule_interval(
            lambda dt: self._tick_countdown(dt, session), 1
        )

    def _try_load_and_play(self, path):
        """Last-resort fallback load, used when the chosen ringtone fails —
        returns the playing Sound object, or None if even this fails."""
        if not path:
            return None
        try:
            sound = SoundLoader.load(path)
            if sound is not None:
                sound.loop = True
                sound.play()
                print("[RedAlarm] ring: fallback playback started:", path)
                return sound
            print("[RedAlarm] ring: fallback SoundLoader also returned None")
        except Exception as exc:
            print("[RedAlarm] ring: fallback sound error:", exc)
        return None

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
        self._ringing = False
        self._ring_session += 1              # invalidates any queued tick

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

        if ANDROID:
            try:
                android_show_over_lockscreen(False)
                android_release_wake_lock()
            except Exception as exc:
                print("[RedAlarm] wake/lockscreen release error:", exc)
            try:
                android_vibrate_stop()
            except Exception as exc:
                print("[RedAlarm] vibration stop error:", exc)
            try:
                android_cancel_ring_notification()
            except Exception as exc:
                print("[RedAlarm] full-screen notification cancel error:", exc)

    def dismiss_pressed(self):
        if self._ringing:
            self.finish(reason="dismiss")

    def snooze_pressed(self):
        if self._ringing:
            self.finish(reason="snooze")

    def finish(self, reason):
        # Audio is stopped FIRST so it can never keep playing behind the UI.
        current_alarm_id = self.alarm_id
        self._stop_common()

        app = App.get_running_app()
        alarm = app.store.get(current_alarm_id)
        if alarm:
            if reason == "snooze":
                snooze_sec = max(1, int(alarm.get("snooze_sec", 300) or 300))
                app.scheduler.schedule_snooze(
                    alarm,
                    datetime.datetime.now() + datetime.timedelta(seconds=snooze_sec),
                )
            elif reason != "delete":
                # One-time alarms switch themselves off after ringing.
                # Repeating ones stay on (next occurrence already queued).
                if not any(alarm.get("days") or []):
                    alarm["enabled"] = False
                    app.store.put(alarm)

        self.alarm_id = ""
        self.countdown_text = ""
        app.root.current = "home"


class RootManager(ScreenManager):
    pass


# ======================================================================
# 5. APP
# ======================================================================

class RedAlarmApp(App):
    _ready = False            # True once the real UI + store + scheduler exist
    _queued_intents = None    # intents that arrive before _ready (replayed after)

    def build(self):
        """Returns a tiny pure-Python splash IMMEDIATELY. The expensive part
        (parsing the big alarm.kv, building every screen, loading alarms)
        runs on the very next tick in _finish_startup(), so the user sees a
        deliberate RedAlarm splash instead of a frozen blank window."""
        self.title = APP_TITLE
        self._queued_intents = []

        # Cheap, and wanted before anything else can go wrong: log
        # uncaught exceptions to a file instead of dying silently.
        self.crash_log_path = os.path.join(self.user_data_dir, "crash_log.txt")
        ExceptionManager.add_handler(_CrashLogger(self.crash_log_path))

        if not ANDROID:
            Window.size = (380, 720)
        else:
            # THE fix for "AlarmManager fires but start_ringing() never
            # runs" when the app is alive-but-backgrounded: Android
            # delivers the alarm intent via onNewIntent, which p4a's stock
            # PythonActivity doesn't mirror into getIntent(). Binding the
            # documented Python hook hands us the fresh Intent directly.
            # Registered here (not deferred) so no alarm intent can slip
            # past during startup — _dispatch_intent queues it until the
            # UI is ready.
            android_activity.bind(on_new_intent=self._on_new_intent)

        self._splash = self._build_splash()
        Clock.schedule_once(self._finish_startup, 0.1)
        return self._splash

    

    def _finish_startup(self, dt):
        # ---- everything needed to show the real UI ----
        Builder.load_file("alarm.kv")
        self.store = AlarmStore(os.path.join(self.user_data_dir, "alarms.json"))
        self.ringtone_cache_dir = os.path.join(self.user_data_dir, "ringtones")
        # The path is known up front; the file itself is (re)created
        # lazily just below if it's missing, never on the UI critical path.
        self.default_ringtone_path = os.path.join(self.ringtone_cache_dir, "default_alarm.wav")
        self.scheduler = AlarmScheduler(on_desktop_fire=self.handle_alarm_fired)

        root = RootManager()
        root.add_widget(HomeScreen(name="home"))
        root.add_widget(AlarmListScreen(name="list"))
        root.add_widget(AlarmEditScreen(name="edit"))
        root.add_widget(AlarmRingScreen(name="ring"))
        root.current = "home"

        Window.remove_widget(self._splash)
        Window.add_widget(root)
        self.root = root
        self._ready = True

        # ---- alarm recovery: NOT deferred any further than this ----
        if not os.path.exists(self.default_ringtone_path):
            # first run only; needed before anything can ring/preview
            self.default_ringtone_path = ensure_default_ringtone(self.ringtone_cache_dir)
        if ANDROID:
            try:
                android_ensure_ring_channel()
            except Exception as exc:
                print("[RedAlarm] notification channel error:", exc)
            try:
                android_request_runtime_permissions()
            except Exception as exc:
                print("[RedAlarm] permission request error:", exc)

        for alarm in self.store.all():
            if alarm.get("enabled", True):
                try:
                    self.scheduler.schedule(alarm)
                except Exception as exc:
                    # A single bad record must never stop every alarm after
                    # it in this list from being armed too.
                    print("[RedAlarm] could not schedule alarm {}: {}"
                          .format(alarm.get("id"), exc))

        self._check_incoming_alarm()
        queued, self._queued_intents = self._queued_intents, []
        for args in queued:
            self._dispatch_intent(*args)

        # ---- non-essential: after the main UI is already on screen ----
        Clock.schedule_once(self._maybe_show_samsung_prompt, 2.5)

    # ---- Samsung "Never sleeping apps" guidance (one-time / infrequent) ----
    def _samsung_state_path(self):
        return os.path.join(self.user_data_dir, "samsung_prompt.json")

    def _read_samsung_state(self):
        try:
            with open(self._samsung_state_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, OSError, ValueError):
            return {}

    def _write_samsung_state(self, state_name):
        try:
            with open(self._samsung_state_path(), "w", encoding="utf-8") as f:
                json.dump({"state": state_name,
                           "ts": datetime.datetime.now().timestamp()}, f)
        except (IOError, OSError) as exc:
            print("[RedAlarm] could not save samsung prompt state:", exc)

    def _maybe_show_samsung_prompt(self, dt=None):
        if not ANDROID or not self._ready:
            return
        try:
            if not android_is_samsung():
                return
        except Exception:
            return
        state = self._read_samsung_state()
        if state.get("state") == "opened":
            return        # they already went to Settings: never nag again
        if state.get("state") == "later":
            age = datetime.datetime.now().timestamp() - float(state.get("ts", 0))
            if age < 7 * 86400:
                return    # "Maybe later" => ask again at most once a week
        if self.root.current == "ring":
            return        # never interrupt a ringing alarm

        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(18))
        body = Label(
            text=(
                "Samsung's Device Care can put apps to sleep in the "
                "background, which can delay or silence alarms.\n\n"
                "Add RedAlarm to [b]Never sleeping apps[/b]:\n"
                "1. Tap + / Add apps\n"
                "2. Choose RedAlarm\n"
                "3. Confirm\n\n"
                "If you can't find it on that screen, that's usually fine - "
                "Samsung often protects alarm apps automatically.\n\n"
                "This only helps stop background killing. RedAlarm's alarms "
                "are scheduled with Android's own alarm system, which this "
                "setting doesn't replace."
            ),
            markup=True, color=(0.9, 0.9, 0.9, 1), font_size="13.5sp",
            halign="left", valign="top",
        )
        body.bind(size=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        content.add_widget(body)

        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(12))
        later_btn = Button(text="Maybe later", background_normal="", background_down="",
                           background_color=(0.11, 0.09, 0.09, 1), color=(0.75, 0.72, 0.72, 1))
        open_btn = Button(text="Open Samsung settings", background_normal="",
                          background_down="", background_color=(0.82, 0.10, 0.13, 1),
                          color=(1, 1, 1, 1), bold=True)
        buttons.add_widget(later_btn)
        buttons.add_widget(open_btn)
        content.add_widget(buttons)

        popup = Popup(title="Keep alarms reliable on Samsung", content=content,
                      size_hint=(0.92, 0.78), auto_dismiss=False,
                      background_color=(0.05, 0.05, 0.055, 1),
                      title_color=(0.96, 0.96, 0.96, 1))

        def _later(*_):
            self._write_samsung_state("later")
            popup.dismiss()

        def _open(*_):
            self._write_samsung_state("opened")
            popup.dismiss()
            try:
                which = android_open_samsung_battery_settings()
                print("[RedAlarm] samsung settings opened ->", which)
            except Exception as exc:
                print("[RedAlarm] could not open any settings screen:", exc)

        later_btn.bind(on_release=_later)
        open_btn.bind(on_release=_open)
        popup.open()

    def on_resume(self):
        # Fires when Android brings this activity back to the foreground —
        # including when AlarmManager relaunches it while the app was only
        # backgrounded (not killed), which is the single most common real
        # case: phone locked overnight, app never force-closed.
        if not self._ready:
            return
        self._check_incoming_alarm()
        if self.root.current == "list":
            # Catches coming straight back from the exact-alarm / battery
            # Settings screens, which isn't a Kivy screen change so
            # on_pre_enter alone wouldn't notice the permission changed.
            self.root.get_screen("list")._refresh_permission_banners()

    _last_fire_token = None

    def _check_incoming_alarm(self):
        if not ANDROID:
            return
        try:
            alarm_id, fire_token, action_kind = android_read_incoming_alarm()
        except Exception as exc:
            print("[RedAlarm] could not read incoming intent:", exc)
            return
        self._dispatch_intent(alarm_id, fire_token, action_kind)

    def _on_new_intent(self, intent):
        # Called directly by p4a/Android with the FRESH intent — this is
        # what actually fixes the warm-background case, since it doesn't
        # depend on getIntent() at all. onNewIntent arrives on Android's
        # UI thread; hop onto Kivy's Clock to touch widgets/screens safely.
        try:
            alarm_id = intent.getStringExtra("alarm_id")
            fire_token = intent.getStringExtra("fire_token")
            action_kind = intent.getStringExtra("action_kind")
        except Exception as exc:
            print("[RedAlarm] on_new_intent read error:", exc)
            return
        Clock.schedule_once(
            lambda dt: self._dispatch_intent(alarm_id, fire_token, action_kind), 0
        )

    def _dispatch_intent(self, alarm_id, fire_token, action_kind):
        """Single funnel for every way PythonActivity can be (re)launched:
        a genuine alarm fire, a plain notification-body tap, or a
        Dismiss/Snooze notification action tap. fire_token dedupes so the
        same event never fires twice (getIntent() polling and the
        on_new_intent hook can both see the same intent)."""
        if not alarm_id or not fire_token or fire_token == self._last_fire_token:
            return
        if not self._ready:
            # arrived while the splash is still up — replayed once the UI exists
            self._queued_intents.append((alarm_id, fire_token, action_kind))
            return
        self._last_fire_token = fire_token

        ring = self.root.get_screen("ring")
        if action_kind == "dismiss":
            print("[RedAlarm] notification Dismiss tapped:", alarm_id)
            if ring.alarm_id == alarm_id:
                ring.dismiss_pressed()
            return
        if action_kind == "snooze":
            print("[RedAlarm] notification Snooze tapped:", alarm_id)
            if ring.alarm_id == alarm_id:
                ring.snooze_pressed()
            return

        # A genuine fire, or a plain tap on the notification body while
        # already ringing — the OS brings the activity to front either
        # way, so a plain tap on an alarm already ringing needs no action
        # from us (and must NOT restart the sound/countdown from zero).
        if ring.alarm_id == alarm_id and ring._ringing:
            return
        self.handle_alarm_fired(alarm_id)

    def handle_alarm_fired(self, alarm_id):
        alarm = self.store.get(alarm_id)
        if not alarm or not alarm.get("enabled", True):
            return

        # Repeating alarms: queue the next occurrence right away. Looking
        # 30s ahead guarantees a slightly-early timer can't re-queue the
        # occurrence that is firing right now.
        if any(alarm.get("days") or []):
            self.scheduler.schedule(
                alarm,
                now=datetime.datetime.now() + datetime.timedelta(seconds=30),
            )

        ring = self.root.get_screen("ring")
        ring.start_ringing(alarm)
        self.root.current = "ring"

    def on_stop(self):
        if self._ready:
            self.root.get_screen("ring")._stop_common()


if __name__ == "__main__":
    RedAlarmApp().run()
