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
import time


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
from kivy.uix.widget import Widget
from splash_screen import SplashScreen
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
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from redalarm_timepicker import AlarmEditorUI, RoundedActionButton, RoundedPanel, format_duration


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
                traceback.print_exception(
                    type(inst), inst, getattr(inst, "__traceback__", None), file=f
                )
        except Exception:
            pass
        return ExceptionManager.PASS


# ----------------------------------------------------------------------
# ANDROID BRIDGE — every native call lives here, nowhere else in the file.
#
# AlarmManager delivers to a native BroadcastReceiver, which starts the
# independent RedAlarmRingingService. Audio/wake-lock handling therefore does
# not depend on Kivy's render loop or the Activity staying alive. A boot/time
# receiver restores scheduled alarms from native preferences; PythonActivity
# is only the user-facing ringing screen and dismiss/snooze control surface.
# ----------------------------------------------------------------------
if ANDROID:
    from jnius import autoclass, cast
    from android.permissions import request_permissions, Permission
    from android.runnable import run_on_ui_thread
    from android import activity as android_activity

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Intent = autoclass("android.content.Intent")
    PendingIntent = autoclass("android.app.PendingIntent")
    Context = autoclass("android.content.Context")
    AlarmManager = autoclass("android.app.AlarmManager")
    AlarmClockInfo = autoclass("android.app.AlarmManager$AlarmClockInfo")
    PowerManager = autoclass("android.os.PowerManager")
    Build = autoclass("android.os.Build")
    BuildVersion = autoclass("android.os.Build$VERSION")
    Settings = autoclass("android.provider.Settings")
    Uri = autoclass("android.net.Uri")
    WindowManagerFlags = autoclass("android.view.WindowManager$LayoutParams")
    KeyguardManager = autoclass("android.app.KeyguardManager")
    JString = autoclass("java.lang.String")
    Toast = autoclass("android.widget.Toast")
    Gravity = autoclass("android.view.Gravity")

    def _activity():
        return PythonActivity.mActivity

    @run_on_ui_thread
    def android_show_toast(message):
        """Show the OS-managed Android toast, not an app-drawn overlay."""
        try:
            toast = Toast.makeText(
                _activity().getApplicationContext(), JString(str(message)), Toast.LENGTH_LONG
            )
            # Android 10 and older honour this. Newer Android versions may
            # choose their own position for standard text toasts.
            try:
                toast.setGravity(Gravity.CENTER, 0, 0)
            except Exception:
                pass
            toast.show()
        except Exception as exc:
            print("[RedAlarm] native Android toast failed:", exc)

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

    def android_schedule_alarm(alarm_id, trigger_dt, salt="", alarm=None, store_path=""):
        """Schedule through native BroadcastReceiver; Python/Kivy need not be awake."""
        request_code = stable_request_code(alarm_id, salt)
        fire_token = int(trigger_dt.timestamp() * 1000)
        app = App.get_running_app()
        config = dict(alarm or {})
        if app is not None:
            if not store_path:
                store_path = getattr(getattr(app, "store", None), "path", "")
            try:
                cache_dir = getattr(app, "ringtone_cache_dir", "")
                resolved = resolve_ringtone_for_playback(config.get("sound_path", ""), cache_dir)
                if resolved and os.path.isfile(resolved):
                    config["native_sound_path"] = resolved
            except Exception as exc:
                print("[RedAlarm] native ringtone path preparation failed:", exc)
            config["native_fallback_path"] = getattr(app, "default_ringtone_path", "")
        config["id"] = str(alarm_id)
        if not config:
            config = {"id": str(alarm_id), "enabled": True, "hour": trigger_dt.hour,
                      "minute": trigger_dt.minute, "days": [False] * 7}
        try:
            context = _activity().getApplicationContext()
            # Clear a pre-patch Activity PendingIntent with the same identity.
            try:
                _alarm_manager().cancel(_alarm_pending_intent(alarm_id, request_code, fire_token))
            except Exception:
                pass
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            Bridge.scheduleAlarm(
                context, JString(str(alarm_id)), JString(json.dumps(config, ensure_ascii=False)),
                JString(str(store_path or "")), int(fire_token), bool(salt == "snooze")
            )
        except Exception as exc:
            # Legacy fallback keeps compatibility if the native bridge could not be loaded.
            print("[RedAlarm] native scheduler unavailable; using legacy Activity alarm:", exc)
            pending_intent = _alarm_pending_intent(alarm_id, request_code, fire_token)
            info = AlarmClockInfo(fire_token, pending_intent)
            _alarm_manager().setAlarmClock(info, pending_intent)

    def android_cancel_alarm(alarm_id, salt=""):
        request_code = stable_request_code(alarm_id, salt)
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            Bridge.cancelAlarm(_activity().getApplicationContext(), JString(str(alarm_id)), bool(salt == "snooze"))
        except Exception as exc:
            print("[RedAlarm] native alarm cancellation failed:", exc)
        # Also cancel any legacy Activity-based PendingIntent left by an older APK.
        try:
            pending_intent = _alarm_pending_intent(alarm_id, request_code)
            _alarm_manager().cancel(pending_intent)
        except Exception:
            pass

    def android_native_ring_is_active(alarm_id):
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            return bool(Bridge.isRinging(_activity().getApplicationContext(), JString(str(alarm_id))))
        except Exception as exc:
            print("[RedAlarm] native ring status unavailable:", exc)
            return False

    def android_stop_native_ring_service(alarm_id=""):
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            Bridge.stopRinging(_activity().getApplicationContext(), JString(str(alarm_id or "")))
        except Exception as exc:
            print("[RedAlarm] native ring service stop failed:", exc)

    def android_any_native_ring_active():
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            return bool(Bridge.isAnyRinging(_activity().getApplicationContext()))
        except Exception:
            return False

    def android_native_fire_recently(alarm_id):
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            return bool(Bridge.hasRecentNativeFire(_activity().getApplicationContext(), JString(str(alarm_id))))
        except Exception:
            return False

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
        if BuildVersion.SDK_INT >= 33:
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

    @run_on_ui_thread
    def _apply_lockscreen_flags(show):
        """Only the live ringing screen may draw over the keyguard."""
        try:
            activity = _activity()
            window = activity.getWindow()
            if show:
                # Never dismiss the user's PIN/pattern. Put only the ringing
                # screen over the lock screen and wake the display for it.
                window.addFlags(WindowManagerFlags.FLAG_SHOW_WHEN_LOCKED
                                | WindowManagerFlags.FLAG_TURN_SCREEN_ON
                                | WindowManagerFlags.FLAG_KEEP_SCREEN_ON)
                if BuildVersion.SDK_INT >= 27:
                    activity.setShowWhenLocked(True)
                    activity.setTurnScreenOn(True)
                print("[RedAlarm] lockscreen: ringing screen shown")
            else:
                # Clear ALL lock-screen flags so Home/clock/editor never remain
                # above the keyguard after dismissal or snoozing.
                window.clearFlags(WindowManagerFlags.FLAG_SHOW_WHEN_LOCKED
                                  | WindowManagerFlags.FLAG_TURN_SCREEN_ON
                                  | WindowManagerFlags.FLAG_KEEP_SCREEN_ON)
                if BuildVersion.SDK_INT >= 27:
                    activity.setShowWhenLocked(False)
                    activity.setTurnScreenOn(False)
                print("[RedAlarm] lockscreen: normal activity hidden by keyguard")
        except Exception as exc:
            print("[RedAlarm] lockscreen flags error:", exc)

    def android_show_over_lockscreen(show):
        """Lockscreen visibility is exclusively owned by RedAlarmRingActivity."""
        _apply_lockscreen_flags(False)

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
    _RING_CHANNEL_ID = "redalarm_ringing_v2"
    _RING_NOTIF_ID = 1002

    def android_ensure_ring_channel():
        if BuildVersion.SDK_INT >= 26:
            NotificationManager = autoclass("android.app.NotificationManager")
            NotificationChannel = autoclass("android.app.NotificationChannel")
            Notification = autoclass("android.app.Notification")
            manager = cast("android.app.NotificationManager",
                            _activity().getSystemService(Context.NOTIFICATION_SERVICE))
            channel = NotificationChannel(JString(_RING_CHANNEL_ID), JString("Alarm ringing"),
                                          NotificationManager.IMPORTANCE_HIGH)
            channel.setBypassDnd(True)
            channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC)
            channel.enableVibration(False)   # we handle vibration ourselves
            manager.createNotificationChannel(channel)

    def _notification_action_pending_intent(alarm_id, kind):
        """Send Dismiss/Snooze directly to the native receiver, never Home/settings."""
        context = _activity().getApplicationContext()
        Receiver = autoclass("org.yashtech.redalarm.RedAlarmAlarmReceiver")
        intent = Intent(context, Receiver)
        intent.setAction(JString("org.yashtech.redalarm.RING_ACTION"))
        intent.putExtra("alarm_id", JString(str(alarm_id)))
        intent.putExtra("ring_action", JString(str(kind)))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        request_code = stable_request_code(alarm_id, "notif_" + kind)
        return PendingIntent.getBroadcast(_activity(), request_code, intent, flags)

    def android_apply_notification_logo(builder):
        """Set splashimage.png as the large branded icon inside Android notifications."""
        try:
            from kivy.resources import resource_find

            logo_path = resource_find("splashimage.png")
            if not logo_path:
                logo_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "splashimage.png"
                )
            if not logo_path or not os.path.isfile(logo_path):
                print("[RedAlarm] notification logo not found: splashimage.png")
                return

            # Downsample the square splash image to avoid decoding a huge bitmap
            # every time the alarm notification is posted.
            BitmapFactory = autoclass("android.graphics.BitmapFactory")
            Options = autoclass("android.graphics.BitmapFactory$Options")
            options = Options()
            options.inSampleSize = 8
            logo_bitmap = BitmapFactory.decodeFile(JString(logo_path), options)
            if logo_bitmap is not None:
                builder.setLargeIcon(logo_bitmap)
        except Exception as exc:
            print("[RedAlarm] notification large-icon error:", exc)

    def android_show_ring_notification(alarm_id, title, text):
        """Fallback ring notification launches only the native minimal ring screen."""
        context = _activity().getApplicationContext()
        Notification = autoclass("android.app.Notification")
        AndroidR_drawable = autoclass("android.R$drawable")
        RingActivity = autoclass("org.yashtech.redalarm.RedAlarmRingActivity")
        tap_intent = Intent(context, RingActivity)
        tap_intent.setAction(JString("org.yashtech.redalarm.OPEN_RING." + str(alarm_id)))
        tap_intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP)
        tap_intent.putExtra("alarm_id", JString(str(alarm_id)))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        tap_pending_intent = PendingIntent.getActivity(
            _activity(), stable_request_code(alarm_id, "ring_tap"), tap_intent, flags
        )
        dismiss_pi = _notification_action_pending_intent(alarm_id, "dismiss")
        snooze_pi = _notification_action_pending_intent(alarm_id, "snooze")
        if BuildVersion.SDK_INT >= 26:
            builder = autoclass("android.app.Notification$Builder")(context, JString(_RING_CHANNEL_ID))
        else:
            builder = autoclass("android.app.Notification$Builder")(context)
            builder.setPriority(2)
        builder.setContentTitle(JString(title))
        builder.setContentText(JString(text))
        builder.setSmallIcon(AndroidR_drawable.ic_lock_idle_alarm)
        android_apply_notification_logo(builder)
        builder.setCategory(Notification.CATEGORY_ALARM)
        builder.setVisibility(Notification.VISIBILITY_PUBLIC)
        builder.setFullScreenIntent(tap_pending_intent, True)
        builder.setContentIntent(tap_pending_intent)
        builder.addAction(AndroidR_drawable.ic_menu_close_clear_cancel, JString("Dismiss"), dismiss_pi)
        builder.addAction(AndroidR_drawable.ic_popup_reminder, JString("Snooze"), snooze_pi)
        builder.setOngoing(True)
        builder.setAutoCancel(False)
        manager = cast("android.app.NotificationManager", context.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.notify(_RING_NOTIF_ID, builder.build())

    def android_cancel_ring_notification():
        context = _activity().getApplicationContext()
        manager = cast("android.app.NotificationManager",
                        context.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.cancel(_RING_NOTIF_ID)


    @run_on_ui_thread
    def android_close_alarm_task():
        """Close the Android app task after a ringing action has been handled."""
        try:
            activity = _activity()
            if activity is None:
                return
            # minapi is 24; retain fallbacks for safety on unexpected runtimes.
            try:
                activity.finishAndRemoveTask()
            except Exception:
                try:
                    activity.finishAffinity()
                except Exception:
                    activity.finish()
        except Exception as exc:
            print("[RedAlarm] could not close alarm task:", exc)

    # Separate from the temporary ring/snooze notification (ID 1002). This
    # ongoing notification remains posted while a future alarm is scheduled.
    _NEXT_ALARM_CHANNEL_ID = "redalarm_next_alarm_v1"
    _NEXT_ALARM_NOTIF_ID = 1001

    def android_ensure_next_alarm_channel():
        if BuildVersion.SDK_INT < 26:
            return
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        Notification = autoclass("android.app.Notification")
        context = _activity().getApplicationContext()
        manager = cast("android.app.NotificationManager",
                       context.getSystemService(Context.NOTIFICATION_SERVICE))
        channel = NotificationChannel(
            JString(_NEXT_ALARM_CHANNEL_ID), JString("Next scheduled alarm"),
            NotificationManager.IMPORTANCE_LOW,
        )
        channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC)
        channel.enableVibration(False)
        try:
            channel.setSound(None, None)
        except Exception:
            pass
        manager.createNotificationChannel(channel)

    def android_show_next_alarm_notification(alarm_id, trigger_dt, label):
        """Post/update a persistent lock-screen-visible countdown preview."""
        try:
            context = _activity().getApplicationContext()
            Notification = autoclass("android.app.Notification")
            AndroidR_drawable = autoclass("android.R$drawable")
            seconds_left = max(0.0, (trigger_dt - datetime.datetime.now()).total_seconds())
            total_minutes = int(math.ceil(seconds_left / 60.0))
            hours, minutes = divmod(total_minutes, 60)
            eta_text = "Your next alarm in {} hr {} min".format(hours, minutes)
            alarm_time = trigger_dt.strftime("%I:%M %p").lstrip("0")
            alarm_label = (str(label or "Alarm").strip() or "Alarm")

            open_intent = Intent(context, PythonActivity)
            open_intent.setAction("com.redalarm.OPEN_NEXT_ALARM")
            open_intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                 | Intent.FLAG_ACTIVITY_CLEAR_TOP
                                 | Intent.FLAG_ACTIVITY_SINGLE_TOP)
            pending_flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
            open_pi = PendingIntent.getActivity(
                _activity(), stable_request_code("redalarm-next-alarm", "open"),
                open_intent, pending_flags,
            )

            if BuildVersion.SDK_INT >= 26:
                builder = autoclass("android.app.Notification$Builder")(
                    context, JString(_NEXT_ALARM_CHANNEL_ID)
                )
            else:
                builder = autoclass("android.app.Notification$Builder")(context)
                builder.setPriority(1)  # PRIORITY_LOW

            builder.setContentTitle(JString("RedAlarm • Next alarm"))
            builder.setContentText(JString(eta_text))
            builder.setSubText(JString("{} • {}".format(alarm_label, alarm_time)))
            builder.setSmallIcon(AndroidR_drawable.ic_lock_idle_alarm)
            builder.setContentIntent(open_pi)
            builder.setCategory(Notification.CATEGORY_ALARM)
            builder.setVisibility(Notification.VISIBILITY_PUBLIC)
            builder.setWhen(int(trigger_dt.timestamp() * 1000))
            builder.setShowWhen(True)
            # Android keeps the displayed countdown moving while the Python
            # process is backgrounded or temporarily reclaimed.
            builder.setUsesChronometer(True)
            if BuildVersion.SDK_INT >= 24:
                builder.setChronometerCountDown(True)
            builder.setOngoing(True)
            builder.setAutoCancel(False)
            builder.setOnlyAlertOnce(True)
            try:
                style = autoclass("android.app.Notification$BigTextStyle")()
                style.bigText(JString("{}\n{} • {}".format(eta_text, alarm_label, alarm_time)))
                builder.setStyle(style)
            except Exception:
                pass

            notification = builder.build()
            notification.flags = (
                int(notification.flags)
                | int(Notification.FLAG_NO_CLEAR)
                | int(Notification.FLAG_ONGOING_EVENT)
            )
            manager = cast("android.app.NotificationManager",
                           context.getSystemService(Context.NOTIFICATION_SERVICE))
            manager.notify(_NEXT_ALARM_NOTIF_ID, notification)
        except Exception as exc:
            # In particular, Android 13+ may reject this until the user grants
            # POST_NOTIFICATIONS. The next refresh retries after permission is granted.
            print("[RedAlarm] next-alarm notification error:", exc)

    def android_cancel_next_alarm_notification():
        try:
            context = _activity().getApplicationContext()
            manager = cast("android.app.NotificationManager",
                           context.getSystemService(Context.NOTIFICATION_SERVICE))
            manager.cancel(_NEXT_ALARM_NOTIF_ID)
        except Exception as exc:
            print("[RedAlarm] next-alarm notification cancel error:", exc)

    def android_show_snoozed_notification(alarm_id, next_trigger):
        """Keep a visible notification showing when the snoozed alarm will ring."""
        context = _activity().getApplicationContext()
        Notification = autoclass("android.app.Notification")
        AndroidR_drawable = autoclass("android.R$drawable")

        if BuildVersion.SDK_INT >= 26:
            builder = autoclass("android.app.Notification$Builder")(
                context, JString(_RING_CHANNEL_ID)
            )
        else:
            builder = autoclass("android.app.Notification$Builder")(context)
            builder.setPriority(2)  # Notification.PRIORITY_MAX

        next_text = next_trigger.strftime("%I:%M %p").lstrip("0")
        builder.setContentTitle(JString("RedAlarm snoozed"))
        builder.setContentText(JString("Next ring at " + next_text))
        builder.setSmallIcon(AndroidR_drawable.ic_lock_idle_alarm)
        android_apply_notification_logo(builder)
        builder.setCategory(Notification.CATEGORY_ALARM)
        builder.setVisibility(Notification.VISIBILITY_PUBLIC)
        builder.setOngoing(True)
        builder.setAutoCancel(False)

        manager = cast("android.app.NotificationManager",
                       context.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.notify(_RING_NOTIF_ID, builder.build())

    def android_get_mime_type(uri_string):
        try:
            mime = _activity().getContentResolver().getType(Uri.parse(uri_string))
            return str(mime) if mime else None
        except Exception:
            return None

    def android_notifications_ok():
        manager = cast("android.app.NotificationManager",
                        _activity().getSystemService(Context.NOTIFICATION_SERVICE))
        return bool(manager.areNotificationsEnabled())

    _notif_request_count = [0]

    def android_request_notification_permission():
        """First tap shows the Android 13+ system dialog; if it was already
        denied the dialog won't show again, so later taps open the app's
        notification settings page instead."""
        _notif_request_count[0] += 1
        if BuildVersion.SDK_INT >= 33 and _notif_request_count[0] == 1:
            request_permissions([Permission.POST_NOTIFICATIONS])
            return
        intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        intent.putExtra(Settings.EXTRA_APP_PACKAGE, JString(_activity().getPackageName()))
        _activity().startActivity(intent)

    class _AndroidPlayer(object):
        """Plays an alarm sound with Android's own MediaPlayer on the ALARM
        audio stream, exposing the same stop()/unload() the ring screen uses
        for Kivy sounds. Used instead of Kivy's SoundLoader on Android because
        SoundLoader chooses a decoder from the file EXTENSION and silently
        returns None for anything it doesn't recognise (that was the "local
        song just sits there / Silent" bug), and because it ignores the alarm
        volume stream."""

        def __init__(self, path, loop=True, volume=1.0):
            MediaPlayer = autoclass("android.media.MediaPlayer")
            AudioAttributes = autoclass("android.media.AudioAttributes")
            AudioAttributesBuilder = autoclass("android.media.AudioAttributes$Builder")
            self._mp = MediaPlayer()
            self._volume = max(0.0, min(1.0, float(volume)))
            try:
                attrs = (AudioAttributesBuilder()
                         .setUsage(AudioAttributes.USAGE_ALARM)
                         .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                         .build())
                self._mp.setAudioAttributes(attrs)
                self._mp.setDataSource(JString(path))
                self._mp.setLooping(bool(loop))
                self._mp.prepare()
                self._mp.setVolume(self._volume, self._volume)
                self._mp.start()
            except Exception:
                self.unload()
                raise

        def stop(self):
            try:
                if self._mp is not None and self._mp.isPlaying():
                    self._mp.stop()
            except Exception:
                pass

        def unload(self):
            mp, self._mp = self._mp, None
            if mp is not None:
                try:
                    mp.release()
                except Exception:
                    pass

    # ---- vibration -------------------------------------------------------
    _vibrator = [None]

    def android_vibrate_start():
        vibrator = cast("android.os.Vibrator",
                         _activity().getSystemService(Context.VIBRATOR_SERVICE))
        if vibrator is None or not vibrator.hasVibrator():
            return
        pattern = [0, 800, 500]   # wait, buzz, pause — repeats from index 1
        if BuildVersion.SDK_INT >= 26:
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
        if BuildVersion.SDK_INT < 34:
            return True
        manager = cast("android.app.NotificationManager",
                        _activity().getSystemService(Context.NOTIFICATION_SERVICE))
        return bool(manager.canUseFullScreenIntent())

    def android_request_full_screen_intent_permission():
        if BuildVersion.SDK_INT < 34:
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
            app = App.get_running_app()
            store_path = getattr(getattr(app, "store", None), "path", "")
            android_schedule_alarm(alarm["id"], trigger_dt, salt="", alarm=alarm, store_path=store_path)
        return trigger_dt

    def cancel(self, alarm):
        self._pending.pop(alarm["id"], None)
        if ANDROID:
            android_cancel_alarm(alarm["id"], salt="")

    def schedule_snooze(self, alarm, trigger_dt):
        self._pending[alarm["id"] + "snooze"] = (alarm["id"], trigger_dt)
        if ANDROID:
            app = App.get_running_app()
            store_path = getattr(getattr(app, "store", None), "path", "")
            android_schedule_alarm(alarm["id"], trigger_dt, salt="snooze", alarm=alarm, store_path=store_path)

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


_AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus", ".amr", ".mid")
_MIME_TO_EXT = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
    "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/ogg": ".ogg",
    "application/ogg": ".ogg", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
    "audio/aac": ".aac", "audio/flac": ".flac", "audio/x-flac": ".flac",
    "audio/opus": ".opus", "audio/amr": ".amr", "audio/midi": ".mid",
}


