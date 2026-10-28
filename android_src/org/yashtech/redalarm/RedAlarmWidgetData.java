package org.yashtech.redalarm;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.widget.RemoteViews;

import java.text.SimpleDateFormat;
import java.util.Date;
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

    private static boolean hasAlarm(Context context, boolean second) {
        SharedPreferences prefs = context.getSharedPreferences("redalarm_widget", Context.MODE_PRIVATE);
        return prefs.getBoolean(second ? "has_second_alarm" : "has_next_alarm", false);
    }

    static String alarmTimeText(Context context, boolean second) {
        if (!hasAlarm(context, second)) return second ? "No other alarm" : "No alarm set";
        SharedPreferences prefs = context.getSharedPreferences("redalarm_widget", Context.MODE_PRIVATE);
        long target = prefs.getLong(second ? "second_alarm_at" : "next_alarm_at", 0L);
        if (target <= 0L) return second ? "No other alarm" : "No alarm set";
        return new SimpleDateFormat("h:mm a", Locale.getDefault()).format(new Date(target));
    }

    static String alarmLabelText(Context context, boolean second) {
        if (!hasAlarm(context, second)) return "";
        SharedPreferences prefs = context.getSharedPreferences("redalarm_widget", Context.MODE_PRIVATE);
        String label = prefs.getString(second ? "second_alarm_label" : "next_alarm_label", "Alarm");
        return label == null || label.trim().isEmpty() ? "Alarm" : label.trim();
    }
}

