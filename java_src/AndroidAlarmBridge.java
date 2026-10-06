package org.kivy.android;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import java.util.Calendar;

/**
 * Bridge between Python and Android AlarmManager.
 * Schedules OS-level alarms so they fire even if the app is not running.
 */
public class AndroidAlarmBridge {
    private static AlarmManager alarmManager;
    private static Context appContext;

    public static void init(Context context) {
        appContext = context;
        alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
    }

    /**
     * Schedule an alarm to fire at the given hour and minute (24-hour format).
     * @param alarmId Unique ID for this alarm
     * @param hour Hour (0-23)
     * @param minute Minute (0-59)
     */
    public static void scheduleAlarm(String alarmId, int hour, int minute) {
        if (alarmManager == null || appContext == null) {
            return;
        }

        Calendar calendar = Calendar.getInstance();
        calendar.set(Calendar.HOUR_OF_DAY, hour);
        calendar.set(Calendar.MINUTE, minute);
        calendar.set(Calendar.SECOND, 0);

        // If the time has already passed today, schedule for tomorrow
        if (calendar.getTimeInMillis() <= System.currentTimeMillis()) {
            calendar.add(Calendar.DAY_OF_MONTH, 1);
        }

        Intent intent = new Intent(appContext, AlarmReceiver.class);
        intent.setAction("org.yashtech.redalarm.ALARM_TRIGGER");
        intent.putExtra("alarm_id", alarmId);

        int requestCode = alarmId.hashCode();
        PendingIntent pendingIntent = PendingIntent.getBroadcast(
                appContext,
                requestCode,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        try {
            // Use setExactAndAllowWhileIdle for Android 6.0+
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, calendar.getTimeInMillis(), pendingIntent);
            } else {
                alarmManager.setExact(AlarmManager.RTC_WAKEUP, calendar.getTimeInMillis(), pendingIntent);
            }
        } catch (SecurityException e) {
            // Fall back to inexact if exact alarm permission is missing
            alarmManager.set(AlarmManager.RTC_WAKEUP, calendar.getTimeInMillis(), pendingIntent);
        }
    }

    /**
     * Cancel an alarm.
     * @param alarmId Unique ID for this alarm
     */
    public static void cancelAlarm(String alarmId) {
        if (alarmManager == null || appContext == null) {
            return;
        }

        Intent intent = new Intent(appContext, AlarmReceiver.class);
        intent.setAction("org.yashtech.redalarm.ALARM_TRIGGER");
        intent.putExtra("alarm_id", alarmId);

        int requestCode = alarmId.hashCode();
        PendingIntent pendingIntent = PendingIntent.getBroadcast(
                appContext,
                requestCode,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        alarmManager.cancel(pendingIntent);
    }
}