def guess_audio_ext(display_name=None, mime=None):
    """File extension for a picked song: from its name, else its MIME type,
    else .mp3. (The old cache file was named '<hash>.audio', an extension no
    decoder recognises - the root cause of "selected but won't play".)"""
    if display_name:
        ext = os.path.splitext(str(display_name))[1].lower()
        if ext in _AUDIO_EXTS:
            return ext
    if mime and str(mime).lower() in _MIME_TO_EXT:
        return _MIME_TO_EXT[str(mime).lower()]
    return ".mp3"


def resolve_ringtone_for_playback(raw_path, app_storage_dir, display_name=None):
    """Desktop paths are used as-is. An Android content:// URI is copied
    into app storage once (with its REAL extension), then the cached copy is
    reused on every later ring."""
    if raw_path and raw_path.startswith("content://"):
        if not ANDROID:
            return None
        os.makedirs(app_storage_dir, exist_ok=True)
        if display_name is None:
            try:
                display_name = android_get_display_name(raw_path)
            except Exception:
                display_name = None
        ext = guess_audio_ext(display_name, android_get_mime_type(raw_path))
        dest = os.path.join(
            app_storage_dir,
            hashlib.md5(raw_path.encode("utf-8")).hexdigest() + ext,
        )
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            try:
                android_copy_content_uri_to_file(raw_path, dest)
            except Exception as exc:
                print("[RedAlarm] couldn't copy ringtone URI:", exc)
                return None
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            print("[RedAlarm] copied ringtone is empty:", dest)
            return None
        return dest
    return raw_path


