package org.yashtech.redalarm;

import android.app.ActivityManager;
import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.text.TextUtils;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Calendar;
import java.util.Locale;
import java.util.Map;

/** Native exact-alarm and reboot bridge. The Python/Kivy Activity is never
 * required to be alive for an alarm to start ringing. */
public final class RedAlarmNativeBridge {
    private static final String PREFS = "redalarm_native_alarms_v1";
    private static final String RING_CHANNEL = "redalarm_ringing_v2";
    private static final String NEXT_CHANNEL = "redalarm_next_alarm_v1";
    private static final int NEXT_ID = 1001;
    private static final int RING_ID = 1002;
    private static final String FIRE_ACTION = "org.yashtech.redalarm.FIRE.";

    private RedAlarmNativeBridge() { }

    static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static String configKey(String id) { return "config:" + id; }
    static String enabledKey(String id) { return "enabled:" + id; }
    static String timeKey(String id) { return "time:" + id; }
    static String snoozeKey(String id) { return "snooze:" + id; }
    static String ringingKey(String id) { return "ringing:" + id; }

    public static void scheduleAlarm(Context context, String alarmId, String alarmJson,
                                     String storePath, long triggerAtMillis, boolean snooze) {
        if (context == null || TextUtils.isEmpty(alarmId) || TextUtils.isEmpty(alarmJson)) return;
        Context app = context.getApplicationContext();
        SharedPreferences p = prefs(app);
        JSONObject config;
        try { config = new JSONObject(alarmJson); }
        catch (JSONException e) { android.util.Log.e("RedAlarmNative", "Invalid alarm JSON", e); return; }

        SharedPreferences.Editor editor = p.edit()
                .putString(configKey(alarmId), config.toString());
        if (!TextUtils.isEmpty(storePath)) editor.putString("store_path", storePath);
        if (snooze) {
            editor.putLong(snoozeKey(alarmId), triggerAtMillis);
        } else {
            editor.putLong(timeKey(alarmId), triggerAtMillis)
                    .putBoolean(enabledKey(alarmId), config.optBoolean("enabled", true));
        }
        editor.apply();

        Intent fire = new Intent(app, RedAlarmAlarmReceiver.class);
        fire.setAction(FIRE_ACTION + alarmId + (snooze ? ".SNOOZE" : ".REGULAR"));
        fire.putExtra("alarm_id", alarmId);
        fire.putExtra("alarm_kind", snooze ? "snooze" : "regular");
        fire.putExtra("trigger_at", triggerAtMillis);
        PendingIntent operation = PendingIntent.getBroadcast(app,
                requestCode(alarmId, snooze ? "snooze" : ""), fire,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Intent show = app.getPackageManager().getLaunchIntentForPackage(app.getPackageName());
        if (show == null) {
            show = new Intent(app, org.kivy.android.PythonActivity.class);
        }
        show.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        show.setAction("org.yashtech.redalarm.SHOW_ALARM." + alarmId);
        PendingIntent showPi = PendingIntent.getActivity(app,
                requestCode(alarmId, "show"), show,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        long when = Math.max(System.currentTimeMillis() + 500L, triggerAtMillis);
        try {
            AlarmManager manager = (AlarmManager) app.getSystemService(Context.ALARM_SERVICE);
            if (manager == null) throw new IllegalStateException("AlarmManager unavailable");
            manager.setAlarmClock(new AlarmManager.AlarmClockInfo(when, showPi), operation);
        } catch (Throwable e) {
            android.util.Log.e("RedAlarmNative", "Could not set exact alarm " + alarmId, e);
        }
        updateNextAlarmNotification(app);
    }

    public static void cancelAlarm(Context context, String alarmId, boolean snooze) {
        if (context == null || TextUtils.isEmpty(alarmId)) return;
        Context app = context.getApplicationContext();
        SharedPreferences.Editor editor = prefs(app).edit();
        if (snooze) editor.remove(snoozeKey(alarmId));
        else editor.remove(timeKey(alarmId)).putBoolean(enabledKey(alarmId), false);
        editor.apply();
        Intent fire = new Intent(app, RedAlarmAlarmReceiver.class);
        fire.setAction(FIRE_ACTION + alarmId + (snooze ? ".SNOOZE" : ".REGULAR"));
        PendingIntent pi = PendingIntent.getBroadcast(app,
                requestCode(alarmId, snooze ? "snooze" : ""), fire,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        AlarmManager manager = (AlarmManager) app.getSystemService(Context.ALARM_SERVICE);
        if (manager != null) manager.cancel(pi);
        pi.cancel();
        updateNextAlarmNotification(app);
    }

    public static boolean isRinging(Context context, String alarmId) {
        if (context == null || TextUtils.isEmpty(alarmId)) return false;
        return prefs(context).getBoolean(ringingKey(alarmId), false);
    }

    public static boolean isAnyRinging(Context context) {
        return context != null && !TextUtils.isEmpty(prefs(context).getString("ringing_id", ""));
    }

    public static boolean hasRecentNativeFire(Context context, String alarmId) {
        if (context == null || TextUtils.isEmpty(alarmId)) return false;
        long last = prefs(context).getLong("last_fire:" + alarmId, 0L);
        long age = System.currentTimeMillis() - last;
        // Suppress a delayed onNewIntent after native ringing already auto-dismissed.
        return last > 0L && age >= 0L && age < 12L * 60L * 60L * 1000L;
    }

    public static void stopRinging(Context context, String alarmId) {
        if (context == null) return;
        Context app = context.getApplicationContext();
        SharedPreferences p = prefs(app);
        String current = p.getString("ringing_id", "");
        // The foreground service can only ring one alarm at a time. Ignore stale
        // cleanup from an old RingScreen if the service now belongs to another ID.
        if (TextUtils.isEmpty(current) || TextUtils.isEmpty(alarmId) || !current.equals(alarmId)) return;
        SharedPreferences.Editor e = p.edit();
        e.putBoolean(ringingKey(current), false).remove("ringing_id").apply();
        app.stopService(new Intent(app, RedAlarmRingingService.class));
        NotificationManager nm = (NotificationManager) app.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(RING_ID);
        updateNextAlarmNotification(app);
    }


    /** Handle ring controls without starting the Kivy/Python activity. */
    public static void performRingAction(Context context, String alarmId, String kind) {
        if (context == null || TextUtils.isEmpty(alarmId) || TextUtils.isEmpty(kind)) return;
        Context app = context.getApplicationContext();
        String current = prefs(app).getString("ringing_id", "");
        if (!alarmId.equals(current)) return;

        if ("snooze".equals(kind)) {
            String raw = getConfig(app, alarmId);
            if (!TextUtils.isEmpty(raw)) {
                try {
                    JSONObject config = new JSONObject(raw);
                    if (!config.optBoolean("snooze_enabled", true)) return;
                    int seconds = Math.max(1, Math.min(10800, config.optInt("snooze_sec", 60)));
                    scheduleAlarm(app, alarmId, raw, getStorePath(app),
                            System.currentTimeMillis() + seconds * 1000L, true);
                } catch (JSONException e) {
                    android.util.Log.e("RedAlarmNative", "Snooze configuration invalid", e);
                }
            }
        } else if ("dismiss".equals(kind)) {
            cancelAlarm(app, alarmId, true);
        } else {
            return;
        }

        stopRinging(app, alarmId);
        Intent finished = new Intent(RedAlarmRingActivity.ACTION_RING_FINISHED);
        finished.setPackage(app.getPackageName());
        finished.putExtra("alarm_id", alarmId);
        app.sendBroadcast(finished);
    }

    /** Remove the normal app task before displaying the independent ring task. */
    public static void closeNormalAppTasks(Context context) {
        if (context == null) return;
        try {
            ActivityManager manager = (ActivityManager) context.getApplicationContext()
                    .getSystemService(Context.ACTIVITY_SERVICE);
            if (manager == null) return;
            for (ActivityManager.AppTask task : manager.getAppTasks()) {
                try {
                    Intent base = task.getTaskInfo().baseIntent;
                    ComponentName component = base == null ? null : base.getComponent();
                    if (component == null) continue;
                    if (RedAlarmRingActivity.class.getName().equals(component.getClassName())) continue;
                    task.finishAndRemoveTask();
                } catch (Throwable e) {
                    android.util.Log.w("RedAlarmNative", "Could not remove normal app task", e);
                }
            }
        } catch (Throwable e) {
            android.util.Log.w("RedAlarmNative", "App-task cleanup unavailable", e);
        }
    }

    static String getConfig(Context context, String alarmId) {
        return prefs(context).getString(configKey(alarmId), null);
    }

    static String getStorePath(Context context) {
        return prefs(context).getString("store_path", "");
    }

    static boolean isEnabled(Context context, String alarmId, JSONObject config) {
        return prefs(context).getBoolean(enabledKey(alarmId), config.optBoolean("enabled", true));
    }

    static void markOneTimeComplete(Context context, String alarmId) {
        Context app = context.getApplicationContext();
        SharedPreferences p = prefs(app);
        p.edit().putBoolean(enabledKey(alarmId), false).remove(timeKey(alarmId)).apply();
        String path = getStorePath(app);
        if (!TextUtils.isEmpty(path)) markStoredAlarmDisabled(new File(path), alarmId);
        updateNextAlarmNotification(app);
    }

    static long nextRepeatTrigger(JSONObject config, long nowMillis) {
        JSONArray days = config.optJSONArray("days");
        if (days == null) return nowMillis + 24L * 60L * 60L * 1000L;
        boolean[] selected = new boolean[7];
        boolean any = false;
        for (int i = 0; i < 7 && i < days.length(); i++) {
            selected[i] = days.optBoolean(i, false);
            any |= selected[i];
        }
        if (!any) return 0L;
        Calendar now = Calendar.getInstance(); now.setTimeInMillis(nowMillis);
        for (int add = 0; add <= 8; add++) {
            Calendar candidate = (Calendar) now.clone();
            candidate.add(Calendar.DAY_OF_YEAR, add);
            int hour = Math.max(0, Math.min(23, config.optInt("hour", 7)));
            int minute = Math.max(0, Math.min(59, config.optInt("minute", 0)));
            candidate.set(Calendar.HOUR_OF_DAY, hour);
            candidate.set(Calendar.MINUTE, minute);
            candidate.set(Calendar.SECOND, 0);
            candidate.set(Calendar.MILLISECOND, 0);
            int weekday = (candidate.get(Calendar.DAY_OF_WEEK) + 5) % 7; // Monday=0
            if (selected[weekday] && candidate.getTimeInMillis() > nowMillis + 250L)
                return candidate.getTimeInMillis();
        }
        return nowMillis + 7L * 24L * 60L * 60L * 1000L;
    }

    static boolean isRepeating(JSONObject config) {
        JSONArray days = config.optJSONArray("days");
        if (days == null) return false;
        for (int i = 0; i < Math.min(7, days.length()); i++) if (days.optBoolean(i, false)) return true;
        return false;
    }

    private static long nextOneTimeTrigger(JSONObject config, long nowMillis) {
        Calendar c = Calendar.getInstance(); c.setTimeInMillis(nowMillis);
        c.set(Calendar.HOUR_OF_DAY, Math.max(0, Math.min(23, config.optInt("hour", 7))));
        c.set(Calendar.MINUTE, Math.max(0, Math.min(59, config.optInt("minute", 0))));
        c.set(Calendar.SECOND, 0); c.set(Calendar.MILLISECOND, 0);
        if (c.getTimeInMillis() <= nowMillis + 250L) c.add(Calendar.DAY_OF_YEAR, 1);
        return c.getTimeInMillis();
    }

    /** Called only by the BOOT_COMPLETED/package/time-change receiver. */
    public static void restoreOnBoot(Context context) {
        if (context == null) return;
        Context app = context.getApplicationContext();
        SharedPreferences p = prefs(app);
        long now = System.currentTimeMillis();
        Map<String, ?> all = p.getAll();
        for (String key : all.keySet()) {
            if (!key.startsWith("config:")) continue;
            String id = key.substring("config:".length());
            String raw = p.getString(key, null);
            if (TextUtils.isEmpty(raw)) continue;
            JSONObject config;
            try { config = new JSONObject(raw); }
            catch (JSONException ex) { android.util.Log.e("RedAlarmNative", "Bad saved alarm " + id, ex); continue; }
            boolean enabled = p.getBoolean(enabledKey(id), config.optBoolean("enabled", true));
            if (enabled) {
                long stored = p.getLong(timeKey(id), 0L);
                long next;
                if (isRepeating(config)) {
                    // Recalculate in local wall-clock time after timezone/manual-clock changes.
                    next = nextRepeatTrigger(config, now + 500L);
                } else if (stored <= now) {
                    // One-time alarm passed while the phone was off: deliver once now.
                    next = now + 2500L;
                } else {
                    next = nextOneTimeTrigger(config, now);
                }
                if (next > 0L) scheduleAlarm(app, id, raw, getStorePath(app), next, false);
            }
            long snooze = p.getLong(snoozeKey(id), 0L);
            if (snooze > 0L) {
                if (snooze <= now) snooze = now + 2500L;
                scheduleAlarm(app, id, raw, getStorePath(app), snooze, true);
            }
        }
        updateNextAlarmNotification(app);
    }

    static void refreshNextAlarm(Context context) { updateNextAlarmNotification(context.getApplicationContext()); }

    private static void updateNextAlarmNotification(Context context) {
        SharedPreferences p = prefs(context);
        long now = System.currentTimeMillis();
        long earliest = Long.MAX_VALUE;
        String chosen = "";
        boolean chosenSnooze = false;
        Map<String, ?> all = p.getAll();
        for (String key : all.keySet()) {
            if (!key.startsWith("config:")) continue;
            String id = key.substring("config:".length());
            String raw = p.getString(key, null);
            if (TextUtils.isEmpty(raw)) continue;
            JSONObject config;
            try { config = new JSONObject(raw); } catch (JSONException e) { continue; }
            if (p.getBoolean(enabledKey(id), config.optBoolean("enabled", true))) {
                long candidate = p.getLong(timeKey(id), 0L);
                if (candidate > now && candidate < earliest) {
                    earliest = candidate; chosen = id; chosenSnooze = false;
                }
            }
            long snooze = p.getLong(snoozeKey(id), 0L);
            if (snooze > now && snooze < earliest) {
                earliest = snooze; chosen = id; chosenSnooze = true;
            }
        }
        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (earliest == Long.MAX_VALUE) { nm.cancel(NEXT_ID); return; }
        ensureNextChannel(context, nm);
        JSONObject cfg;
        try { cfg = new JSONObject(p.getString(configKey(chosen), "{}")); }
        catch (JSONException e) { cfg = new JSONObject(); }
        String label = cfg.optString("label", "Alarm").trim();
        if (label.isEmpty()) label = "Alarm";
        Calendar c = Calendar.getInstance(); c.setTimeInMillis(earliest);
        String clock = String.format(Locale.getDefault(), "%d:%02d %s",
                (c.get(Calendar.HOUR) == 0 ? 12 : c.get(Calendar.HOUR)),
                c.get(Calendar.MINUTE), c.get(Calendar.AM_PM) == Calendar.AM ? "AM" : "PM");
        long mins = Math.max(0L, (earliest - now + 59999L) / 60000L);
        String eta = "Your next alarm in " + (mins / 60L) + " hr " + (mins % 60L) + " min";
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, NEXT_CHANNEL)
                : new Notification.Builder(context).setPriority(Notification.PRIORITY_LOW);
        b.setContentTitle("RedAlarm • Next alarm")
                .setContentText(eta)
                .setSubText(label + " • " + clock + (chosenSnooze ? " • Snoozed" : ""))
                .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setCategory(Notification.CATEGORY_ALARM)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setWhen(earliest).setShowWhen(true).setUsesChronometer(true)
                .setOngoing(true).setAutoCancel(false).setOnlyAlertOnce(true);
        if (Build.VERSION.SDK_INT >= 24) b.setChronometerCountDown(true);
        Notification n = b.build();
        n.flags |= Notification.FLAG_NO_CLEAR | Notification.FLAG_ONGOING_EVENT;
        nm.notify(NEXT_ID, n);
    }

    private static void ensureNextChannel(Context context, NotificationManager nm) {
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(NEXT_CHANNEL) == null) {
            NotificationChannel channel = new NotificationChannel(NEXT_CHANNEL,
                    "Next scheduled alarm", NotificationManager.IMPORTANCE_LOW);
            channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            channel.setSound(null, null);
            nm.createNotificationChannel(channel);
        }
    }

    static int requestCode(String id, String salt) {
        try {
            byte[] digest = MessageDigest.getInstance("MD5").digest((id + salt).getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) hex.append(String.format(Locale.US, "%02x", b & 0xff));
            return (int) (Long.parseLong(hex.substring(0, 7), 16) % 1_000_000L);
        } catch (Exception e) { return Math.abs((id + salt).hashCode()) % 1_000_000; }
    }

    private static void markStoredAlarmDisabled(File file, String id) {
        if (!file.isFile()) return;
        File temp = new File(file.getParentFile(), file.getName() + ".native-tmp");
        try {
            StringBuilder raw = new StringBuilder();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(file), StandardCharsets.UTF_8))) {
                String line; while ((line = r.readLine()) != null) raw.append(line).append('\n');
            }
            JSONArray arr = new JSONArray(raw.toString());
            boolean changed = false;
            for (int i = 0; i < arr.length(); i++) {
                JSONObject item = arr.optJSONObject(i);
                if (item != null && id.equals(item.optString("id"))) {
                    item.put("enabled", false); changed = true;
                }
            }
            if (!changed) return;
            try (BufferedWriter w = new BufferedWriter(new OutputStreamWriter(new FileOutputStream(temp), StandardCharsets.UTF_8))) {
                w.write(arr.toString(2)); w.flush();
            }
            if (!temp.renameTo(file)) {
                try (FileInputStream in = new FileInputStream(temp); FileOutputStream out = new FileOutputStream(file)) {
                    byte[] buf = new byte[8192]; int n;
                    while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                    out.flush();
                }
                temp.delete();
            }
        } catch (Throwable e) {
            android.util.Log.e("RedAlarmNative", "Could not persist one-time alarm completion", e);
            temp.delete();
        }
    }
}
