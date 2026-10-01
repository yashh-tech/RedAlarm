package org.yashtech.redalarm;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import java.util.Calendar;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

import org.kivy.android.PythonActivity;

public class KivyAlarmReceiver extends BroadcastReceiver {

    public static final String ACTION_FIRE =
            "org.yashtech.redalarm.ACTION_FIRE";

    private static final String EXTRA_ALARM_ID = "alarm_id";

    private static final String PREFS_NAME =
            "redalarm_android_scheduler";

    private static final String KEY_IDS =
            "scheduled_ids";

    private static final String CHANNEL_ID =
            "redalarm_alarm_channel_v2";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || intent.getAction() == null) {
            return;
        }

        String action = intent.getAction();

        if (ACTION_FIRE.equals(action)) {
            String alarmId = intent.getStringExtra(EXTRA_ALARM_ID);

            if (alarmId != null && !alarmId.isEmpty()) {
                handleAlarmFire(context, alarmId);
            }

            return;
        }

        if (Intent.ACTION_BOOT_COMPLETED.equals(action)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                || Intent.ACTION_TIME_CHANGED.equals(action)
                || Intent.ACTION_TIMEZONE_CHANGED.equals(action)
                || AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED
                .equals(action)) {

            restoreAllAlarms(context);
        }
    }

    // ------------------------------------------------------------
    // EXACT ALARM ACCESS
    // ------------------------------------------------------------

    public static boolean canScheduleExactAlarms(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return true;
        }

        AlarmManager alarmManager =
                (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);

        return alarmManager != null
                && alarmManager.canScheduleExactAlarms();
    }

    public static void requestExactAlarmAccess(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            return;
        }

        try {
            Intent intent = new Intent(
                    Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM
            );

            intent.setData(
                    Uri.parse("package:" + context.getPackageName())
            );

            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(intent);

        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    // ------------------------------------------------------------
    // FULL-SCREEN INTENT ACCESS
    // ------------------------------------------------------------

    public static boolean canUseFullScreenIntent(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return true;
        }

        NotificationManager manager =
                (NotificationManager) context.getSystemService(
                        Context.NOTIFICATION_SERVICE
                );

        return manager != null && manager.canUseFullScreenIntent();
    }

    public static void requestFullScreenIntentAccess(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return;
        }

        try {
            Intent intent = new Intent(
                    "android.settings.MANAGE_APP_USE_FULL_SCREEN_INTENT"
            );

            intent.setData(
                    Uri.parse("package:" + context.getPackageName())
            );

            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(intent);

        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    // ------------------------------------------------------------
    // SCHEDULE
    // ------------------------------------------------------------

    public static void scheduleAlarm(
            Context context,
            long triggerAtMillis,
            String alarmId,
            boolean snooze,
            String label,
            int hour,
            int minute,
            int repeatMask) {

        if (alarmId == null || alarmId.isEmpty()) {
            return;
        }

        saveRecord(
                context,
                alarmId,
                triggerAtMillis,
                snooze,
                label,
                hour,
                minute,
                repeatMask
        );

        if (!canScheduleExactAlarms(context)) {
            requestExactAlarmAccess(context);
            return;
        }

        scheduleInternal(
                context,
                alarmId,
                triggerAtMillis,
                snooze,
                label
        );
    }

    private static void scheduleInternal(
            Context context,
            String alarmId,
            long triggerAtMillis,
            boolean snooze,
            String label) {

        AlarmManager alarmManager =
                (AlarmManager) context.getSystemService(
                        Context.ALARM_SERVICE
                );

        if (alarmManager == null) {
            return;
        }

        Intent alarmIntent =
                new Intent(context, KivyAlarmReceiver.class);

        alarmIntent.setAction(ACTION_FIRE);
        alarmIntent.putExtra(EXTRA_ALARM_ID, alarmId);
        alarmIntent.setPackage(context.getPackageName());

        int requestCode =
                stableCode(alarmId, snooze);

        PendingIntent operation =
                PendingIntent.getBroadcast(
                        context,
                        requestCode,
                        alarmIntent,
                        PendingIntent.FLAG_UPDATE_CURRENT
                                | PendingIntent.FLAG_IMMUTABLE
                );

        Intent showIntent =
                new Intent(context, PythonActivity.class);

        showIntent.setFlags(
                Intent.FLAG_ACTIVITY_SINGLE_TOP
                        | Intent.FLAG_ACTIVITY_CLEAR_TOP
        );

        PendingIntent showPendingIntent =
                PendingIntent.getActivity(
                        context,
                        requestCode + 500000,
                        showIntent,
                        PendingIntent.FLAG_UPDATE_CURRENT
                                | PendingIntent.FLAG_IMMUTABLE
                );

        AlarmManager.AlarmClockInfo info =
                new AlarmManager.AlarmClockInfo(
                        triggerAtMillis,
                        showPendingIntent
                );

        try {
            alarmManager.setAlarmClock(
                    info,
                    operation
            );
        } catch (SecurityException e) {
            e.printStackTrace();
        }
    }

    // ------------------------------------------------------------
    // CANCEL
    // ------------------------------------------------------------

    public static void cancelAlarm(
            Context context,
            String alarmId,
            boolean snooze) {

        if (alarmId == null || alarmId.isEmpty()) {
            return;
        }

        AlarmManager alarmManager =
                (AlarmManager) context.getSystemService(
                        Context.ALARM_SERVICE
                );

        if (alarmManager != null) {

            Intent intent =
                    new Intent(context, KivyAlarmReceiver.class);

            intent.setAction(ACTION_FIRE);
            intent.putExtra(EXTRA_ALARM_ID, alarmId);
            intent.setPackage(context.getPackageName());

            PendingIntent pendingIntent =
                    PendingIntent.getBroadcast(
                            context,
                            stableCode(alarmId, snooze),
                            intent,
                            PendingIntent.FLAG_UPDATE_CURRENT
                                    | PendingIntent.FLAG_IMMUTABLE
                    );

            alarmManager.cancel(pendingIntent);
            pendingIntent.cancel();
        }

        removeRecord(context, alarmId, snooze);
    }

    // ------------------------------------------------------------
    // NOTIFICATION
    // ------------------------------------------------------------

    private static void handleAlarmFire(
            Context context,
            String alarmId) {

        ScheduledRecord record =
                loadRecord(context, alarmId, false);

        ScheduledRecord snoozeRecord =
                loadRecord(context, alarmId, true);

        boolean isSnooze = false;

        if (record == null && snoozeRecord != null) {
            record = snoozeRecord;
            isSnooze = true;
        }

        if (record == null) {
            return;
        }

        if (isSnooze) {
            removeRecord(context, alarmId, true);

        } else if (record.repeatMask != 0) {

            long next =
                    computeNextRepeating(
                            System.currentTimeMillis(),
                            record.hour,
                            record.minute,
                            record.repeatMask
                    );

            scheduleInternal(
                    context,
                    alarmId,
                    next,
                    false,
                    record.label
            );

            saveRecord(
                    context,
                    alarmId,
                    next,
                    false,
                    record.label,
                    record.hour,
                    record.minute,
                    record.repeatMask
            );

        } else {
            removeRecord(context, alarmId, false);
        }

        showAlarmNotification(
                context,
                alarmId,
                record.label
        );
    }

    private static void showAlarmNotification(
            Context context,
            String alarmId,
            String label) {

        NotificationManager manager =
                (NotificationManager) context.getSystemService(
                        Context.NOTIFICATION_SERVICE
                );

        if (manager == null) {
            return;
        }

        createNotificationChannel(context);

        Intent launchIntent =
                new Intent(context, PythonActivity.class);

        launchIntent.setAction(ACTION_FIRE);
        launchIntent.putExtra(EXTRA_ALARM_ID, alarmId);

        launchIntent.setFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP
        );

        PendingIntent fullScreenIntent =
                PendingIntent.getActivity(
                        context,
                        stableCode(alarmId, false) + 1000000,
                        launchIntent,
                        PendingIntent.FLAG_UPDATE_CURRENT
                                | PendingIntent.FLAG_IMMUTABLE
                );

        Uri alarmSound =
                RingtoneManager.getDefaultUri(
                        RingtoneManager.TYPE_ALARM
                );

        Notification.Builder builder;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(
                    context,
                    CHANNEL_ID
            );
        } else {
            builder = new Notification.Builder(context);

            if (alarmSound != null) {
                builder.setSound(
                        alarmSound,
                        new AudioAttributes.Builder()
                                .setUsage(
                                        AudioAttributes.USAGE_ALARM
                                )
                                .setContentType(
                                        AudioAttributes.CONTENT_TYPE_SONIFICATION
                                )
                                .build()
                );
            }

            builder.setPriority(
                    Notification.PRIORITY_MAX
            );
        }

        builder.setSmallIcon(
                android.R.drawable.ic_lock_idle_alarm
        );

        builder.setContentTitle(
                label == null || label.isEmpty()
                        ? "Red Alarm"
                        : label
        );

        builder.setContentText(
                "Alarm is ringing"
        );

        builder.setCategory(
                Notification.CATEGORY_ALARM
        );

        builder.setVisibility(
                Notification.VISIBILITY_PUBLIC
        );

        builder.setOngoing(true);
        builder.setAutoCancel(true);

        builder.setFullScreenIntent(
                fullScreenIntent,
                true
        );

        manager.notify(
                notificationId(alarmId),
                builder.build()
        );
    }

    private static void createNotificationChannel(
            Context context) {

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationManager manager =
                (NotificationManager) context.getSystemService(
                        Context.NOTIFICATION_SERVICE
                );

        if (manager == null) {
            return;
        }

        Uri alarmSound =
                RingtoneManager.getDefaultUri(
                        RingtoneManager.TYPE_ALARM
                );

        AudioAttributes attributes =
                new AudioAttributes.Builder()
                        .setUsage(
                                AudioAttributes.USAGE_ALARM
                        )
                        .setContentType(
                                AudioAttributes.CONTENT_TYPE_SONIFICATION
                        )
                        .build();

        NotificationChannel channel =
                new NotificationChannel(
                        CHANNEL_ID,
                        "Red Alarm",
                        NotificationManager.IMPORTANCE_HIGH
                );

        if (alarmSound != null) {
            channel.setSound(
                    alarmSound,
                    attributes
            );
        }

        channel.setLockscreenVisibility(
                Notification.VISIBILITY_PUBLIC
        );

        manager.createNotificationChannel(channel);
    }

    public static void cancelAlarmNotification(
            Context context,
            String alarmId,
            boolean snooze) {

        NotificationManager manager =
                (NotificationManager) context.getSystemService(
                        Context.NOTIFICATION_SERVICE
                );

        if (manager != null && alarmId != null) {
            manager.cancel(
                    notificationId(alarmId)
            );
        }
    }

    // ------------------------------------------------------------
    // BOOT / TIME RESTORE
    // ------------------------------------------------------------

    private static void restoreAllAlarms(
            Context context) {

        if (!canScheduleExactAlarms(context)) {
            return;
        }

        android.content.SharedPreferences prefs =
                context.getSharedPreferences(
                        PREFS_NAME,
                        Context.MODE_PRIVATE
                );

        Set<String> ids =
                new HashSet<>(
                        prefs.getStringSet(
                                KEY_IDS,
                                Collections.<String>emptySet()
                        )
                );

        long now =
                System.currentTimeMillis();

        for (String key : ids) {

            int separator =
                    key.lastIndexOf("|");

            if (separator <= 0) {
                continue;
            }

            String alarmId =
                    key.substring(0, separator);

            boolean snooze =
                    key.substring(separator + 1).equals("s");

            ScheduledRecord record =
                    loadRecord(
                            context,
                            alarmId,
                            snooze
                    );

            if (record == null) {
                continue;
            }

            if (snooze) {

                if (record.triggerAtMillis > now) {

                    scheduleInternal(
                            context,
                            alarmId,
                            record.triggerAtMillis,
                            true,
                            record.label
                    );

                } else {
                    removeRecord(
                            context,
                            alarmId,
                            true
                    );
                }

                continue;
            }

            if (record.repeatMask == 0) {

                if (record.triggerAtMillis > now) {

                    scheduleInternal(
                            context,
                            alarmId,
                            record.triggerAtMillis,
                            false,
                            record.label
                    );

                } else {

                    removeRecord(
                            context,
                            alarmId,
                            false
                    );
                }

            } else {

                long next =
                        computeNextRepeating(
                                now,
                                record.hour,
                                record.minute,
                                record.repeatMask
                        );

                saveRecord(
                        context,
                        alarmId,
                        next,
                        false,
                        record.label,
                        record.hour,
                        record.minute,
                        record.repeatMask
                );

                scheduleInternal(
                        context,
                        alarmId,
                        next,
                        false,
                        record.label
                );
            }
        }
    }

    // ------------------------------------------------------------
    // PERSISTENCE
    // ------------------------------------------------------------

    private static void saveRecord(
            Context context,
            String alarmId,
            long triggerAtMillis,
            boolean snooze,
            String label,
            int hour,
            int minute,
            int repeatMask) {

        android.content.SharedPreferences prefs =
                context.getSharedPreferences(
                        PREFS_NAME,
                        Context.MODE_PRIVATE
                );

        String key =
                recordKey(alarmId, snooze);

        Set<String> ids =
                new HashSet<>(
                        prefs.getStringSet(
                                KEY_IDS,
                                Collections.<String>emptySet()
                        )
                );

        ids.add(key);

        prefs.edit()
                .putStringSet(KEY_IDS, ids)
                .putLong(key + ".trigger", triggerAtMillis)
                .putBoolean(key + ".snooze", snooze)
                .putString(key + ".label", label == null ? "" : label)
                .putInt(key + ".hour", hour)
                .putInt(key + ".minute", minute)
                .putInt(key + ".mask", repeatMask)
                .apply();
    }

    private static ScheduledRecord loadRecord(
            Context context,
            String alarmId,
            boolean snooze) {

        android.content.SharedPreferences prefs =
                context.getSharedPreferences(
                        PREFS_NAME,
                        Context.MODE_PRIVATE
                );

        String key =
                recordKey(alarmId, snooze);

        if (!prefs.contains(key + ".trigger")) {
            return null;
        }

        ScheduledRecord record =
                new ScheduledRecord();

        record.triggerAtMillis =
                prefs.getLong(
                        key + ".trigger",
                        0
                );

        record.label =
                prefs.getString(
                        key + ".label",
                        ""
                );

        record.hour =
                prefs.getInt(
                        key + ".hour",
                        0
                );

        record.minute =
                prefs.getInt(
                        key + ".minute",
                        0
                );

        record.repeatMask =
                prefs.getInt(
                        key + ".mask",
                        0
                );

        return record;
    }

    private static void removeRecord(
            Context context,
            String alarmId,
            boolean snooze) {

        android.content.SharedPreferences prefs =
                context.getSharedPreferences(
                        PREFS_NAME,
                        Context.MODE_PRIVATE
                );

        String key =
                recordKey(alarmId, snooze);

        Set<String> ids =
                new HashSet<>(
                        prefs.getStringSet(
                                KEY_IDS,
                                Collections.<String>emptySet()
                        )
                );

        ids.remove(key);

        prefs.edit()
                .putStringSet(KEY_IDS, ids)
                .remove(key + ".trigger")
                .remove(key + ".snooze")
                .remove(key + ".label")
                .remove(key + ".hour")
                .remove(key + ".minute")
                .remove(key + ".mask")
                .apply();
    }

    // ------------------------------------------------------------
    // REPEATING DAY CALCULATION
    // ------------------------------------------------------------

    private static long computeNextRepeating(
            long nowMillis,
            int hour,
            int minute,
            int repeatMask) {

        Calendar now =
                Calendar.getInstance();

        now.setTimeInMillis(nowMillis);

        for (int add = 0; add <= 7; add++) {

            Calendar candidate =
                    (Calendar) now.clone();

            candidate.add(
                    Calendar.DAY_OF_YEAR,
                    add
            );

            candidate.set(
                    Calendar.HOUR_OF_DAY,
                    hour
            );

            candidate.set(
                    Calendar.MINUTE,
                    minute
            );

            candidate.set(
                    Calendar.SECOND,
                    0
            );

            candidate.set(
                    Calendar.MILLISECOND,
                    0
            );

            int sundayBased =
                    candidate.get(Calendar.DAY_OF_WEEK);

            int mondayIndex =
                    (sundayBased + 5) % 7;

            boolean selected =
                    (repeatMask & (1 << mondayIndex)) != 0;

            if (selected
                    && candidate.getTimeInMillis() > nowMillis) {

                return candidate.getTimeInMillis();
            }
        }

        return nowMillis + 7L * 24L * 60L * 60L * 1000L;
    }

    // ------------------------------------------------------------
    // IDS
    // ------------------------------------------------------------

    private static String recordKey(
            String alarmId,
            boolean snooze) {

        return "alarm."
                + alarmId
                + "|"
                + (snooze ? "s" : "a");
    }

    private static int stableCode(
            String alarmId,
            boolean snooze) {

        return (alarmId
                + (snooze ? "#s" : "#a"))
                .hashCode()
                & 0x7fffffff;
    }

    private static int notificationId(
            String alarmId) {

        return ("notify#" + alarmId)
                .hashCode()
                & 0x7fffffff;
    }

    private static class ScheduledRecord {

        long triggerAtMillis;
        String label;
        int hour;
        int minute;
        int repeatMask;
    }
}