def load_and_play(path, loop=True, volume=1.0):
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
    return None

# ======================================================================
# 3. CUSTOM WIDGETS (auto-registered with Kivy's Factory, so alarm.kv can
#    use them by class name)
# ======================================================================

def _seconds_to_next_wall_second():
    """Delay until the next wall-clock second boundary (recomputed each tick)."""
    now = datetime.datetime.now()
    return max(0.001, (1000000 - now.microsecond) / 1000000.0)


class AnalogClock(Widget):
    """Canvas-drawn analog clock. Fills whatever box it is given and draws
    a centred circle, so it never gets squashed into an ellipse."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_second = None
        self._numerals = {}
        self.bind(pos=self._force_redraw, size=self._force_redraw)
        self._tick_event = Clock.schedule_once(
            self._tick, _seconds_to_next_wall_second()
        )
        self._redraw()

    def _force_redraw(self, *_):
        self._last_second = None
        self._redraw()

    def _tick(self, dt):
        # Re-align after each tick instead of accumulating interval drift.
        self._tick_event = None
        self._redraw()
        self._tick_event = Clock.schedule_once(
            self._tick, _seconds_to_next_wall_second()
        )

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
    row = ObjectProperty(None)
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
        row = self.row
        if row is not None:
            row.release_child_touch()
            if row._long_press_triggered:
                row._long_press_triggered = False
                return
            if row.list_screen is not None and row.list_screen.selection_mode:
                return
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


class AlarmSelectionIndicator(ButtonBehavior, Widget):
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
            self.row.release_child_touch()
            self.row.on_row_press()


# ======================================================================
# 4. SCREENS
# ======================================================================

class HomeScreen(Screen):
    date_text = StringProperty("")
    next_alarm_text = StringProperty("")
    _next_alarm_event = None

    def on_pre_enter(self, *args):
        self._refresh_clock_displays()
        if self._next_alarm_event is None:
            self._next_alarm_event = Clock.schedule_once(
                self._wall_clock_tick, _seconds_to_next_wall_second()
            )

    def _refresh_clock_displays(self):
        self.date_text = datetime.datetime.now().strftime("%A, %d %B")
        self._refresh_next_alarm()

    def _wall_clock_tick(self, _dt):
        self._next_alarm_event = None
        if self.manager is None or self.manager.current != self.name:
            return
        self._refresh_clock_displays()
        # Recompute from wall time on each tick to prevent accumulated drift.
        self._next_alarm_event = Clock.schedule_once(
            self._wall_clock_tick, _seconds_to_next_wall_second()
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

        def _open():
            app.root.get_screen("edit").load_alarm(None)
            app.root.current = "edit"
        app.ask_permissions_then(_open)


class AlarmRow(BoxLayout):
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

class AlarmListScreen(Screen):
    _delete_popup = None
    selection_mode = BooleanProperty(False)
    selected_alarm_ids = ListProperty([])
    selected_count = NumericProperty(0)
    all_selected = BooleanProperty(False)
    exact_alarm_ok = BooleanProperty(True)
    battery_ok = BooleanProperty(True)
    overlay_ok = BooleanProperty(True)
    fsi_ok = BooleanProperty(True)

    def _sync_selection_visuals(self):
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

    def on_pre_enter(self, *args):
        self.refresh()
        self._refresh_permission_banners()

    def go_home(self):
        if self.selection_mode:
            self.cancel_selection()
            return
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
        valid_ids = {str(item.get("id", "")) for item in alarms}
        self.selected_alarm_ids = [item_id for item_id in self.selected_alarm_ids if item_id in valid_ids]
        if not self.selected_alarm_ids:
            self.selection_mode = False
        self.selected_count = len(self.selected_alarm_ids)
        self.all_selected = bool(alarms) and self.selected_count == len(alarms)
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
            row.sub_text = label if label else days_str
            row.enabled = bool(alarm.get("enabled", True))
            row.selection_mode = self.selection_mode
            row.selected = row.alarm_id in self.selected_alarm_ids
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

        def _open():
            app.root.get_screen("edit").load_alarm(None)
            app.root.current = "edit"
        app.ask_permissions_then(_open)

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
        app.refresh_next_alarm_notification()

    def confirm_delete(self, alarm_id):
        """Show a styled, explicit delete confirmation for the chosen alarm."""
        app = App.get_running_app()
        alarm = app.store.get(alarm_id)
        if not alarm:
            return

        # Avoid stacking duplicate delete dialogs on repeated taps.
        active = getattr(self, "_delete_popup", None)
        if active is not None and getattr(active, "is_open", False):
            return

        label_text = (alarm.get("label") or "Alarm").strip() or "Alarm"
        time_text = format_time(alarm["hour"], alarm["minute"])
        repeat_text = format_days(alarm.get("days"))

        content = RoundedPanel(
            fill=(0.045, 0.045, 0.052, 1), radius=dp(22),
            orientation="vertical", padding=(dp(18), dp(14), dp(18), dp(14)),
            spacing=dp(8),
        )
        title = Label(
            text="DELETE THIS ALARM?", color=(1, 0.42, 0.45, 1),
            font_size="15sp", bold=True, size_hint_y=None, height=dp(26),
            halign="center", valign="middle",
        )
        title.bind(size=lambda w, v: setattr(w, "text_size", v))
        content.add_widget(title)

        details = Label(
            text="{}\n{}  ·  {}".format(time_text, label_text, repeat_text),
            color=(0.96, 0.96, 0.98, 1), font_size="13sp", bold=True,
            size_hint_y=None, height=dp(48), halign="center", valign="middle",
        )
        details.bind(size=lambda w, v: setattr(w, "text_size", v))
        content.add_widget(details)

        warning = Label(
            text="This removes the alarm and cancels its schedule.",
            color=(0.64, 0.64, 0.68, 1), font_size="11sp",
            size_hint_y=None, height=dp(30), halign="center", valign="middle",
        )
        warning.bind(size=lambda w, v: setattr(w, "text_size", v))
        content.add_widget(warning)

        buttons = BoxLayout(
            orientation="horizontal", spacing=dp(10),
            size_hint_y=None, height=dp(44),
        )

        popup = Popup(
            title="", content=content, size_hint=(0.88, None), height=dp(238),
            separator_height=0, background_color=(0.025, 0.025, 0.03, 1),
            auto_dismiss=True,
        )

        def do_delete(*_):
            current_alarm = app.store.get(alarm_id)
            if current_alarm:
                app.scheduler.cancel(current_alarm)
                app.scheduler.cancel_snooze(current_alarm)
            ring = app.root.get_screen("ring")
            if ring.alarm_id == alarm_id:
                ring.finish(reason="delete")
            app.store.delete(alarm_id)
            app.refresh_next_alarm_notification()
            popup.dismiss()
            self.refresh()

        keep_button = RoundedActionButton(
            "KEEP ALARM", callback=lambda: popup.dismiss(), accent=False,
            size_hint_x=1,
        )
        delete_button = RoundedActionButton(
            "DELETE", callback=do_delete, accent=True, size_hint_x=1,
        )
        buttons.add_widget(keep_button)
        buttons.add_widget(delete_button)
        content.add_widget(buttons)

        self._delete_popup = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_delete_popup", None))
        popup.open()


class PermissionsPopup(Popup):
    """Shown when you tap Add / Set New Alarm and something Android needs for
    a reliable LOCK-SCREEN alarm is still missing. One row per permission with
    an Allow button; rows turn to "Done" as you grant them (refresh() is called
    again when you come back from Settings). Continue always works - nothing
    is forced. `items` are dicts: title, sub, check() -> bool, action()."""

    RED = (0.82, 0.10, 0.13, 1)
    CARD = (0.11, 0.09, 0.09, 1)
    SUB = (0.62, 0.58, 0.58, 1)

    def __init__(self, items, on_continue, on_dismissed=None, **kwargs):
        self._items = items
        self._on_continue = on_continue
        self._on_dismissed = on_dismissed
        self._rows = []
        row_h = dp(74)
        width = min(Window.width * 0.92, dp(460))
        height = min(Window.height * 0.96, dp(236) + row_h * len(items))
        super().__init__(
            title="", separator_height=0, auto_dismiss=False,
            background_color=(0.03, 0.03, 0.035, 1),
            size_hint=(None, None), size=(width, height), **kwargs
        )
        self.content = self._build(row_h)
        self.refresh()

    def _wrap_label(self, **kw):
        lbl = Label(halign="left", valign="middle", **kw)
        lbl.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        return lbl

    def _build(self, row_h):
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(8))
        title = self._wrap_label(
            text="[b]Allow these so alarms ring on the lock screen[/b]", markup=True,
            font_size="15sp", color=(0.96, 0.96, 0.96, 1),
            size_hint_y=None, height=dp(44))
        root.add_widget(title)

        scroll = ScrollView(do_scroll_x=False, bar_width=0)
        grid = GridLayout(cols=1, spacing=dp(6), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for item in self._items:
            row = BoxLayout(size_hint_y=None, height=row_h, spacing=dp(8))
            text_col = BoxLayout(orientation="vertical")
            t = self._wrap_label(text=item["title"], font_size="14sp", bold=True,
                                 color=(0.96, 0.96, 0.96, 1))
            sub = self._wrap_label(text=item.get("sub", ""), font_size="11sp", color=self.SUB)
            text_col.add_widget(t)
            text_col.add_widget(sub)
            btn = Button(text="Allow", size_hint_x=None, width=dp(78),
                         background_normal="", background_down="", bold=True)
            btn.bind(on_release=lambda inst, it=item: self._press(it))
            row.add_widget(text_col)
            row.add_widget(btn)
            grid.add_widget(row)
            self._rows.append((item, btn))
        scroll.add_widget(grid)
        root.add_widget(scroll)

        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(12))
        cancel_btn = Button(text="Cancel", background_normal="", background_down="",
                            background_color=self.CARD, color=(0.75, 0.72, 0.72, 1))
        cont_btn = Button(text="Continue", background_normal="", background_down="",
                          background_color=self.RED, color=(1, 1, 1, 1), bold=True)
        cancel_btn.bind(on_release=lambda *_: self._finish(False))
        cont_btn.bind(on_release=lambda *_: self._finish(True))
        buttons.add_widget(cancel_btn)
        buttons.add_widget(cont_btn)
        root.add_widget(buttons)
        return root

    def _press(self, item):
        try:
            item["action"]()
        except Exception as exc:
            print("[RedAlarm] permission action failed:", item.get("title"), exc)
        self.refresh()

    def refresh(self):
        for item, btn in self._rows:
            try:
                ok = bool(item["check"]())
            except Exception:
                ok = False
            btn.text = "Done" if ok else "Allow"
            btn.disabled = ok
            btn.background_color = self.CARD if ok else self.RED
            btn.color = (0.55, 0.52, 0.52, 1) if ok else (1, 1, 1, 1)

    def _finish(self, proceed):
        self.dismiss()
        if self._on_dismissed:
            self._on_dismissed(proceed)
        if proceed and self._on_continue:
            self._on_continue()


class AlarmEditScreen(Screen):
    """Two-page alarm editor; existing persistence/scheduler APIs stay in main.py."""
    editing_id = StringProperty("")
    ampm = StringProperty("AM")
    days_selected = ListProperty([False] * 7)
    sound_path = StringProperty("")
    sound_name = StringProperty("Default beep")
    vibrate = BooleanProperty(False)
    volume = NumericProperty(0.80)
    auto_dismiss_sec = NumericProperty(5)
    snooze_sec = NumericProperty(60)
    error_message = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.time_state = {"hour": 7, "minute": 16, "ampm": "AM", "label": ""}
        self._return_screen = "home"
        # PATCH2_NAV_UI_FIX_V1: an alarm is only a candidate until confirmation DONE.
        self._pending_confirmation_alarm = None
        self._pending_confirmation_previous = None
        self.ui = AlarmEditorUI(self, size_hint=(1, 1), pos=self.pos)
        self.add_widget(self.ui)
        self.label_input = self.ui.picker_page.label_input
        self.error_label = self.ui.settings_page.error_label

    def on_enter(self, *args):
        # The time wheel and all alarm settings now live on one page.
        self.ui.show_settings()

    def handle_hardware_back(self):
        """Close the top modal first, then navigate one editor step backward."""
        # The root keyboard handler also checks these, but keep this method safe
        # when called directly by an editor-level callback.
        confirmation = getattr(self, "_confirmation_popup", None)
        if confirmation is not None and getattr(confirmation, "is_open", False):
            self.cancel_confirmation(confirmation)
            return True
            

        sound_popup = getattr(self, "_sound_picker_popup", None)
        if sound_popup is not None and getattr(sound_popup, "is_open", False):
            sound_popup.dismiss()
            return True

        time_editor = getattr(self, "_time_edit_popup", None)
        time_popup = getattr(time_editor, "popup", None)
        if time_popup is not None and getattr(time_popup, "is_open", False):
            time_popup.dismiss()
            return True

        # There is one editor page now: close the keyboard first, otherwise
        # discard this unsaved edit and return to the screen that opened it.
        if getattr(self.label_input, "focus", False):
            self.label_input.focus = False
            return True

        self.cancel_edit()
        return True

    def load_alarm(self, alarm_id):
        """Load defaults or an existing record and reset the editor to page 1."""
        app = App.get_running_app()
        current_screen = getattr(app.root, "current", "home") if app.root else "home"
        self._return_screen = current_screen if current_screen in ("home", "list") else "home"
        self.error_message = ""
        self.error_label.text = ""
        self.ui.current = "settings"

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
            self.auto_dismiss_sec = 5
            self.snooze_sec = 60
        else:
            alarm = App.get_running_app().store.get(alarm_id)
            if not alarm:
                return
            self.editing_id = alarm_id
            hour24 = int(alarm.get("hour", 7)) % 24
            stored_label = str(alarm.get("label") or "").strip()
            if stored_label.lower() == "alarm":
                stored_label = ""
            self.time_state.update({
                "hour": hour24 % 12 or 12,
                "minute": int(alarm.get("minute", 0)) % 60,
                "ampm": "PM" if hour24 >= 12 else "AM",
                "label": stored_label,
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
            self.auto_dismiss_sec = max(1, min(10800, int(alarm.get("auto_dismiss_sec", 5) or 5)))
            self.snooze_sec = max(3, min(10800, int(alarm.get("snooze_sec", 60) or 60)))

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


    def choose_builtin_sound(self):
        """Select and preview the app's existing default beep."""
        self.sound_path = ""
        self.sound_name = "Default beep"
        self.error_message = ""
        self.error_label.text = ""
        self.ui.settings_page.refresh_sound()
        self.preview_sound()

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
        app.refresh_next_alarm_notification()
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

    def _commit_pending_confirmation(self):
        """Persist and schedule the candidate alarm only after DONE is tapped."""
        pending = self._pending_confirmation_alarm
        if pending is None:
            return None

        app = App.get_running_app()
        alarm_id = pending["id"]
        previous = self._pending_confirmation_previous

        try:
            if previous:
                app.scheduler.cancel(previous)
                app.scheduler.cancel_snooze(previous)
            app.store.put(pending)
            actual_trigger_dt = app.scheduler.schedule(pending)
        except Exception:
            # Restore the original alarm if a reschedule fails. A new candidate
            # is removed completely so a failed DONE never leaves a ghost alarm.
            try:
                app.scheduler.cancel(pending)
                app.scheduler.cancel_snooze(pending)
            except Exception:
                pass
            if previous:
                app.store.put(previous)
                if previous.get("enabled", True):
                    app.scheduler.schedule(previous)
            else:
                app.store.delete(alarm_id)
            app.refresh_next_alarm_notification()
            raise

        self._pending_confirmation_alarm = None
        self._pending_confirmation_previous = None
        app.refresh_next_alarm_notification()
        print("[RedAlarm] alarm confirmed and scheduled:", alarm_id)
        return actual_trigger_dt


    def cancel_confirmation(self, popup=None):
        """Cancel review without saving; keep entered editor fields intact."""
        active = getattr(self, "_confirmation_popup", None)

        if active is None:
            return False

        if popup is not None and popup is not active:
            return False

        if getattr(active, "is_open", False):
            active.dismiss(animation=False)
        else:
            # Clean up safely if dismissal has already started.
            self._on_confirmation_dismiss(active)

        app = App.get_running_app()
        if app.root is not None and app.root.current != "edit":
            app.root.current = "edit"

        self.ui.show_settings()
        return True

    def _on_confirmation_dismiss(self, popup, *_):
        """Discard only this popup's candidate, never a newer confirmation."""
        if getattr(self, "_confirmation_popup", None) is not popup:
            return
        self._confirmation_popup = None
        self._pending_confirmation_alarm = None
        self._pending_confirmation_previous = None

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
            ("Auto-dismiss", format_duration(alarm.get("auto_dismiss_sec", 5))),
            ("Snooze", format_duration(alarm.get("snooze_sec", 60))),
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

        popup = Popup(title="", content=content, size_hint=(0.88, None), height=dp(510),
                      background="atlas://data/images/defaulttheme/modalview-background",
                      background_color=(0, 0, 0, 0), separator_height=0, auto_dismiss=True)
        self._confirmation_popup = popup
        popup.bind(on_dismiss=self._on_confirmation_dismiss)

        def finish(_button=None):
            try:
                actual_trigger_dt = self._commit_pending_confirmation()
            except Exception as exc:
                print("[RedAlarm] confirmation commit failed:", exc)
                title.text = "COULDN'T SAVE — PLEASE TRY AGAIN"
                title.color = (1, 0.35, 0.38, 1)
                return

            if actual_trigger_dt is None:
                return

            popup.dismiss()
            self._confirmation_popup = None
            # Completed alarm setup returns to the main clock/Home screen.
            app.root.current = "home"
            remaining_seconds = max(
                0.0,
                (actual_trigger_dt - datetime.datetime.now()).total_seconds(),
            )
            total_minutes = int(math.ceil(remaining_seconds / 60.0))
            hours, minutes = divmod(total_minutes, 60)
            message = "Alarm Set for {} {} and {} {} from now".format(
                hours, "hour" if hours == 1 else "hours",
                minutes, "minute" if minutes == 1 else "minutes",
            )
            if ANDROID:
                Clock.schedule_once(lambda _dt: android_show_toast(message), 0.12)

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
        if not 1 <= dismiss_seconds <= 10800:
            return self._fail("Auto-dismiss must be between 1 second and 3 Hr.")
        if not 3 <= snooze_seconds <= 10800:
            return self._fail("Snooze must be between 3 seconds and 3 Hr.")

        app = App.get_running_app()
        is_new_alarm = not bool(self.editing_id)
        existing_alarm = app.store.get(self.editing_id)
        self._pending_confirmation_previous = dict(existing_alarm) if existing_alarm else None
        # Work on a copy: editing must not mutate the live, previously saved alarm.
        label_text = str(self.label_input.text or self.time_state.get("label") or "").strip()
        if len(label_text.split()) > 25:
            return self._fail("Alarm label can contain up to 25 words.")

        alarm = dict(existing_alarm or {})
        sound_path = self.sound_path or app.default_ringtone_path
        sound_name = self.sound_name if self.sound_path else "Default beep"
        alarm.update({
            "id": self.editing_id or new_alarm_id(),
            "hour": hour24,
            "minute": minute,
            "days": list(self.days_selected),
            "label": label_text or "Alarm",
            "sound_path": sound_path,
            "sound_name": sound_name,
            "volume": volume,
            "auto_dismiss_sec": dismiss_seconds,
            "snooze_sec": snooze_seconds,
            "vibrate": bool(self.vibrate),
            "enabled": True,
        })
        # Keep the candidate in memory only. The DONE button is the commit point.
        self._pending_confirmation_alarm = alarm
        trigger_dt = compute_next_trigger_dt(alarm)
        print("[RedAlarm] alarm waiting for confirmation:", alarm.get("id"),
              "new:", is_new_alarm)
        # Keep the confirmation on the editor settings page, not over Home.
        self.ui.current = "settings"
        app.root.current = "edit"
        self._show_alarm_confirmation(alarm, trigger_dt)


