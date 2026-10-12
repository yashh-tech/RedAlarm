"""Android foreground service for RedAlarm's ringtone and ongoing notification.

This is launched only when an alarm starts, not as an always-running process.
The service's notification ID is 1 because `ring` is the first service declared
in buildozer.spec; keep that declaration first if more services are added later.
"""
import hashlib
import json
import os
import time
import traceback

from jnius import autoclass

SERVICE_NOTIFICATION_ID = 1
SERVICE_CHANNEL_ID = "redalarm_service_ringing_v1"


def _stable_request_code(alarm_id, salt=""):
    digest = hashlib.md5((alarm_id + salt).encode("utf-8")).hexdigest()
    return int(digest[:7], 16) % 1_000_000


def _write_state(path, alarm_id, reason):
    if not path:
        return
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as output:
            json.dump({"alarm_id": alarm_id, "reason": reason}, output)
        os.replace(temporary, path)
    except Exception:
        pass


def _make_pending_intent(context, alarm_id, kind=None):
    Intent = autoclass("android.content.Intent")
    PendingIntent = autoclass("android.app.PendingIntent")
    JString = autoclass("java.lang.String")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")

    intent = Intent(context, PythonActivity)
    if kind is None:
        intent.setAction("com.redalarm.FIRE_" + alarm_id)
        salt = "ring_tap"
        nonce = "tap" + str(int(time.time() * 1000))
    else:
        intent.setAction("com.redalarm.{}_{}".format(kind.upper(), alarm_id))
        intent.putExtra("action_kind", JString(kind))
        salt = "notif_" + kind
        nonce = kind + str(int(time.time() * 1000))
    intent.setFlags(
        Intent.FLAG_ACTIVITY_NEW_TASK
        | Intent.FLAG_ACTIVITY_CLEAR_TOP
        | Intent.FLAG_ACTIVITY_SINGLE_TOP
    )
    intent.putExtra("alarm_id", JString(alarm_id))
    intent.putExtra("fire_token", JString(nonce))
    flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
    return PendingIntent.getActivity(
        context, _stable_request_code(alarm_id, salt), intent, flags
    )


def _make_alarm_notification(service, config):
    Notification = autoclass("android.app.Notification")
    NotificationManager = autoclass("android.app.NotificationManager")
    NotificationChannel = autoclass("android.app.NotificationChannel")
    AndroidR_drawable = autoclass("android.R$drawable")
    BuildVersion = autoclass("android.os.Build$VERSION")
    JString = autoclass("java.lang.String")

    context = service.getApplicationContext()
    manager = service.getSystemService(JString("notification"))
    if BuildVersion.SDK_INT >= 26:
        channel = NotificationChannel(
            JString(SERVICE_CHANNEL_ID), JString("Alarm ringing"),
            NotificationManager.IMPORTANCE_HIGH,
        )
        channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC)
        channel.enableVibration(False)  # alarm vibration is handled by RedAlarm
        try:
            channel.setSound(None, None)  # the looping alarm audio is played by MediaPlayer
        except Exception:
            pass
        manager.createNotificationChannel(channel)
        builder = autoclass("android.app.Notification$Builder")(
            context, JString(SERVICE_CHANNEL_ID)
        )
    else:
        builder = autoclass("android.app.Notification$Builder")(context)
        builder.setPriority(2)  # PRIORITY_MAX

    alarm_id = str(config.get("alarm_id") or "")
    title = str(config.get("title") or "Alarm")
    time_text = str(config.get("time_text") or "")
    content_intent = _make_pending_intent(context, alarm_id)
    dismiss_intent = _make_pending_intent(context, alarm_id, "dismiss")
    snooze_intent = _make_pending_intent(context, alarm_id, "snooze")

    builder.setContentTitle(JString(title))
    builder.setContentText(JString(time_text))
    builder.setSmallIcon(AndroidR_drawable.ic_lock_idle_alarm)
    builder.setCategory(Notification.CATEGORY_ALARM)
    builder.setVisibility(Notification.VISIBILITY_PUBLIC)
    builder.setContentIntent(content_intent)
    builder.setFullScreenIntent(content_intent, True)
    builder.addAction(
        AndroidR_drawable.ic_menu_close_clear_cancel, JString("Dismiss"), dismiss_intent
    )
    builder.addAction(
        AndroidR_drawable.ic_popup_reminder, JString("Snooze"), snooze_intent
    )
    builder.setOngoing(True)
    builder.setAutoCancel(False)
    builder.setOnlyAlertOnce(True)

    # Use the full-color RedAlarm logo as the notification's large icon.
    try:
        logo_path = str(config.get("logo_path") or "")
        if not logo_path or not os.path.isfile(logo_path):
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            logo_path = os.path.join(app_root, "splashimage.png")
        if os.path.isfile(logo_path):
            BitmapFactory = autoclass("android.graphics.BitmapFactory")
            Options = autoclass("android.graphics.BitmapFactory$Options")
            options = Options()
            options.inSampleSize = 8
            logo = BitmapFactory.decodeFile(JString(logo_path), options)
            if logo is not None:
                builder.setLargeIcon(logo)
    except Exception:
        pass

    notification = builder.build()
    notification.flags = (
        int(notification.flags)
        | int(Notification.FLAG_NO_CLEAR)
        | int(Notification.FLAG_ONGOING_EVENT)
    )
    return notification


