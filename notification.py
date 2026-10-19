"""Shared ongoing alarm notification builder used by the app and ring service."""
RING_CHANNEL_ID = "redalarm_ringing_v2"


def build_ringing_notification(
    context, title, text, tap_pending_intent, dismiss_pending_intent,
    snooze_pending_intent, logo_path="", channel_id=RING_CHANNEL_ID,
    small_icon=None,
):
    """Build a public, ongoing alarm notification with full-screen/action intents.

    Context and PendingIntents are supplied by the caller because the app and
    python-for-android service each create those in their own Android process.
    """
    from jnius import autoclass

    Notification = autoclass("android.app.Notification")
    NotificationManager = autoclass("android.app.NotificationManager")
    AndroidR_drawable = autoclass("android.R$drawable")
    BuildVersion = autoclass("android.os.Build$VERSION")
    JString = autoclass("java.lang.String")
    NotificationChannel = None
    if BuildVersion.SDK_INT >= 26:
        NotificationChannel = autoclass("android.app.NotificationChannel")

    if small_icon is None:
        small_icon = AndroidR_drawable.ic_lock_idle_alarm

    if BuildVersion.SDK_INT >= 26:
        manager = context.getSystemService(JString("notification"))
        channel = NotificationChannel(
            JString(channel_id), JString("Alarm ringing"),
            NotificationManager.IMPORTANCE_HIGH,
        )
        channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC)
        channel.enableVibration(False)
        try:
            channel.setSound(None, None)  # Audio is played by MediaPlayer.
        except Exception:
            pass
        manager.createNotificationChannel(channel)
        builder = autoclass("android.app.Notification$Builder")(
            context, JString(channel_id)
        )
    else:
        builder = autoclass("android.app.Notification$Builder")(context)
        builder.setPriority(2)  # PRIORITY_MAX

    builder.setContentTitle(JString(str(title or "Alarm")))
    builder.setContentText(JString(str(text or "")))
    builder.setSmallIcon(small_icon)
    builder.setCategory(Notification.CATEGORY_ALARM)
    builder.setVisibility(Notification.VISIBILITY_PUBLIC)
    builder.setContentIntent(tap_pending_intent)
    builder.setFullScreenIntent(tap_pending_intent, True)
    builder.addAction(
        AndroidR_drawable.ic_menu_close_clear_cancel,
        JString("Dismiss"), dismiss_pending_intent,
    )
    builder.addAction(
        AndroidR_drawable.ic_popup_reminder,
        JString("Snooze"), snooze_pending_intent,
    )
    builder.setOngoing(True)
    builder.setAutoCancel(False)
    builder.setOnlyAlertOnce(True)

    try:
        logo_path = str(logo_path or "")
        if logo_path:
            BitmapFactory = autoclass("android.graphics.BitmapFactory")
            Options = autoclass("android.graphics.BitmapFactory$Options")
            options = Options()
            options.inSampleSize = 8
            logo = BitmapFactory.decodeFile(JString(logo_path), options)
            if logo is not None:
                builder.setLargeIcon(logo)
    except Exception as exc:
        print("[RedAlarm notification] logo load error:", exc)

    notification = builder.build()
    notification.flags = (
        int(notification.flags)
        | int(Notification.FLAG_NO_CLEAR)
        | int(Notification.FLAG_ONGOING_EVENT)
    )
    return notification