class AlarmRingScreen(Screen):
    alarm_id = StringProperty("")
    time_text = StringProperty("")
    label_text = StringProperty("")
    countdown_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sound = None
        self._sound_stop_event = None
        self._countdown_event = None
        self._remaining_seconds = 0
        self._ringing = False
        self._ring_session = 0
        self._keep_snooze_notification = False

    def on_leave(self, *args):
        # Safety net: whichever way we leave this screen, sound + timer stop.
        self._stop_common(
            cancel_notification=not self._keep_snooze_notification
        )

    def start_ringing(self, alarm):
        self._stop_common()                  # kill any previous ring first
        self._keep_snooze_notification = False
        self._ring_session += 1
        session = self._ring_session
        self._ringing = True

        self.alarm_id = alarm["id"]
        self.time_text = format_time(alarm["hour"], alarm["minute"])
        self.label_text = alarm.get("label") or "Alarm"

        native_playback = False
        if ANDROID:
            try:
                native_playback = android_native_ring_is_active(alarm["id"])
            except Exception:
                native_playback = False
            try:
                android_acquire_wake_lock()
                android_show_over_lockscreen(True)
            except Exception as exc:
                print("[RedAlarm] wake/lockscreen error:", exc)
            # The native service already posts its own full-screen notification.
            # Do not replace it with a second Activity-owned notification.
            if not native_playback:
                try:
                    android_show_ring_notification(alarm["id"], self.label_text, self.time_text)
                except Exception as exc:
                    print("[RedAlarm] full-screen notification error:", exc)
            if alarm.get("vibrate", False) and not native_playback:
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

        try:
            ring_volume = max(0.0, min(1.0, float(alarm.get("volume", 0.80))))
        except (TypeError, ValueError):
            ring_volume = 0.80
        # On Android the exact-alarm receiver starts a native media-playback
        # foreground service before it asks the Activity to draw this screen.
        # That service keeps audio alive if Kivy's clock pauses on the lock screen.
        if ANDROID and native_playback:
            sound = None
            print("[RedAlarm] ring: native foreground service owns playback")
        else:
            sound = load_and_play(path, loop=True, volume=ring_volume) if path else None
            if sound is None and path != app.default_ringtone_path:
                print("[RedAlarm] ring: chosen sound failed, falling back to default beep")
                sound = load_and_play(app.default_ringtone_path, loop=True, volume=ring_volume)
        self._sound = sound
        if sound is None and not (ANDROID and native_playback):
            print("[RedAlarm] ring: NO sound could be started (not even the default)")

        configured_dismiss_seconds = max(
            1, int(alarm.get("auto_dismiss_sec", 5) or 5)
        )
        # Stop audio at the selected duration; the UI grace below must not extend it.
        if self._sound is not None:
            self._sound_stop_event = Clock.schedule_once(
                lambda _dt, ring_session=session: self._stop_ring_sound(ring_session),
                float(configured_dismiss_seconds),
            )
        # Extremely short settings need a startup/visibility grace so Android has
        # time to display the ringing UI before the activity closes.
        dismiss_grace_seconds = 1 if configured_dismiss_seconds <= 3 else 0
        self._remaining_seconds = configured_dismiss_seconds + dismiss_grace_seconds
        self._update_countdown_text()

        # ONE timer drives both the digits and the auto-dismiss: the tick
        # that reaches zero is the tick that ends the alarm, so the display
        # and the real cutoff can never disagree.
        self._countdown_event = Clock.schedule_interval(
            lambda dt: self._tick_countdown(dt, session), 1
        )

    def _stop_ring_sound(self, session=None):
        """Stop and release only the ringtone; keep the ring UI/countdown alive."""
        if session is not None and (not self._ringing or session != self._ring_session):
            return False
        self._sound_stop_event = None
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
        return False

    def _try_load_and_play(self, path):
        """Kept for compatibility: plays `path` in a loop, or returns None."""
        return load_and_play(path, loop=True)

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

    def _stop_common(self, cancel_notification=True):
        self._ringing = False
        self._ring_session += 1              # invalidates any queued tick

        event, self._countdown_event = self._countdown_event, None
        if event is not None:
            event.cancel()

        sound_stop_event, self._sound_stop_event = self._sound_stop_event, None
        if sound_stop_event is not None:
            try:
                sound_stop_event.cancel()
            except Exception:
                pass
        self._stop_ring_sound()

        if ANDROID:
            # Stop only the native service owned by this RingScreen. On a new
            # alarm launch, an older screen's cleanup must not kill the fresh
            # service or remove its notification/vibration.
            try:
                if self.alarm_id:
                    android_stop_native_ring_service(self.alarm_id)
            except Exception as exc:
                print("[RedAlarm] native ringing service stop error:", exc)
            native_still_ringing = android_any_native_ring_active()
            if not native_still_ringing:
                try:
                    android_show_over_lockscreen(False)
                    android_release_wake_lock()
                except Exception as exc:
                    print("[RedAlarm] wake/lockscreen release error:", exc)
                try:
                    android_vibrate_stop()
                except Exception as exc:
                    print("[RedAlarm] vibration stop error:", exc)
                if cancel_notification:
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
        # Stop sound first. Snooze replaces the ringing card with a snoozed card.
        current_alarm_id = self.alarm_id
        keep_snooze_notification = reason == "snooze"
        self._keep_snooze_notification = keep_snooze_notification
        self._stop_common(cancel_notification=not keep_snooze_notification)

        app = App.get_running_app()
        alarm = app.store.get(current_alarm_id)
        snooze_trigger = None
        if alarm:
            if reason == "snooze":
                snooze_sec = max(1, int(alarm.get("snooze_sec", 60) or 60))
                snooze_trigger = datetime.datetime.now() + datetime.timedelta(
                    seconds=snooze_sec
                )
                app.scheduler.schedule_snooze(alarm, snooze_trigger)
            elif reason != "delete":
                app.scheduler.cancel_snooze(alarm)
                # One-time alarms switch themselves off after ringing.
                # Repeating ones stay on (next occurrence already queued).
                if not any(alarm.get("days") or []):
                    alarm["enabled"] = False
                    app.store.put(alarm)
                    app.scheduler.cancel(alarm)

        self.alarm_id = ""
        self.countdown_text = ""
        close_task = ANDROID and reason in ("auto", "dismiss", "snooze")
        if not close_task:
            app.root.current = "home"

        app.refresh_next_alarm_notification()
        if keep_snooze_notification and snooze_trigger and ANDROID:
            try:
                android_show_snoozed_notification(current_alarm_id, snooze_trigger)
            except Exception as exc:
                print("[RedAlarm] snoozed notification error:", exc)

        if close_task:
            # Let the OS alarm and snooze notification be posted before removing the task.
            Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.20)


