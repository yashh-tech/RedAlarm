"""
Android bridge for alarm scheduling and background management.
Provides Python interface to Android AlarmManager and foreground service.
"""

import os
from kivy.utils import platform

ANDROID = platform == "android"

if ANDROID:
    from jnius import autoclass, cast
    from android.permissions import request_permissions, Permission

    # Import our custom Android classes
    AndroidAlarmBridge = autoclass('org.kivy.android.AndroidAlarmBridge')
    AlarmService = autoclass('org.kivy.android.AlarmService')
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Intent = autoclass('android.content.Intent')
    Context = autoclass('android.content.Context')


def init_android_alarm_bridge():
    """
    Initialize the Android alarm bridge on app startup.
    This must be called early so AlarmManager is ready.
    """
    if not ANDROID:
        return

    try:
        activity = PythonActivity.mActivity
        if activity is not None:
            AndroidAlarmBridge.init(activity)
            print("[RedAlarm] Android alarm bridge initialized")
    except Exception as e:
        print("[RedAlarm] Failed to initialize Android alarm bridge: {}".format(e))


def start_foreground_service():
    """
    Start the foreground service to keep the app alive in the background.
    """
    if not ANDROID:
        return

    try:
        activity = PythonActivity.mActivity
        if activity is not None:
            intent = Intent(activity, AlarmService)
            activity.startService(intent)
            print("[RedAlarm] Foreground service started")
    except Exception as e:
        print("[RedAlarm] Failed to start foreground service: {}".format(e))


def schedule_android_alarm(alarm_id, hour, minute):
    """
    Schedule an OS-level alarm that will fire even if the app is backgrounded.
    
    Args:
        alarm_id: Unique identifier for this alarm
        hour: Hour in 24-hour format (0-23)
        minute: Minute (0-59)
    """
    if not ANDROID:
        return

    try:
        AndroidAlarmBridge.scheduleAlarm(alarm_id, hour, minute)
        print("[RedAlarm] Scheduled Android alarm: {} at {:02d}:{:02d}".format(alarm_id, hour, minute))
    except Exception as e:
        print("[RedAlarm] Failed to schedule Android alarm: {}".format(e))


def cancel_android_alarm(alarm_id):
    """
    Cancel an OS-level alarm.
    
    Args:
        alarm_id: Unique identifier for the alarm to cancel
    """
    if not ANDROID:
        return

    try:
        AndroidAlarmBridge.cancelAlarm(alarm_id)
        print("[RedAlarm] Cancelled Android alarm: {}".format(alarm_id))
    except Exception as e:
        print("[RedAlarm] Failed to cancel Android alarm: {}".format(e))


def request_alarm_permissions():
    """
    Request necessary permissions for background alarms on Android 12+.
    """
    if not ANDROID:
        return

    try:
        request_permissions([
            Permission.SCHEDULE_EXACT_ALARM,
            Permission.POST_NOTIFICATIONS,
        ])
        print("[RedAlarm] Requested alarm permissions")
    except Exception as e:
        print("[RedAlarm] Failed to request permissions: {}".format(e))
