package org.yashtech.redalarm;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.widget.RemoteViews;

import java.util.Locale;

/** Shared display-only helpers for the optional RedAlarm home-screen widgets. */
final class RedAlarmWidgetData {
    private RedAlarmWidgetData() { }

    static void bindLaunch(Context context, RemoteViews views, int rootId, int requestCode) {
        try {
            Intent launch = new Intent();
            launch.setClassName(context.getPackageName(), "org.kivy.android.PythonActivity");
            launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                    | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
            PendingIntent pi = PendingIntent.getActivity(context, requestCode, launch, flags);
            views.setOnClickPendingIntent(rootId, pi);
        } catch (Throwable ignored) { }
    }

    static String upcomingText(Context context) {
        SharedPreferences prefs = context.getSharedPreferences("redalarm_widget", Context.MODE_PRIVATE);
        if (!prefs.getBoolean("has_next_alarm", false)) return "No upcoming alarm";
        long target = prefs.getLong("next_alarm_at", 0L);
        if (target <= 0L) return "No upcoming alarm";
        long remaining = Math.max(0L, target - System.currentTimeMillis());
        long totalMinutes = (remaining + 59999L) / 60000L;
        long hours = totalMinutes / 60L;
        long minutes = totalMinutes % 60L;
        return String.format(Locale.getDefault(), "alarm in %d hours %d minutes", hours, minutes);
    }
}