def _new_player(context, path):
    MediaPlayer = autoclass("android.media.MediaPlayer")
    AudioAttributes = autoclass("android.media.AudioAttributes")
    PowerManager = autoclass("android.os.PowerManager")
    JString = autoclass("java.lang.String")

    player = MediaPlayer()
    try:
        attributes = (
            AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        )
        player.setAudioAttributes(attributes)
        player.setWakeMode(context, PowerManager.PARTIAL_WAKE_LOCK)
        player.setDataSource(JString(path))
        player.setLooping(True)
        player.prepare()
        player.start()
        return player
    except Exception:
        try:
            player.release()
        except Exception:
            pass
        raise


def main():
    from os import environ

    PythonService = autoclass("org.kivy.android.PythonService")
    service = PythonService.mService
    if service is None:
        return

    raw_argument = environ.get("PYTHON_SERVICE_ARGUMENT", "")
    try:
        config = json.loads(raw_argument) if raw_argument else {}
    except Exception:
        config = {}

    # START_STICKY can recreate this process with an empty intent. Recover
    # the saved request from the app-private files directory.
    if not config:
        try:
            files_dir = str(service.getFilesDir().getAbsolutePath())
            saved_config = os.path.join(files_dir, "ring_service_state.json.config")
            with open(saved_config, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
        except Exception:
            config = {}
    if not config:
        try:
            service.stopForeground(True)
            service.stopSelf()
        except Exception:
            pass
        return

    alarm_id = str(config.get("alarm_id") or "")
    state_path = str(config.get("state_path") or "")
    config_path = str(config.get("config_path") or (state_path + ".config" if state_path else ""))
    duration = max(1, int(config.get("duration_sec") or 300))
    deadline_epoch = float(config.get("deadline_epoch") or (time.time() + duration))
    player = None
    timed_out = False

    try:
        notification = _make_alarm_notification(service, config)
        # `ring` is the only p4a service, so generated ServiceRing.getServiceId() is 1.
        service.startForeground(SERVICE_NOTIFICATION_ID, notification)

        context = service.getApplicationContext()
        candidates = [str(config.get("sound_path") or ""), str(config.get("fallback_path") or "")]
        last_error = None
        for path in candidates:
            if path and os.path.isfile(path):
                try:
                    player = _new_player(context, path)
                    print("[RedAlarm service] playing alarm audio:", path)
                    break
                except Exception as exc:
                    last_error = exc
                    print("[RedAlarm service] playback path failed:", path, exc)
        if player is None:
            raise RuntimeError("No ringtone could be played: {}".format(last_error))

        # Preserve the original timeout if Android restarts the sticky service.
        while time.time() < deadline_epoch:
            time.sleep(0.25)
        timed_out = True
        _write_state(state_path, alarm_id, "auto")
        try:
            Context = autoclass("android.content.Context")
            vibrator = service.getSystemService(Context.VIBRATOR_SERVICE)
            if vibrator is not None:
                vibrator.cancel()
        except Exception:
            pass
    except Exception as exc:
        error_path = os.path.join(os.path.dirname(state_path), "ring_service_error.txt") if state_path else ""
        if error_path:
            try:
                with open(error_path, "a", encoding="utf-8") as output:
                    output.write("{}: {}\n{}\n".format(time.ctime(), exc, traceback.format_exc()))
            except Exception:
                pass
        print("[RedAlarm service] fatal error:", exc)
        _write_state(state_path, alarm_id, "error")
    finally:
        if player is not None:
            try:
                if player.isPlaying():
                    player.stop()
            except Exception:
                pass
            try:
                player.release()
            except Exception:
                pass
        if config_path and os.path.isfile(config_path):
            try:
                os.remove(config_path)
            except Exception:
                pass
        try:
            service.stopForeground(True)
        except Exception:
            pass
        try:
            service.stopSelf()
        except Exception:
            pass


main()
