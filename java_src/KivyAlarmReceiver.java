package org.kivy.android;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;

/** Native alarm restore for reboot and wall-clock/time-zone changes.
 *  Does not try to launch the whole Activity from a background broadcast.
 */
public class KivyAlarmReceiver extends BroadcastReceiver {
    private static final int NEXT_NOTIFICATION_ID = 1001;
    private static final String NEXT_CHANNEL_ID = "redalarm_next_alarm_v1";
    private static final String ACTION_FIRE_ALARM = "com.redalarm.FIRE_ALARM";
    private static final String ACTION_REFRESH_SCHEDULES = "com.redalarm.REFRESH_SCHEDULES";

    @Override public void onReceive(Context context, Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (action == null) return;
        Context appContext = context.getApplicationContext();
        if (ACTION_FIRE_ALARM.equals(action)) {
            fireAlarmAndStartService(appContext, intent);
            return;
        }
        if (ACTION_REFRESH_SCHEDULES.equals(action)) {
            restoreSchedules(appContext);
            return;
        }
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_TIME_CHANGED.equals(action)
                && !Intent.ACTION_TIMEZONE_CHANGED.equals(action)
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) return;
        restoreSchedules(appContext);
    }

    private static File appDataFile(Context context, String filename) {
        File appDir = new File(context.getFilesDir(), "app");
        File preferred = new File(appDir, filename);
        if (preferred.isFile()) return preferred;
        File fallback = new File(context.getFilesDir(), filename);
        return fallback.isFile() ? fallback : preferred;
    }

    private static String readText(File file) {
        if (file == null || !file.isFile()) return null;
        StringBuilder output = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line;
            while ((line = reader.readLine()) != null) output.append(line);
            return output.toString();
        } catch (Exception ignored) { return null; }
    }

    private static int stableRequestCode(String alarmId, String salt) {
        try {
            byte[] digest = MessageDigest.getInstance("MD5")
                    .digest((alarmId + salt).getBytes("UTF-8"));
            StringBuilder hex = new StringBuilder();
            for (byte item : digest) hex.append(String.format(Locale.US, "%02x", item & 0xff));
            return (int)(Long.parseLong(hex.substring(0, 7), 16) % 1000000L);
        } catch (Exception ignored) {
            return Math.abs((alarmId + salt).hashCode()) % 1000000;
        }
    }

    private static PendingIntent firePendingIntent(Context context, String alarmId,
                                                    String salt, long triggerAt) {
        Intent fire = new Intent(context, KivyAlarmReceiver.class);
        fire.setAction(ACTION_FIRE_ALARM);
        fire.putExtra("alarm_id", alarmId);
        fire.putExtra("fire_token", Long.toString(triggerAt));
        fire.putExtra("fire_at", triggerAt);
        fire.putExtra("alarm_salt", salt == null ? "" : salt);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getBroadcast(context, stableRequestCode(alarmId, salt), fire, flags);
    }

    private static PendingIntent alarmShowIntent(Context context, String alarmId) {
        // Intentionally no alarm_id/fire_token extras: tapping the OS alarm glyph
        // opens the app but must not route into the actual ringing screen.
        Intent show = new Intent(context, PythonActivity.class);
        show.setAction("com.redalarm.SHOW_ALARM_" + alarmId);
        show.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getActivity(context, stableRequestCode(alarmId, "alarm_show"), show, flags);
    }

    private static long nextTrigger(JSONObject alarm, long nowMillis) throws JSONException {
        int hour = alarm.optInt("hour", 7);
        int minute = alarm.optInt("minute", 0);
        if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return -1L;
        JSONArray rawDays = alarm.optJSONArray("days");
        boolean[] days = new boolean[7];
        boolean repeats = false;
        if (rawDays != null) {
            for (int i = 0; i < 7 && i < rawDays.length(); i++) {
                days[i] = rawDays.optBoolean(i, false);
                repeats |= days[i];
            }
        }
        Calendar now = Calendar.getInstance();
        now.setTimeInMillis(nowMillis);
        if (!repeats) {
            Calendar candidate = (Calendar) now.clone();
            candidate.set(Calendar.HOUR_OF_DAY, hour);
            candidate.set(Calendar.MINUTE, minute);
            candidate.set(Calendar.SECOND, 0);
            candidate.set(Calendar.MILLISECOND, 0);
            if (candidate.getTimeInMillis() <= nowMillis) candidate.add(Calendar.DAY_OF_YEAR, 1);
            return candidate.getTimeInMillis();
        }
        for (int add = 0; add < 8; add++) {
            Calendar day = (Calendar) now.clone();
            day.add(Calendar.DAY_OF_YEAR, add);
            int mondayFirst = (day.get(Calendar.DAY_OF_WEEK) + 5) % 7;
            if (!days[mondayFirst]) continue;
            Calendar candidate = (Calendar) day.clone();
            candidate.set(Calendar.HOUR_OF_DAY, hour);
            candidate.set(Calendar.MINUTE, minute);
            candidate.set(Calendar.SECOND, 0);
            candidate.set(Calendar.MILLISECOND, 0);
            if (candidate.getTimeInMillis() > nowMillis) return candidate.getTimeInMillis();
        }
        return -1L;
    }

    private static final class NextAlarm {
        final String id, label;
        final long triggerAt;
        NextAlarm(String alarmId, String alarmLabel, long trigger) {
            id = alarmId; label = alarmLabel; triggerAt = trigger;
        }
    }

    private static void restoreSchedules(Context context) {
        try {
            File alarmsFile = appDataFile(context, "alarms.json");
            String raw = readText(alarmsFile);
            if (raw == null) {
                cancelNextNotification(context);
                return;
            }
            JSONArray array = new JSONArray(raw);
            JSONObject snoozes = new JSONObject();
            String snoozeRaw = readText(appDataFile(context, "snooze_state.json"));
            if (snoozeRaw != null) {
                try { snoozes = new JSONObject(snoozeRaw); } catch (JSONException ignored) { }
            }
            AlarmManager manager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
            long now = System.currentTimeMillis();
            NextAlarm next = null;
            java.util.HashMap<String, JSONObject> alarms = new java.util.HashMap<>();
            for (int i = 0; i < array.length(); i++) {
                JSONObject alarm = array.optJSONObject(i);
                if (alarm == null) continue;
                String id = alarm.optString("id", "");
                if (id.length() == 0) continue;
                alarms.put(id, alarm);
                PendingIntent fire = firePendingIntent(context, id, "", now);
                if (!alarm.optBoolean("enabled", true)) {
                    manager.cancel(fire);
                    continue;
                }
                long when = nextTrigger(alarm, now);
                if (when > now) {
                    fire = firePendingIntent(context, id, "", when);
                    manager.setAlarmClock(new AlarmManager.AlarmClockInfo(
                            when, alarmShowIntent(context, id)), fire);
                    String label = alarm.optString("label", "Alarm").trim();
                    if (label.length() == 0) label = "Alarm";
                    if (next == null || when < next.triggerAt) next = new NextAlarm(id, label, when);
                }
            }
            // Restore snooze timers too; they survive a phone reboot via snooze_state.json.
            java.util.Iterator<String> keys = snoozes.keys();
            while (keys.hasNext()) {
                String id = keys.next();
                JSONObject alarm = alarms.get(id);
                if (alarm == null) continue;
                try {
                    long when = (long)(snoozes.optDouble(id, 0.0) * 1000.0);
                    if (when <= now) continue;
                    PendingIntent fire = firePendingIntent(context, id, "snooze", when);
                    manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, when, fire);
                    String label = alarm.optString("label", "Alarm").trim();
                    if (label.length() == 0) label = "Alarm";
                    if (next == null || when < next.triggerAt) next = new NextAlarm(id, label, when);
                } catch (Exception ignored) { }
            }
            if (next == null) cancelNextNotification(context);
            else showNextNotification(context, next);
        } catch (Exception exc) {
            android.util.Log.e("RedAlarm", "Native alarm restore failed", exc);
        }
    }

    private static void fireAlarmAndStartService(Context context, Intent intent) {
        String alarmId = intent.getStringExtra("alarm_id");
        String salt = intent.getStringExtra("alarm_salt");
        if (salt == null) salt = "";
        if (alarmId == null || alarmId.trim().isEmpty()) return;
        android.util.Log.i("RedAlarm", "Alarm fire received: id=" + alarmId + " salt=" + salt);
        try {
            File alarmsFile = appDataFile(context, "alarms.json");
            String raw = readText(alarmsFile);
            if (raw == null) {
                android.util.Log.e("RedAlarm", "Cannot read alarm data file: " + alarmsFile.getAbsolutePath());
                return;
            }
            JSONArray array = new JSONArray(raw);
            JSONObject alarm = null;
            for (int i = 0; i < array.length(); i++) {
                JSONObject candidate = array.optJSONObject(i);
                if (candidate != null && alarmId.equals(candidate.optString("id", ""))) {
                    alarm = candidate;
                    break;
                }
            }
            if (alarm == null) {
                android.util.Log.e("RedAlarm", "No saved alarm matched id=" + alarmId + " in " + alarmsFile.getAbsolutePath());
                return;
            }
            boolean isSnooze = "snooze".equals(salt);
            if (!alarm.optBoolean("enabled", true) && !isSnooze) return;

            long now = System.currentTimeMillis();
            JSONArray days = alarm.optJSONArray("days");
            boolean repeats = false;
            if (days != null) {
                for (int i = 0; i < Math.min(7, days.length()); i++) {
                    repeats |= days.optBoolean(i, false);
                }
            }
            // Re-arm repeating alarms before audio starts so Activity startup latency
            // cannot lose the next occurrence. Use the same PendingIntent identity as Python.
            if (!isSnooze && repeats) {
                long next = nextTrigger(alarm, now + 30000L);
                if (next > now) {
                    AlarmManager manager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
                    PendingIntent fire = firePendingIntent(context, alarmId, "", next);
                    manager.setAlarmClock(new AlarmManager.AlarmClockInfo(next,
                            alarmShowIntent(context, alarmId)), fire);
                }
            }
            if (isSnooze) removeSnoozeEntry(context, alarmId);

            JSONObject config = new JSONObject();
            File alarmDataDir = alarmsFile.getParentFile();
            if (alarmDataDir == null) alarmDataDir = new File(context.getFilesDir(), "app");
            String appRoot = alarmDataDir.getAbsolutePath();
            String statePath = new File(context.getFilesDir(), "ring_service_state.json").getAbsolutePath();
            String configPath = statePath + ".config";
            String stopPath = new File(context.getFilesDir(), "ring_service_stop.json").getAbsolutePath();
            String label = alarm.optString("label", "Alarm").trim();
            if (label.isEmpty()) label = "Alarm";
            int hour = alarm.optInt("hour", 7) % 24;
            int minute = alarm.optInt("minute", 0) % 60;
            int hour12 = hour % 12;
            if (hour12 == 0) hour12 = 12;
            String ampm = hour >= 12 ? "PM" : "AM";
            String timeText = String.format(Locale.getDefault(), "%02d:%02d %s", hour12, minute, ampm);
            String sound = alarm.optString("sound_path", "");
            if (sound == null) sound = "";
            config.put("alarm_id", alarmId);
            config.put("title", label);
            config.put("time_text", timeText);
            config.put("sound_path", sound);
            File primaryFallback = new File(new File(appRoot, "ringtones"), "default_alarm.wav");
            File legacyFallback = new File(new File(context.getFilesDir(), "app/ringtones"), "default_alarm.wav");
            File selectedFallback = primaryFallback.isFile() ? primaryFallback : legacyFallback;
            config.put("fallback_path", selectedFallback.getAbsolutePath());
            android.util.Log.i("RedAlarm", "Ring audio paths: custom=" + sound + " fallback=" + selectedFallback.getAbsolutePath());
            config.put("logo_path", new File(appRoot, "splashimage.png").getAbsolutePath());
            config.put("clip_start_ms", Math.max(0, alarm.optInt("clip_start_ms", 0)));
            config.put("clip_duration_ms", Math.max(0, alarm.optInt("clip_duration_ms", 0)));
            config.put("duration_sec", Math.max(1, Math.min(10800, alarm.optInt("auto_dismiss_sec", 5))));
            config.put("volume", Math.max(0.0, Math.min(1.0, alarm.optDouble("volume", 0.80))));
            config.put("vibrate", alarm.optBoolean("vibrate", false));
            config.put("alarms_path", alarmsFile.getAbsolutePath());
            config.put("disable_one_time_on_auto", !repeats);
            config.put("state_path", statePath);
            config.put("config_path", configPath);
            config.put("stop_path", stopPath);
            // Remove stale state from the last ring and persist the sticky-service request.
            new File(statePath).delete();
            new File(stopPath).delete();
            writeTextAtomically(new File(configPath), config.toString());
            Class<?> serviceClass = Class.forName(context.getPackageName() + ".ServiceRing");
            android.util.Log.i("RedAlarm", "Starting ringtone service: " + serviceClass.getName());
            serviceClass.getMethod("start", Context.class, String.class).invoke(null, context, config.toString());
            android.util.Log.i("RedAlarm", "Ringtone service start request submitted for id=" + alarmId);
        } catch (Exception exc) {
            android.util.Log.e("RedAlarm", "Native alarm service launch failed", exc);
            // Last-resort compatibility fallback; Android may decline this background Activity.
            try {
                Intent launch = new Intent(context, PythonActivity.class);
                launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                launch.putExtra("alarm_id", alarmId);
                launch.putExtra("fire_token", intent.getStringExtra("fire_token"));
                context.startActivity(launch);
            } catch (Exception launchError) {
                android.util.Log.e("RedAlarm", "Activity fallback after service failure also failed", launchError);
            }
        }
    }

    private static void removeSnoozeEntry(Context context, String alarmId) {
        try {
            File file = appDataFile(context, "snooze_state.json");
            String raw = readText(file);
            if (raw == null) return;
            JSONObject state = new JSONObject(raw);
            state.remove(alarmId);
            writeTextAtomically(file, state.toString());
        } catch (Exception exc) {
            android.util.Log.w("RedAlarm", "Could not clear fired snooze entry", exc);
        }
    }

    private static void writeTextAtomically(File target, String value) throws Exception {
        File parent = target.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new java.io.IOException("Cannot create " + parent);
        }
        File temporary = new File(target.getAbsolutePath() + ".native.tmp");
        try (java.io.FileWriter writer = new java.io.FileWriter(temporary, false)) {
            writer.write(value);
            writer.flush();
        }
        if (target.exists() && !target.delete()) throw new java.io.IOException("Cannot replace " + target);
        if (!temporary.renameTo(target)) throw new java.io.IOException("Cannot rename temporary file to " + target);
    }

    private static void showNextNotification(Context context, NextAlarm alarm) {
        try {
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel channel = new NotificationChannel(
                        NEXT_CHANNEL_ID, "Next scheduled alarm", NotificationManager.IMPORTANCE_LOW);
                channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
                channel.enableVibration(false);
                channel.setSound(null, null);
                manager.createNotificationChannel(channel);
            }
            Intent open = new Intent(context, PythonActivity.class);
            open.setAction("com.redalarm.OPEN_NEXT_ALARM");
            open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                    | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= 23) piFlags |= PendingIntent.FLAG_IMMUTABLE;
            PendingIntent openPi = PendingIntent.getActivity(context, 1001, open, piFlags);
            long remainingMinutes = Math.max(0, (alarm.triggerAt - System.currentTimeMillis() + 59999L) / 60000L);
            long hours = remainingMinutes / 60L;
            long minutes = remainingMinutes % 60L;
            String eta = "Your next alarm in " + hours + " hr " + minutes + " min";
            String clock = new SimpleDateFormat("h:mm a", Locale.getDefault()).format(new Date(alarm.triggerAt));
            String sub = alarm.label + " • " + clock;
            Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                    ? new Notification.Builder(context, NEXT_CHANNEL_ID)
                    : new Notification.Builder(context).setPriority(Notification.PRIORITY_LOW);
            builder.setContentTitle("RedAlarm • Next alarm")
                    .setContentText(eta)
                    .setSubText(sub)
                    .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                    .setContentIntent(openPi)
                    .setCategory(Notification.CATEGORY_ALARM)
                    .setVisibility(Notification.VISIBILITY_PUBLIC)
                    .setWhen(alarm.triggerAt)
                    .setShowWhen(true)
                    .setUsesChronometer(true)
                    .setOngoing(true)
                    .setAutoCancel(false)
                    .setOnlyAlertOnce(true)
                    .setStyle(new Notification.BigTextStyle().bigText(eta + "\n" + sub));
            if (Build.VERSION.SDK_INT >= 24) builder.setChronometerCountDown(true);
            Notification notification = builder.build();
            notification.flags |= Notification.FLAG_NO_CLEAR | Notification.FLAG_ONGOING_EVENT;
            manager.notify(NEXT_NOTIFICATION_ID, notification);
        } catch (SecurityException ignored) {
            // Notification permission may be denied; alarms still restore.
        } catch (Exception exc) {
            android.util.Log.e("RedAlarm", "Next-alarm notification refresh failed", exc);
        }
    }

    private static void cancelNextNotification(Context context) {
        try {
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            manager.cancel(NEXT_NOTIFICATION_ID);
        } catch (Exception ignored) { }
    }
}
