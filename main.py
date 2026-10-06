

def _start_android_alarm_service():
    """Keep the app alive while Android is actively managing alarm state.

    This does not make the app immortal; Android still owns process limits.
    It does give the app the foreground-service plumbing needed for better
    background behavior while alarms are scheduled and when the screen is off.
    """
    if not ANDROID:
        return

    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        AlarmService = autoclass("org.kivy.android.AlarmService")
        Intent = autoclass("android.content.Intent")

        activity = PythonActivity.mActivity
        if activity is None:
            return

        service_intent = Intent(activity, AlarmService)
        activity.startService(service_intent)
    except Exception as exc:
        print("[RedAlarm] foreground service start failed: {}".format(exc))


# ----------------------------------------------------------------------
# Android bridge placeholder. The native AlarmManager / WakeLock code is
# not part of this desktop build; the calls below are stubs so the app
# runs on Windows. Plug the pyjnius bridge back in here when porting.
# ----------------------------------------------------------------------
if ANDROID:
    from jnius import autoclass, cast  # noqa: F401
    from android.permissions import request_permissions, Permission  # noqa: F401


