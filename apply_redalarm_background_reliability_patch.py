#!/usr/bin/env python3
"""Apply RedAlarm's Android background/lock-screen/reboot reliability patch.

Run from the RedAlarm repository root in GitHub Codespaces:
    python apply_redalarm_background_reliability_patch.py

The script requires a clean working tree, creates a local safety backup, and
switches to fix/android-background-ringing (or uses it if already checked out).
It modifies only the alarm delivery/service wiring, manifest permissions, and
removes the broken CANCEL button from the alarm confirmation page.
"""
from __future__ import annotations
import datetime as _dt
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path.cwd().resolve()
EXPECTED = {
    "main.py": "def android_schedule_alarm(",
    "buildozer.spec": "android.permissions =",
    "java_src/manifest_hook.py": "def after_apk_build(toolchain):",
    "redalarm_timepicker.py": "class RoundedActionButton(Button):",
    ".github/workflows/build.yml": "      - yashh-tech-patch-2",
}


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=check)


def fail(message: str) -> None:
    print("ERROR:", message, file=sys.stderr)
    raise SystemExit(2)


def write_text(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        fail(f"Safety check for {label}: expected one source anchor, found {count}. No files were changed yet.")
    return source.replace(old, new, 1)


def stable_request_code(alarm_id: str, salt: str = "") -> int:
    import hashlib
    return int(hashlib.md5((alarm_id + salt).encode("utf-8")).hexdigest()[:7], 16) % 1_000_000


def ensure_repo_and_branch() -> None:
    if not (ROOT / ".git").exists():
        fail("Run this script from the RedAlarm repository root (the folder containing .git and main.py).")
    for rel, anchor in EXPECTED.items():
        path = ROOT / rel
        if not path.is_file() or anchor not in path.read_text(encoding="utf-8"):
            fail(f"Expected RedAlarm file/anchor not found: {rel}. Please switch to yashh-tech-patch-2 and try again.")
    branch = run("git", "branch", "--show-current").stdout.strip()
    if branch not in ("yashh-tech-patch-2", "fix/android-background-ringing"):
        fail(f"Current branch is '{branch}', not 'yashh-tech-patch-2'. Switch branches first; no files were changed.")
    status_lines = run("git", "status", "--porcelain").stdout.splitlines()
    # The user may upload this installer into the repository root in Codespaces.
    # Treat the installer itself as a delivery helper, not a project modification.
    status_lines = [line for line in status_lines
                    if line[3:].strip() not in {"apply_redalarm_background_reliability_patch.py"}]
    if status_lines:
        print("\n".join(status_lines))
        fail("Working tree is not clean. Commit/stash your existing changes before applying the patch; no project files were changed.")
    if branch != "fix/android-background-ringing":
        exists = run("git", "show-ref", "--verify", "--quiet", "refs/heads/fix/android-background-ringing", check=False).returncode == 0
        if exists:
            fail("Local branch fix/android-background-ringing already exists. Switch to it or rename it before applying this patch.")
        result = run("git", "switch", "-c", "fix/android-background-ringing", check=False)
        if result.returncode:
            fail("Could not create the local fix branch:\n" + result.stdout)
        print(result.stdout.strip())


# Java helper: owns exact alarms, reboot re-arming, persistent next-alarm notification,
# one-time completion state, and shared state consumed by the ringing service.
BRIDGE_JAVA = r'''package org.yashtech.redalarm;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
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
'''

RECEIVER_JAVA = r'''package org.yashtech.redalarm;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.text.TextUtils;
import org.json.JSONException;
import org.json.JSONObject;

/** Receives an exact AlarmManager broadcast and starts the independent ring service. */
public final class RedAlarmAlarmReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        String id = intent.getStringExtra("alarm_id");
        String kind = intent.getStringExtra("alarm_kind");
        if (TextUtils.isEmpty(id)) return;
        boolean snooze = "snooze".equals(kind);
        String raw = RedAlarmNativeBridge.getConfig(context, id);
        if (TextUtils.isEmpty(raw)) return;
        JSONObject config;
        try { config = new JSONObject(raw); }
        catch (JSONException e) { android.util.Log.e("RedAlarmNative", "Bad alarm configuration", e); return; }
        SharedPreferences p = context.getApplicationContext().getSharedPreferences("redalarm_native_alarms_v1", Context.MODE_PRIVATE);
        if (!snooze && !RedAlarmNativeBridge.isEnabled(context, id, config)) {
            RedAlarmNativeBridge.refreshNextAlarm(context); return;
        }
        if (snooze) {
            p.edit().remove("snooze:" + id).apply();
        } else {
            p.edit().remove("time:" + id).apply();
            if (RedAlarmNativeBridge.isRepeating(config)) {
                long next = RedAlarmNativeBridge.nextRepeatTrigger(config, System.currentTimeMillis());
                if (next > 0L) RedAlarmNativeBridge.scheduleAlarm(context, id, raw,
                        RedAlarmNativeBridge.getStorePath(context), next, false);
            } else {
                // Persist this before starting Activity/Service so restart cannot
                // turn a one-shot into tomorrow's alarm if Python never runs.
                RedAlarmNativeBridge.markOneTimeComplete(context, id);
            }
        }
        p.edit().putBoolean("ringing:" + id, true).putString("ringing_id", id)
                .putLong("last_fire:" + id, System.currentTimeMillis()).apply();
        Intent service = new Intent(context, RedAlarmRingingService.class);
        service.setAction(RedAlarmRingingService.ACTION_RING);
        service.putExtra("alarm_id", id);
        service.putExtra("alarm_json", raw);
        service.putExtra("alarm_kind", snooze ? "snooze" : "regular");
        try {
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(service);
            else context.startService(service);
        } catch (Throwable e) {
            android.util.Log.e("RedAlarmNative", "Could not start native ringing service", e);
            p.edit().putBoolean("ringing:" + id, false).remove("ringing_id").apply();
        }
        RedAlarmNativeBridge.refreshNextAlarm(context);
    }
}
'''

RING_SERVICE_JAVA = r'''package org.yashtech.redalarm;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.text.TextUtils;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.File;

/** Independent Android media-playback foreground service. It continues if the
 * Kivy Activity pauses, the display locks, or the Activity process is reclaimed. */
public final class RedAlarmRingingService extends Service {
    public static final String ACTION_RING = "org.yashtech.redalarm.RING";
    private static final String CHANNEL = "redalarm_ringing_v2";
    private static final int NOTIFICATION_ID = 1002;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private MediaPlayer player;
    private PowerManager.WakeLock wakeLock;
    private Vibrator vibrator;
    private String alarmId = "";
    private int session = 0;
    private final Runnable timeout = new Runnable() { @Override public void run() { stopAndFinish(); } };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || !ACTION_RING.equals(intent.getAction())) { stopSelf(startId); return START_NOT_STICKY; }
        String id = intent.getStringExtra("alarm_id");
        String raw = intent.getStringExtra("alarm_json");
        if (TextUtils.isEmpty(id)) { stopSelf(startId); return START_NOT_STICKY; }
        if (TextUtils.isEmpty(raw)) raw = RedAlarmNativeBridge.getConfig(this, id);
        JSONObject config;
        try { config = new JSONObject(raw == null ? "{}" : raw); }
        catch (JSONException e) { config = new JSONObject(); }
        stopCurrentPlayback();
        handler.removeCallbacks(timeout);
        alarmId = id;
        session++;
        ensureRingChannel();
        Notification notification = buildNotification(id, config);
        try { startForeground(NOTIFICATION_ID, notification); }
        catch (Throwable e) { android.util.Log.e("RedAlarmNative", "startForeground failed", e); }
        getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                .putBoolean("ringing:" + id, true).putString("ringing_id", id).apply();
        acquireWakeLock(Math.max(1, config.optInt("auto_dismiss_sec", 5)) + 15);
        startAudio(config);
        if (config.optBoolean("vibrate", false)) startVibration();
        int duration = Math.max(1, Math.min(10800, config.optInt("auto_dismiss_sec", 5)));
        final int run = session;
        handler.postDelayed(new Runnable() { @Override public void run() { if (run == session) stopAndFinish(); } }, duration * 1000L);
        return START_NOT_STICKY;
    }

    private void ensureRingChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Alarm ringing", NotificationManager.IMPORTANCE_HIGH);
            channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            channel.enableVibration(false);
            channel.setSound(null, null);
            nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification(String id, JSONObject config) {
        String label = config.optString("label", "Alarm").trim();
        if (label.isEmpty()) label = "Alarm";
        int hour = Math.max(0, Math.min(23, config.optInt("hour", 7)));
        int minute = Math.max(0, Math.min(59, config.optInt("minute", 0)));
        String time = String.format(java.util.Locale.getDefault(), "%d:%02d %s",
                (hour % 12 == 0 ? 12 : hour % 12), minute, hour >= 12 ? "PM" : "AM");
        String nonce = "native_" + System.currentTimeMillis();
        Intent open = new Intent(this, org.kivy.android.PythonActivity.class);
        open.setAction("org.yashtech.redalarm.NATIVE_FIRE." + id);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        open.putExtra("alarm_id", id);
        open.putExtra("fire_token", nonce);
        open.putExtra("native_ring", true);
        PendingIntent content = PendingIntent.getActivity(this, RedAlarmNativeBridge.requestCode(id, "ring_tap"), open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent dismiss = actionPendingIntent(id, "dismiss");
        PendingIntent snooze = actionPendingIntent(id, "snooze");
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this).setPriority(Notification.PRIORITY_MAX);
        b.setContentTitle(label).setContentText("Alarm • " + time)
                .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setCategory(Notification.CATEGORY_ALARM)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setContentIntent(content).setFullScreenIntent(content, true)
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Dismiss", dismiss)
                .addAction(android.R.drawable.ic_popup_reminder, "Snooze", snooze)
                .setOngoing(true).setAutoCancel(false).setOnlyAlertOnce(true);
        Notification n = b.build();
        n.flags |= Notification.FLAG_NO_CLEAR | Notification.FLAG_ONGOING_EVENT;
        return n;
    }

    private PendingIntent actionPendingIntent(String id, String kind) {
        Intent i = new Intent(this, org.kivy.android.PythonActivity.class);
        i.setAction("org.yashtech.redalarm.ACTION." + kind.toUpperCase() + "." + id);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        i.putExtra("alarm_id", id);
        i.putExtra("action_kind", kind);
        i.putExtra("fire_token", kind + "_" + System.currentTimeMillis());
        return PendingIntent.getActivity(this, RedAlarmNativeBridge.requestCode(id, "notif_" + kind), i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private void acquireWakeLock(int seconds) {
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null) {
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RedAlarm:NativeRinging");
                wakeLock.acquire(seconds * 1000L);
            }
        } catch (Throwable e) { android.util.Log.w("RedAlarmNative", "Wake lock unavailable", e); }
    }

    private void startAudio(JSONObject config) {
        String[] paths = new String[] {
                config.optString("native_sound_path", ""),
                config.optString("native_fallback_path", ""),
                config.optString("sound_path", "")
        };
        float volume = (float) Math.max(0.0, Math.min(1.0, config.optDouble("volume", 0.80)));
        for (String path : paths) {
            if (TextUtils.isEmpty(path) || path.startsWith("content:") || !new File(path).isFile()) continue;
            try {
                MediaPlayer mp = new MediaPlayer();
                AudioAttributes attrs = new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
                mp.setAudioAttributes(attrs);
                mp.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
                mp.setDataSource(path);
                mp.setLooping(true);
                mp.setVolume(volume, volume);
                mp.prepare(); mp.start(); player = mp; return;
            } catch (Throwable e) { android.util.Log.e("RedAlarmNative", "Ringtone path failed: " + path, e); }
        }
        try {
            Uri uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            if (uri == null) uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
            if (uri != null) {
                MediaPlayer mp = new MediaPlayer();
                mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                mp.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
                mp.setDataSource(this, uri); mp.setLooping(true); mp.setVolume(volume, volume);
                mp.prepare(); mp.start(); player = mp;
            }
        } catch (Throwable e) { android.util.Log.e("RedAlarmNative", "Default ringtone failed", e); }
    }

    private void startVibration() {
        try {
            vibrator = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (vibrator != null && vibrator.hasVibrator()) {
                if (Build.VERSION.SDK_INT >= 26) vibrator.vibrate(VibrationEffect.createWaveform(new long[]{0, 550, 250}, 0));
                else vibrator.vibrate(new long[]{0, 550, 250}, 0);
            }
        } catch (Throwable e) { android.util.Log.w("RedAlarmNative", "Vibration unavailable", e); }
    }

    private void stopCurrentPlayback() {
        try { if (player != null) { try { if (player.isPlaying()) player.stop(); } catch (Throwable ignored) { } player.release(); } }
        catch (Throwable ignored) { }
        player = null;
        try { if (vibrator != null) vibrator.cancel(); } catch (Throwable ignored) { }
        vibrator = null;
        try { if (wakeLock != null && wakeLock.isHeld()) wakeLock.release(); } catch (Throwable ignored) { }
        wakeLock = null;
    }

    private void stopAndFinish() {
        handler.removeCallbacks(timeout);
        stopCurrentPlayback();
        getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                .putBoolean("ringing:" + alarmId, false).remove("ringing_id").apply();
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(NOTIFICATION_ID);
        try { stopForeground(true); } catch (Throwable ignored) { }
        stopSelf();
        RedAlarmNativeBridge.refreshNextAlarm(this);
    }

    @Override public void onDestroy() {
        session++;
        handler.removeCallbacksAndMessages(null);
        stopCurrentPlayback();
        if (!TextUtils.isEmpty(alarmId)) {
            getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                    .putBoolean("ringing:" + alarmId, false).remove("ringing_id").apply();
        }
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(NOTIFICATION_ID);
        super.onDestroy();
    }
}
'''

BOOT_RECEIVER_JAVA = r'''package org.kivy.android;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Restores saved native AlarmManager entries without launching the Kivy UI. */
public class KivyAlarmReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null || intent.getAction() == null) return;
        String action = intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(action)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                || Intent.ACTION_TIME_CHANGED.equals(action)
                || Intent.ACTION_TIMEZONE_CHANGED.equals(action)) {
            try {
                org.yashtech.redalarm.RedAlarmNativeBridge.restoreOnBoot(context);
            } catch (Throwable e) {
                android.util.Log.e("RedAlarmNative", "Boot/time-change alarm recovery failed", e);
            }
        }
    }
}
'''


APPLICATION_JAVA = r'''package org.yashtech.redalarm;

import android.app.Activity;
import android.app.Application;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

/** Applies lock-screen flags for an actual ringing session, including warm
 * Activities reused through singleTask/onNewIntent. Ordinary screens stay below keyguard. */
public class RedAlarmApplication extends Application {
    private static final String PREFS = "redalarm_native_alarms_v1";
    @Override public void onCreate() {
        super.onCreate();
        registerActivityLifecycleCallbacks(new ActivityLifecycleCallbacks() {
            private void apply(Activity activity, boolean show) {
                try {
                    if (Build.VERSION.SDK_INT >= 27) {
                        activity.setShowWhenLocked(show);
                        activity.setTurnScreenOn(show);
                    }
                    if (show) {
                        activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    } else {
                        activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    }
                } catch (Throwable ignored) { }
            }
            private boolean nativeRinging() {
                try {
                    SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
                    String id = p.getString("ringing_id", "");
                    return id != null && !id.isEmpty();
                } catch (Throwable ignored) { return false; }
            }
            @Override public void onActivityCreated(Activity activity, Bundle state) {
                try {
                    Intent i = activity.getIntent();
                    String id = i == null ? null : i.getStringExtra("alarm_id");
                    String action = i == null ? null : i.getStringExtra("action_kind");
                    apply(activity, id != null && action == null);
                } catch (Throwable ignored) { apply(activity, false); }
            }
            @Override public void onActivityStarted(Activity activity) { }
            @Override public void onActivityResumed(Activity activity) { apply(activity, nativeRinging()); }
            @Override public void onActivityPaused(Activity activity) { }
            @Override public void onActivityStopped(Activity activity) { }
            @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) { }
            @Override public void onActivityDestroyed(Activity activity) { }
        });
    }
}
'''

MANIFEST_HOOK = r'''"""Register RedAlarm's native alarm receiver and foreground ringing service."""
from pathlib import Path
import re


def after_apk_build(toolchain):
    dist = getattr(getattr(toolchain, "_dist", None), "dist_dir", None)
    if not dist:
        raise RuntimeError("python-for-android hook did not expose toolchain._dist.dist_dir")
    manifest = Path(dist) / "src" / "main" / "AndroidManifest.xml"
    if not manifest.is_file():
        raise RuntimeError("Generated AndroidManifest.xml was not found: " + str(manifest))
    text = manifest.read_text(encoding="utf-8")
    app = re.search(r"<application\b[^>]*>", text, flags=re.DOTALL)
    if app is None:
        raise RuntimeError("Could not find <application> in " + str(manifest))

    # Remove any previous versions of only the components owned by this hook,
    # then insert one canonical copy. This also repairs old manifests when p4a
    # reuses a build distribution.
    owned = [
        ("receiver", "org.kivy.android.KivyAlarmReceiver"),
        ("receiver", "org.yashtech.redalarm.RedAlarmAlarmReceiver"),
        ("service", "org.yashtech.redalarm.RedAlarmRingingService"),
    ]
    for tag, name in owned:
        pattern = re.compile(r"\s*<" + tag + r"\b(?=[^>]*android:name=[\"']" + re.escape(name) + r"[\"'])[^>]*(?:/>|>.*?</" + tag + r"\s*>)", re.DOTALL)
        text = pattern.sub("", text)
    app = re.search(r"<application\b[^>]*>", text, flags=re.DOTALL)
    components = """
        <receiver android:name="org.kivy.android.KivyAlarmReceiver" android:enabled="true" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
                <action android:name="android.intent.action.TIME_SET" />
                <action android:name="android.intent.action.TIMEZONE_CHANGED" />
            </intent-filter>
        </receiver>
        <receiver android:name="org.yashtech.redalarm.RedAlarmAlarmReceiver" android:enabled="true" android:exported="false" />
        <service android:name="org.yashtech.redalarm.RedAlarmRingingService" android:enabled="true" android:exported="false" android:foregroundServiceType="mediaPlayback" />
"""
    text = text[:app.end()] + components + text[app.end():]
    manifest.write_text(text, encoding="utf-8")
    print("[RedAlarm] Registered boot recovery, native alarm receiver, and media-playback foreground service")
'''


def apply_main() -> None:
    path = ROOT / "main.py"
    src = path.read_text(encoding="utf-8")
    schedule_start = src.index("    def android_schedule_alarm(")
    cancel_start = src.index("    def android_cancel_alarm(", schedule_start)
    src = src[:schedule_start] + r'''    def android_schedule_alarm(alarm_id, trigger_dt, salt="", alarm=None, store_path=""):
        """Schedule through native BroadcastReceiver; Python/Kivy need not be awake."""
        request_code = stable_request_code(alarm_id, salt)
        fire_token = int(trigger_dt.timestamp() * 1000)
        app = App.get_running_app()
        config = dict(alarm or {})
        if app is not None:
            if not store_path:
                store_path = getattr(getattr(app, "store", None), "path", "")
            try:
                cache_dir = getattr(app, "ringtone_cache_dir", "")
                resolved = resolve_ringtone_for_playback(config.get("sound_path", ""), cache_dir)
                if resolved and os.path.isfile(resolved):
                    config["native_sound_path"] = resolved
            except Exception as exc:
                print("[RedAlarm] native ringtone path preparation failed:", exc)
            config["native_fallback_path"] = getattr(app, "default_ringtone_path", "")
        config["id"] = str(alarm_id)
        if not config:
            config = {"id": str(alarm_id), "enabled": True, "hour": trigger_dt.hour,
                      "minute": trigger_dt.minute, "days": [False] * 7}
        try:
            context = _activity().getApplicationContext()
            # Clear a pre-patch Activity PendingIntent with the same identity.
            try:
                _alarm_manager().cancel(_alarm_pending_intent(alarm_id, request_code, fire_token))
            except Exception:
                pass
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            Bridge.scheduleAlarm(
                context, JString(str(alarm_id)), JString(json.dumps(config, ensure_ascii=False)),
                JString(str(store_path or "")), int(fire_token), bool(salt == "snooze")
            )
        except Exception as exc:
            # Legacy fallback keeps compatibility if the native bridge could not be loaded.
            print("[RedAlarm] native scheduler unavailable; using legacy Activity alarm:", exc)
            pending_intent = _alarm_pending_intent(alarm_id, request_code, fire_token)
            info = AlarmClockInfo(fire_token, pending_intent)
            _alarm_manager().setAlarmClock(info, pending_intent)

''' + src[cancel_start:]
    cancel_start = src.index("    def android_cancel_alarm(")
    next_start = src.index("    def android_can_schedule_exact_alarms(", cancel_start)
    src = src[:cancel_start] + r'''    def android_cancel_alarm(alarm_id, salt=""):
        request_code = stable_request_code(alarm_id, salt)
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            Bridge.cancelAlarm(_activity().getApplicationContext(), JString(str(alarm_id)), bool(salt == "snooze"))
        except Exception as exc:
            print("[RedAlarm] native alarm cancellation failed:", exc)
        # Also cancel any legacy Activity-based PendingIntent left by an older APK.
        try:
            pending_intent = _alarm_pending_intent(alarm_id, request_code)
            _alarm_manager().cancel(pending_intent)
        except Exception:
            pass

    def android_native_ring_is_active(alarm_id):
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            return bool(Bridge.isRinging(_activity().getApplicationContext(), JString(str(alarm_id))))
        except Exception as exc:
            print("[RedAlarm] native ring status unavailable:", exc)
            return False

    def android_stop_native_ring_service(alarm_id=""):
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            Bridge.stopRinging(_activity().getApplicationContext(), JString(str(alarm_id or "")))
        except Exception as exc:
            print("[RedAlarm] native ring service stop failed:", exc)

    def android_any_native_ring_active():
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            return bool(Bridge.isAnyRinging(_activity().getApplicationContext()))
        except Exception:
            return False

    def android_native_fire_recently(alarm_id):
        try:
            Bridge = autoclass("org.yashtech.redalarm.RedAlarmNativeBridge")
            return bool(Bridge.hasRecentNativeFire(_activity().getApplicationContext(), JString(str(alarm_id))))
        except Exception:
            return False

''' + src[next_start:]

    # Route regular alarm and snooze schedules through the native bridge with full data.
    src = replace_once(src,
        '            android_schedule_alarm(alarm["id"], trigger_dt, salt="")',
        '            app = App.get_running_app()\n            store_path = getattr(getattr(app, "store", None), "path", "")\n            android_schedule_alarm(alarm["id"], trigger_dt, salt="", alarm=alarm, store_path=store_path)',
        "AlarmScheduler.schedule native bridge")
    src = replace_once(src,
        '            android_schedule_alarm(alarm["id"], trigger_dt, salt="snooze")',
        '            app = App.get_running_app()\n            store_path = getattr(getattr(app, "store", None), "path", "")\n            android_schedule_alarm(alarm["id"], trigger_dt, salt="snooze", alarm=alarm, store_path=store_path)',
        "AlarmScheduler.schedule_snooze native bridge")

    # Native service owns ringtone/vibration; the Kivy activity only draws the alarm UI.
    src = replace_once(src,
'''        if ANDROID:
            try:
                android_acquire_wake_lock()
                android_show_over_lockscreen(True)
            except Exception as exc:
                print("[RedAlarm] wake/lockscreen error:", exc)
            try:
                android_show_ring_notification(
                    alarm["id"], self.label_text, self.time_text
                )
            except Exception as exc:
                print("[RedAlarm] full-screen notification error:", exc)
            if alarm.get("vibrate", False):
                try:
                    android_vibrate_start()
                    print("[RedAlarm] ring: vibration started")
                except Exception as exc:
                    print("[RedAlarm] vibration start error:", exc)
''',
'''        native_playback = False
        if ANDROID:
            try:
                native_playback = android_native_ring_is_active(alarm["id"])
            except Exception:
                native_playback = False
            try:
                android_acquire_wake_lock()
                android_show_over_lockscreen(True)
            except Exception as exc:
                print("[RedAlarm] wake/lockscreen error:", exc)
            # The native service already posts its own full-screen notification.
            # Do not replace it with a second Activity-owned notification.
            if not native_playback:
                try:
                    android_show_ring_notification(alarm["id"], self.label_text, self.time_text)
                except Exception as exc:
                    print("[RedAlarm] full-screen notification error:", exc)
            if alarm.get("vibrate", False) and not native_playback:
                try:
                    android_vibrate_start()
                    print("[RedAlarm] ring: vibration started")
                except Exception as exc:
                    print("[RedAlarm] vibration start error:", exc)
''', "AlarmRingScreen native foreground service integration")

    src = replace_once(src,
'''        sound = load_and_play(path, loop=True, volume=ring_volume) if path else None
        if sound is None and path != app.default_ringtone_path:
            print("[RedAlarm] ring: chosen sound failed, falling back to default beep")
            sound = load_and_play(app.default_ringtone_path, loop=True, volume=ring_volume)
        self._sound = sound
        if sound is None:
            print("[RedAlarm] ring: NO sound could be started (not even the default)")
''',
'''        # On Android the exact-alarm receiver starts a native media-playback
        # foreground service before it asks the Activity to draw this screen.
        # That service keeps audio alive if Kivy's clock pauses on the lock screen.
        if ANDROID and native_playback:
            sound = None
            print("[RedAlarm] ring: native foreground service owns playback")
        else:
            sound = load_and_play(path, loop=True, volume=ring_volume) if path else None
            if sound is None and path != app.default_ringtone_path:
                print("[RedAlarm] ring: chosen sound failed, falling back to default beep")
                sound = load_and_play(app.default_ringtone_path, loop=True, volume=ring_volume)
        self._sound = sound
        if sound is None and not (ANDROID and native_playback):
            print("[RedAlarm] ring: NO sound could be started (not even the default)")
''', "prevent duplicate Kivy audio")

    src = replace_once(src,
'''        if ANDROID:
            try:
                android_show_over_lockscreen(False)
                android_release_wake_lock()
            except Exception as exc:
                print("[RedAlarm] wake/lockscreen release error:", exc)
            try:
                android_vibrate_stop()
            except Exception as exc:
                print("[RedAlarm] vibration stop error:", exc)
            if cancel_notification:
                try:
                    android_cancel_ring_notification()
                except Exception as exc:
                    print("[RedAlarm] full-screen notification cancel error:", exc)
''',
'''        if ANDROID:
            # Stop only the native service owned by this RingScreen. On a new
            # alarm launch, an older screen's cleanup must not kill the fresh
            # service or remove its notification/vibration.
            try:
                if self.alarm_id:
                    android_stop_native_ring_service(self.alarm_id)
            except Exception as exc:
                print("[RedAlarm] native ringing service stop error:", exc)
            native_still_ringing = android_any_native_ring_active()
            if not native_still_ringing:
                try:
                    android_show_over_lockscreen(False)
                    android_release_wake_lock()
                except Exception as exc:
                    print("[RedAlarm] wake/lockscreen release error:", exc)
                try:
                    android_vibrate_stop()
                except Exception as exc:
                    print("[RedAlarm] vibration stop error:", exc)
                if cancel_notification:
                    try:
                        android_cancel_ring_notification()
                    except Exception as exc:
                        print("[RedAlarm] full-screen notification cancel error:", exc)
''', "ring stop service lifecycle")

    # For cold-start notification actions, stop native audio as soon as Python receives action.
    src = replace_once(src,
'''            else:
                # Handle notification actions even if Android recreated the process.
                alarm = self.store.get(alarm_id)
''',
'''            else:
                if ANDROID:
                    android_stop_native_ring_service(alarm_id)
                # Handle notification actions even if Android recreated the process.
                alarm = self.store.get(alarm_id)
''', "cold dismiss action")
    src = replace_once(src,
'''                    self.scheduler.schedule_snooze(alarm, next_trigger)
                    ring._keep_snooze_notification = True
                    if ANDROID:
                        android_show_snoozed_notification(alarm_id, next_trigger)
''',
'''                    self.scheduler.schedule_snooze(alarm, next_trigger)
                    ring._keep_snooze_notification = True
                    if ANDROID:
                        android_stop_native_ring_service(alarm_id)
                        android_show_snoozed_notification(alarm_id, next_trigger)
''', "cold snooze action")

    # Allow the already-fired native service to show a one-time alarm after the
    # receiver has correctly disabled its persisted schedule.
    src = replace_once(src,
'''    def handle_alarm_fired(self, alarm_id):
        alarm = self.store.get(alarm_id)
        if not alarm or not alarm.get("enabled", True):
            return
''',
'''    def handle_alarm_fired(self, alarm_id):
        alarm = self.store.get(alarm_id)
        native_ring_active = False
        if ANDROID and alarm:
            try:
                native_ring_active = android_native_ring_is_active(alarm_id)
            except Exception:
                native_ring_active = False
        if not alarm:
            return
        if ANDROID and not native_ring_active:
            try:
                if android_native_fire_recently(alarm_id):
                    # The native service already rang and auto-dismissed while
                    # Kivy was asleep. Do not replay late on unlock. Reconcile
                    # the in-memory store with native one-shot completion.
                    if any(alarm.get("days") or []) and alarm.get("enabled", True):
                        self.scheduler.schedule(
                            alarm, now=datetime.datetime.now() + datetime.timedelta(seconds=30)
                        )
                    else:
                        if not any(alarm.get("days") or []):
                            alarm["enabled"] = False
                            self.store.put(alarm)
                        self.scheduler.cancel(alarm)
                        self.scheduler.cancel_snooze(alarm)
                    self._refresh_next_alarm_notification()
                    return
            except Exception as exc:
                print("[RedAlarm] could not reconcile delayed native alarm:", exc)
        if not alarm.get("enabled", True) and not native_ring_active:
            return
''', "one-time native fire dispatch")

    # Android background/lock must never trigger Kivy cleanup that shuts down the ring.
    src = replace_once(src,
'''    def on_stop(self):
        if self._ready:
            ring = self.root.get_screen("ring")
            ring._stop_common(
                cancel_notification=not ring._keep_snooze_notification
            )
''',
'''    def on_stop(self):
        if not self._ready:
            return
        if ANDROID:
            # Android may call this when the Activity is backgrounded/locked or
            # the UI process is reclaimed. Native AlarmManager + foreground
            # ringing service own delivery and playback; never cancel them here.
            return
        ring = self.root.get_screen("ring")
        ring._stop_common(cancel_notification=not ring._keep_snooze_notification)
''', "Android on_stop must not kill ring")

    path.write_text(src, encoding="utf-8")


def apply_spec() -> None:
    path = ROOT / "buildozer.spec"
    src = path.read_text(encoding="utf-8")
    line = next((l for l in src.splitlines() if l.strip().startswith("android.permissions =")), None)
    if line is None: fail("Could not find android.permissions line")
    permissions = line.split("=", 1)[1].strip().split(",")
    for needed in ("FOREGROUND_SERVICE", "FOREGROUND_SERVICE_MEDIA_PLAYBACK"):
        if needed not in permissions: permissions.append(needed)
    new_line = "android.permissions = " + ",".join(permissions)
    src = replace_once(src, line, new_line, "foreground service permissions")
    path.write_text(src, encoding="utf-8")


def apply_workflow() -> None:
    path = ROOT / ".github/workflows/build.yml"
    src = path.read_text(encoding="utf-8")
    old = "      - yashh-tech-patch-2"
    if "      - fix/android-background-ringing" not in src:
        src = replace_once(src, old, old + "\n      - fix/android-background-ringing", "enable CI build for fix branch")
    path.write_text(src, encoding="utf-8")


def remove_cancel_button() -> None:
    path = ROOT / "main.py"
    src = path.read_text(encoding="utf-8")
    old = '''        def cancel_review(_button=None):
            self.cancel_confirmation(popup)

        # Cancel returns to settings and preserves the in-memory form; it does
        # not reach the commit/scheduling path.
        content.add_widget(RoundedActionButton("CANCEL", callback=cancel_review, accent=False,
                                               size_hint_y=None, height=dp(44)))
'''
    src = replace_once(src, old, "", "remove unreliable confirmation CANCEL button")
    path.write_text(src, encoding="utf-8")


def main() -> None:
    ensure_repo_and_branch()
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT.parent / (ROOT.name + "-backup-before-native-alarm-patch-" + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    for rel in ("main.py", "buildozer.spec", "java_src/manifest_hook.py",
                "java_src/KivyAlarmReceiver.java", "android_src/org/yashtech/redalarm/RedAlarmApplication.java", "redalarm_timepicker.py", ".github/workflows/build.yml"):
        dest = backup / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    print("Safety backup:", backup)

    try:
        # Create native Android implementation.
        write_text("android_src/org/yashtech/redalarm/RedAlarmNativeBridge.java", BRIDGE_JAVA)
        write_text("android_src/org/yashtech/redalarm/RedAlarmAlarmReceiver.java", RECEIVER_JAVA)
        write_text("android_src/org/yashtech/redalarm/RedAlarmRingingService.java", RING_SERVICE_JAVA)
        write_text("android_src/org/yashtech/redalarm/RedAlarmApplication.java", APPLICATION_JAVA)
        write_text("java_src/KivyAlarmReceiver.java", BOOT_RECEIVER_JAVA)
        write_text("java_src/manifest_hook.py", MANIFEST_HOOK)
        apply_main()
        apply_spec()
        apply_workflow()
        remove_cancel_button()

        print("\nRunning Python syntax checks...")
        py_files = ["main.py", "redalarm_timepicker.py", "java_src/manifest_hook.py"]
        result = run(sys.executable, "-m", "py_compile", *py_files, check=False)
        if result.returncode:
            # Restore source files from backup; keep branch for easier inspection.
            for rel in ("main.py", "buildozer.spec", "java_src/manifest_hook.py", "java_src/KivyAlarmReceiver.java", "android_src/org/yashtech/redalarm/RedAlarmApplication.java", "redalarm_timepicker.py", ".github/workflows/build.yml"):
                shutil.copy2(backup / rel, ROOT / rel)
            for rel in ("android_src/org/yashtech/redalarm/RedAlarmNativeBridge.java",
                        "android_src/org/yashtech/redalarm/RedAlarmAlarmReceiver.java",
                        "android_src/org/yashtech/redalarm/RedAlarmRingingService.java"):
                try: (ROOT / rel).unlink()
                except OSError: pass
            fail("Python syntax validation failed; original files restored from the backup.\n" + result.stdout)
        print(result.stdout.strip() or "Python syntax checks passed.")

        print("\nChecking whitespace and displaying changed files...")
        diffcheck = run("git", "diff", "--check", check=False)
        if diffcheck.returncode:
            print(diffcheck.stdout)
            fail("git diff --check failed. Review before committing.")
        print(run("git", "status", "--short").stdout)
        print("\nPatch applied locally only. No commit or push was performed.")
        print("Next: run `python validate_redalarm_timepicker_integration.py`, then `buildozer -v android debug` or use your GitHub Actions build.")
        print("After a successful test, commit and push: git add main.py buildozer.spec java_src android_src .github/workflows/build.yml && git commit -m \"Fix Android background alarm delivery and reboot recovery\" && git push -u origin fix/android-background-ringing")
    except BaseException:
        # Do not leave a half-installed native alarm patch if any anchor or
        # validation step fails. Restore every pre-existing file from backup.
        for rel in ("main.py", "buildozer.spec", "java_src/manifest_hook.py",
                    "java_src/KivyAlarmReceiver.java",
                    "android_src/org/yashtech/redalarm/RedAlarmApplication.java",
                    "redalarm_timepicker.py", ".github/workflows/build.yml"):
            saved = backup / rel
            if saved.exists():
                shutil.copy2(saved, ROOT / rel)
        for rel in ("android_src/org/yashtech/redalarm/RedAlarmNativeBridge.java",
                    "android_src/org/yashtech/redalarm/RedAlarmAlarmReceiver.java",
                    "android_src/org/yashtech/redalarm/RedAlarmRingingService.java"):
            try:
                (ROOT / rel).unlink()
            except OSError:
                pass
        raise


if __name__ == "__main__":
    main()