class RootManager(ScreenManager):
    pass


# ======================================================================
# 5. APP
# ======================================================================

class RedAlarmApp(App):
    _ready = False            # True once the real UI + store + scheduler exist
    _queued_intents = None    # intents that arrive before _ready (replayed after)

    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        """Handle Android Back in modal-first, previous-page order."""
        if key != 27:
            return False
        if not self._ready or not getattr(self, "root", None):
            return False

        root = self.root
        edit_screen = root.get_screen("edit")
        list_screen = root.get_screen("list")

        # Modal dialogs take priority even if the root screen behind one changed.
        time_editor = getattr(edit_screen, "_time_edit_popup", None)
        time_popup = getattr(time_editor, "popup", None)
        if time_popup is not None and getattr(time_popup, "is_open", False):
            time_popup.dismiss()
            return True

        sound_popup = getattr(edit_screen, "_sound_picker_popup", None)
        if sound_popup is not None and getattr(sound_popup, "is_open", False):
            sound_popup.dismiss()
            return True

        confirmation = getattr(edit_screen, "_confirmation_popup", None)
        if confirmation is not None and getattr(confirmation, "is_open", False):
            # Use the same no-save path as the on-screen CANCEL action.
            edit_screen.cancel_confirmation(confirmation)
            return True

        delete_popup = getattr(list_screen, "_delete_popup", None)
        if delete_popup is not None and getattr(delete_popup, "is_open", False):
            delete_popup.dismiss()
            list_screen._delete_popup = None
            return True

        current = root.current
        if current == "edit":
            return edit_screen.handle_hardware_back()
        if current == "list":
            list_screen.go_home()
            return True
        if current == "ring":
            # Never let Back close the app while an alarm is actively ringing.
            return True
        return False

    def _on_request_close(self, *args, **kwargs):
        """Route Android Back/close through the same modal-first handler."""
        if not ANDROID:
            return False
        return bool(self._on_keyboard(Window, 27, 0, "", []))

    def build(self):
        self.title = APP_TITLE
        self._queued_intents = []
        self._startup_started = time.monotonic()
        Window.bind(on_keyboard=self._on_keyboard)
        Window.bind(on_request_close=self._on_request_close)

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
        
    def _build_splash(self):
        return SplashScreen(duration=1.0)
    

    def _finish_startup(self, dt):
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

        self._pending_root = root
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
                android_ensure_next_alarm_channel()
            except Exception as exc:
                print("[RedAlarm] next-alarm notification channel error:", exc)
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

        if ANDROID:
            self._refresh_next_alarm_notification()
            self._next_alarm_notification_event = Clock.schedule_interval(
                self._refresh_next_alarm_notification, 60.0
            )

        self._check_incoming_alarm()
        queued, self._queued_intents = self._queued_intents, []
        for args in queued:
            self._dispatch_intent(*args)

        # Keep the splash visible for one second from app startup.
        remaining = max(
            0.0,
            1.0 - (time.monotonic() - self._startup_started)
        )
        Clock.schedule_once(self._show_main_ui, remaining)

    def _show_main_ui(self, dt):
        root = getattr(self, "_pending_root", None)
        if root is None:
            return

        Window.remove_widget(self._splash)
        Window.add_widget(root)


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

    def _open_samsung_settings(self):
        self._write_samsung_state("opened")
        which = android_open_samsung_battery_settings()
        print("[RedAlarm] samsung settings opened ->", which)

    def _samsung_item_ok(self):
        state = self._read_samsung_state()
        if state.get("state") == "opened":
            return True
        if state.get("state") == "later":
            age = datetime.datetime.now().timestamp() - float(state.get("ts", 0))
            return age < 7 * 86400    # asked recently - don't nag every time
        return False

    def _permission_items(self):
        """Everything a lock-screen alarm needs, in the order it matters.
        Empty on desktop. Each check() is a live query, so the popup can tick
        rows off after you come back from Settings."""
        if not ANDROID:
            return []
        items = [
            dict(title="Notifications",
                 sub="Shows the alarm with Dismiss / Snooze, even when locked",
                 check=android_notifications_ok,
                 action=android_request_notification_permission),
            dict(title="Exact alarms",
                 sub="So the alarm rings at the exact minute",
                 check=android_can_schedule_exact_alarms,
                 action=android_request_exact_alarm_permission),
            dict(title="Full-screen alarm on lock screen",
                 sub="Lets the alarm screen open over the lock screen",
                 check=android_can_use_full_screen_intent,
                 action=android_request_full_screen_intent_permission),
            dict(title="Display over other apps",
                 sub="Lets the alarm open while you're using another app",
                 check=android_can_draw_overlays,
                 action=android_request_overlay_permission),
            dict(title="Battery: don't optimise RedAlarm",
                 sub="Stops Android putting the app to sleep",
                 check=android_is_ignoring_battery_optimizations,
                 action=android_request_ignore_battery_optimizations),
        ]
        try:
            if android_is_samsung():
                items.append(dict(
                    title="Samsung: Never sleeping apps",
                    sub="Add RedAlarm in Battery > Background usage limits. "
                        "Helps stop Samsung killing the app.",
                    check=self._samsung_item_ok,
                    action=self._open_samsung_settings))
        except Exception:
            pass
        return items

    _perm_popup = None

    def ask_permissions_then(self, proceed):
        """Called when you tap Add / Set New Alarm. If anything is missing,
        show ONE checklist popup first; Continue (or nothing missing) goes on
        to the editor. Never blocks the app if a check itself fails."""
        items = self._permission_items()
        pending = False
        for it in items:
            try:
                if not it["check"]():
                    pending = True
                    break
            except Exception:
                continue
        if not pending:
            proceed()
            return

        def _dismissed(went_on):
            self._perm_popup = None
            if went_on and not self._samsung_item_ok():
                self._write_samsung_state("later")   # asked once, don't nag

        popup = PermissionsPopup(items, on_continue=proceed, on_dismissed=_dismissed)
        self._perm_popup = popup
        popup.open()

    def _refresh_next_alarm_notification(self, _dt=None):
        """Keep the persistent notification aligned with the earliest pending trigger."""
        if not ANDROID or not self._ready:
            return
        try:
            now = datetime.datetime.now()
            pending = getattr(getattr(self, "scheduler", None), "_pending", {})
            candidates = []
            for pending_key, entry in list(pending.items()):
                try:
                    alarm_id, trigger_dt = entry
                    if trigger_dt <= now:
                        continue
                    alarm = self.store.get(alarm_id)
                    if not alarm:
                        continue
                    is_snooze = str(pending_key).endswith("snooze")
                    if not is_snooze and not bool(alarm.get("enabled", True)):
                        continue
                    label = (str(alarm.get("label") or "Alarm").strip() or "Alarm")
                    candidates.append((trigger_dt, alarm_id, label))
                except Exception as exc:
                    print("[RedAlarm] skipping invalid pending notification trigger:", exc)
            if not candidates:
                android_cancel_next_alarm_notification()
                return
            trigger_dt, alarm_id, label = min(candidates, key=lambda item: item[0])
            android_show_next_alarm_notification(alarm_id, trigger_dt, label)
        except Exception as exc:
            print("[RedAlarm] next-alarm notification refresh error:", exc)

    def refresh_next_alarm_notification(self):
        """Public hook for alarm creation, toggles, edits, and dismiss/snooze."""
        self._refresh_next_alarm_notification()

    def on_resume(self):
        # Fires when Android brings this activity back to the foreground —
        # including when AlarmManager relaunches it while the app was only
        # backgrounded (not killed), which is the single most common real
        # case: phone locked overnight, app never force-closed.
        if not self._ready:
            return
        self._check_incoming_alarm()
        self._refresh_next_alarm_notification()
        if self._perm_popup is not None:
            self._perm_popup.refresh()
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
            if ring.alarm_id == alarm_id and ring._ringing:
                ring.dismiss_pressed()
            else:
                if ANDROID:
                    android_stop_native_ring_service(alarm_id)
                # Handle notification actions even if Android recreated the process.
                alarm = self.store.get(alarm_id)
                if alarm:
                    self.scheduler.cancel_snooze(alarm)
                    if not any(alarm.get("days") or []):
                        alarm["enabled"] = False
                        self.store.put(alarm)
                        self.scheduler.cancel(alarm)
                if ANDROID:
                    android_cancel_ring_notification()
                    Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.20)
            return
        if action_kind == "snooze":
            print("[RedAlarm] notification Snooze tapped:", alarm_id)
            if ring.alarm_id == alarm_id and ring._ringing:
                ring.snooze_pressed()
            else:
                # A cold-start action has no active RingScreen to operate on.
                alarm = self.store.get(alarm_id)
                if alarm:
                    snooze_sec = max(1, int(alarm.get("snooze_sec", 60) or 60))
                    next_trigger = datetime.datetime.now() + datetime.timedelta(
                        seconds=snooze_sec
                    )
                    self.scheduler.schedule_snooze(alarm, next_trigger)
                    ring._keep_snooze_notification = True
                    if ANDROID:
                        android_stop_native_ring_service(alarm_id)
                        android_show_snoozed_notification(alarm_id, next_trigger)
                        Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.20)
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
        native_ring_active = False
        if ANDROID and alarm:
            try:
                native_ring_active = android_native_ring_is_active(alarm_id)
            except Exception:
                native_ring_active = False
        if not alarm:
            return
        if ANDROID and not native_ring_active:
            try:
                if android_native_fire_recently(alarm_id):
                    # The native service already rang and auto-dismissed while
                    # Kivy was asleep. Do not replay late on unlock. Reconcile
                    # the in-memory store with native one-shot completion.
                    if any(alarm.get("days") or []) and alarm.get("enabled", True):
                        self.scheduler.schedule(
                            alarm, now=datetime.datetime.now() + datetime.timedelta(seconds=30)
                        )
                    else:
                        if not any(alarm.get("days") or []):
                            alarm["enabled"] = False
                            self.store.put(alarm)
                        self.scheduler.cancel(alarm)
                        self.scheduler.cancel_snooze(alarm)
                    self._refresh_next_alarm_notification()
                    return
            except Exception as exc:
                print("[RedAlarm] could not reconcile delayed native alarm:", exc)
        if not alarm.get("enabled", True) and not native_ring_active:
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
        self._refresh_next_alarm_notification()

    def on_stop(self):
        if not self._ready:
            return
        if ANDROID:
            # Android may call this when the Activity is backgrounded/locked or
            # the UI process is reclaimed. Native AlarmManager + foreground
            # ringing service own delivery and playback; never cancel them here.
            return
        ring = self.root.get_screen("ring")
        ring._stop_common(cancel_notification=not ring._keep_snooze_notification)


if __name__ == "__main__":
    RedAlarmApp().run()
