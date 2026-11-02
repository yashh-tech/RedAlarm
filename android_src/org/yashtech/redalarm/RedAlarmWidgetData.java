package org.yashtech.redalarm;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.text.style.RelativeSizeSpan;
import android.text.style.StyleSpan;
import android.widget.RemoteViews;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;

/** Shared display-only helpers for the RedAlarm home-screen widget. */
final class RedAlarmWidgetData {
    private static final String PREFS = "redalarm_widget";
    private static final String DAY_LETTERS = "SMTWTFS";
    private static final int DAY_ON = 0xFFE0141E;
    private static final int DAY_OFF = 0xFF6E6E73;

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

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static long target(Context context, boolean second) {
        SharedPreferences prefs = prefs(context);
        if (!prefs.getBoolean(second ? "has_second_alarm" : "has_next_alarm", false)) return 0L;
        return prefs.getLong(second ? "second_alarm_at" : "next_alarm_at", 0L);
    }

    /** "10:00 am" with a smaller am/pm suffix, or "--:--" when there is no alarm. */
    static CharSequence alarmTimeText(Context context, boolean second) {
        long at = target(context, second);
        if (at <= 0L) return "--:--";
        Date date = new Date(at);
        String time = new SimpleDateFormat("h:mm", Locale.getDefault()).format(date);
        String ampm = new SimpleDateFormat("a", Locale.getDefault()).format(date);
        SpannableStringBuilder text = new SpannableStringBuilder(time).append(' ');
        int start = text.length();
        text.append(ampm);
        text.setSpan(new RelativeSizeSpan(0.62f), start, text.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        return text;
    }

    static String alarmLabelText(Context context, boolean second) {
        if (target(context, second) <= 0L) return second ? "No other alarm" : "No alarm set";
        String label = prefs(context).getString(second ? "second_alarm_label" : "next_alarm_label", "Alarm");
        return label == null || label.trim().isEmpty() ? "Alarm" : label.trim();
    }

    /** "S M T W T F S" with the alarm's days in red. Sunday-first, one-time alarms light their ring day. */
    static CharSequence alarmDaysText(Context context, boolean second) {
        long at = target(context, second);
        String days = at > 0L ? prefs(context).getString(second ? "second_alarm_days" : "next_alarm_days", "") : "";
        if (days == null) days = "";
        if (at > 0L && days.indexOf('1') < 0) {
            Calendar cal = Calendar.getInstance();
            cal.setTimeInMillis(at);
            char[] once = "0000000".toCharArray();
            once[cal.get(Calendar.DAY_OF_WEEK) - Calendar.SUNDAY] = '1';
            days = new String(once);
        }
        SpannableStringBuilder text = new SpannableStringBuilder();
        for (int i = 0; i < DAY_LETTERS.length(); i++) {
            if (i > 0) text.append(' ');
            int start = text.length();
            text.append(DAY_LETTERS.charAt(i));
            boolean on = i < days.length() && days.charAt(i) == '1';
            text.setSpan(new ForegroundColorSpan(on ? DAY_ON : DAY_OFF), start, text.length(),
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            if (on) text.setSpan(new StyleSpan(Typeface.BOLD), start, text.length(),
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        return text;
    }

    /** "28 min", "7h 12m" or "2d 3h" until the next alarm; "--" when none is upcoming. */
    static String countdownText(Context context) {
        long at = target(context, false);
        long now = System.currentTimeMillis();
        if (at <= now) return "--";
        long minutes = (at - now + 59_999L) / 60_000L;
        if (minutes < 60L) return minutes + " min";
        long hours = minutes / 60L;
        if (hours < 24L) return hours + "h " + (minutes % 60L) + "m";
        return (hours / 24L) + "d " + (hours % 24L) + "h";
    }

    /** Per-second countdown, "3h 42m 15s" style; "--" when none is upcoming. */
    static String countdownSecondsText(Context context) {
        long at = target(context, false);
        long left = (at - System.currentTimeMillis() + 999L) / 1000L;
        if (at <= 0L || left <= 0L) return "--";
        long days = left / 86400L;
        long hours = (left % 86400L) / 3600L;
        long minutes = (left % 3600L) / 60L;
        long seconds = left % 60L;
        if (days > 0L) return days + "d " + hours + "h " + minutes + "m " + seconds + "s";
        if (hours > 0L) return hours + "h " + minutes + "m " + seconds + "s";
        if (minutes > 0L) return minutes + "m " + seconds + "s";
        return seconds + "s";
    }

    /** True while the next alarm is still in the future and worth ticking for. */
    static boolean hasUpcomingAlarm(Context context) {
        long at = target(context, false);
        return at > System.currentTimeMillis();
    }
}
