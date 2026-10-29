#!/usr/bin/env python3
"""Safely patch RedAlarm lock-screen behavior and Alarm List header alignment.

Upload this file into the RedAlarm Codespaces workspace and run it from the
repository root on branch fix/spinner-cancel-touch. It leaves the time-picker
UI untouched. It creates a native, minimal ringing Activity and routes native
Dismiss/Snooze actions away from PythonActivity.
"""
from __future__ import annotations

import datetime
import pathlib
import re
import subprocess
import sys

TARGET_BRANCH = "fix/spinner-cancel-touch"
NATIVE_ROOT = pathlib.Path("android_src/org/yashtech/redalarm")
FILES_TO_BACK_UP = [
    pathlib.Path("main.py"),
    pathlib.Path("alarm.kv"),
    pathlib.Path("java_src/manifest_hook.py"),
    NATIVE_ROOT / "RedAlarmApplication.java",
    NATIVE_ROOT / "RedAlarmNativeBridge.java",
    NATIVE_ROOT / "RedAlarmAlarmReceiver.java",
    NATIVE_ROOT / "RedAlarmRingingService.java",
    NATIVE_ROOT / "RedAlarmRingActivity.java",
]


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return (result.stdout or "").strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one matching block, found {count}; no source files written")
    return text.replace(old, new, 1)


def replace_region(text: str, start: str, end: str, replacement: str, label: str) -> str:
    if text.count(start) != 1:
        raise RuntimeError(f"{label}: expected one start marker; no source files written")
    a = text.index(start)
    b = text.find(end, a + len(start))
    if b < 0:
        raise RuntimeError(f"{label}: end marker missing; no source files written")
    return text[:a] + replacement + text[b:]


def ensure_java_import(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    return replace_once(text, old, new, label)


def main() -> int:
    root = pathlib.Path(git("rev-parse", "--show-toplevel"))
    branch = git("branch", "--show-current")
    if branch != TARGET_BRANCH:
        raise RuntimeError(f"You are on {branch!r}; switch to {TARGET_BRANCH!r} first")
    if subprocess.run(["git", "diff", "--quiet"], cwd=root).returncode:
        raise RuntimeError("Tracked changes exist. Commit or stash them before applying this patch")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root).returncode:
        raise RuntimeError("Staged changes exist. Commit or unstage them before applying this patch")

    def read(rel: pathlib.Path | str) -> str:
        return (root / rel).read_text(encoding="utf-8")

    # Refuse reruns rather than accidentally applying the transformations twice.
    activity_path = root / NATIVE_ROOT / "RedAlarmRingActivity.java"
    if activity_path.exists() and "class RedAlarmRingActivity" in activity_path.read_text(encoding="utf-8"):
        raise RuntimeError("RedAlarmRingActivity already exists. This patch appears applied; inspect git diff/status")

    main_py = read("main.py")
    kv = read("alarm.kv")
    hook = read("java_src/manifest_hook.py")
    bridge = read(NATIVE_ROOT / "RedAlarmNativeBridge.java")
    receiver = read(NATIVE_ROOT / "RedAlarmAlarmReceiver.java")
    service = read(NATIVE_ROOT / "RedAlarmRingingService.java")

    # --- Alarm List header: stable 56dp row, true centered title, matched button heights,
    #     and remove the unsupported left-arrow glyph that showed as a tofu box. ---
    old_header = '''        BoxLayout:
            size_hint_y: None
            height: "48dp"

            HomeButton:
                text: "←  BACK"
                font_size: "12sp"
                size_hint: None, None
                size: "96dp", "42dp"
                bg_color: 0.085, 0.075, 0.075, 1
                text_color: COL_TEXT
                on_release: root.go_home()

            Label:
                text: "Alarms"
                font_size: "30sp"
                bold: True
                color: COL_TEXT
                halign: "left"
                valign: "middle"
                text_size: self.size

            HomeButton:
                text: "+"
                font_size: "24sp"
                size_hint: None, None
                size: "48dp", "48dp"
                bg_color: COL_RED
                text_color: 1, 1, 1, 1
                on_release: root.open_new_alarm()
'''
    new_header = '''        FloatLayout:
            size_hint_y: None
            height: dp(56)

            HomeButton:
                text: "BACK"
                font_size: "13sp"
                size_hint: None, None
                size: dp(82), dp(48)
                pos_hint: {"x": 0, "center_y": 0.5}
                bg_color: 0.085, 0.075, 0.075, 1
                text_color: COL_TEXT
                on_release: root.go_home()

            Label:
                text: "Alarms"
                font_size: "27sp"
                bold: True
                color: COL_TEXT
                size_hint: None, None
                size: dp(170), dp(48)
                pos_hint: {"center_x": 0.5, "center_y": 0.5}
                halign: "center"
                valign: "middle"
                text_size: self.size

            HomeButton:
                text: "+"
                font_size: "24sp"
                size_hint: None, None
                size: dp(48), dp(48)
                pos_hint: {"right": 1, "center_y": 0.5}
                bg_color: COL_RED
                text_color: 1, 1, 1, 1
                on_release: root.open_new_alarm()
'''
    kv = replace_once(kv, old_header, new_header, "Alarm List header alignment")

    # --- Bridge action methods: Dismiss/Snooze are native and do not reopen PythonActivity. ---
    bridge = ensure_java_import(
        bridge, "import android.app.AlarmManager;\n",
        "import android.app.ActivityManager;\nimport android.app.AlarmManager;\n",
        "native bridge ActivityManager import",
    )
    bridge = ensure_java_import(
        bridge, "import android.content.Context;\n",
        "import android.content.ComponentName;\nimport android.content.Context;\n",
        "native bridge ComponentName import",
    )
    native_action_methods = r'''
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

'''
    bridge = replace_once(
        bridge,
        "    static String getConfig(Context context, String alarmId) {\n",
        native_action_methods + "    static String getConfig(Context context, String alarmId) {\n",
        "native ring actions insertion",
    )

    # --- Alarm receiver: notification action intents go straight to native bridge. ---
    old_receiver_start = '''        String id = intent.getStringExtra("alarm_id");
        String kind = intent.getStringExtra("alarm_kind");
        if (TextUtils.isEmpty(id)) return;
'''
    new_receiver_start = '''        String id = intent.getStringExtra("alarm_id");
        String ringAction = intent.getStringExtra("ring_action");
        if (!TextUtils.isEmpty(ringAction)) {
            if ("dismiss".equals(ringAction) || "snooze".equals(ringAction)) {
                RedAlarmNativeBridge.performRingAction(context, id, ringAction);
            }
            return;
        }
        String kind = intent.getStringExtra("alarm_kind");
        if (TextUtils.isEmpty(id)) return;
'''
    receiver = replace_once(receiver, old_receiver_start, new_receiver_start, "native ring action receiver")
    receiver = replace_once(
        receiver,
        "        Intent service = new Intent(context, RedAlarmRingingService.class);\n",
        "        RedAlarmNativeBridge.closeNormalAppTasks(context);\n"
        "        Intent service = new Intent(context, RedAlarmRingingService.class);\n",
        "close normal app task on alarm fire",
    )

    # --- Ring service: full-screen intent is the native ring-only screen; actions are broadcasts. ---
    service = replace_once(
        service,
        "Intent open = new Intent(this, org.kivy.android.PythonActivity.class);",
        "Intent open = new Intent(this, RedAlarmRingActivity.class);",
        "ring service full-screen target",
    )
    new_action_method = r'''    private PendingIntent actionPendingIntent(String id, String kind) {
        Intent intent = new Intent(this, RedAlarmAlarmReceiver.class);
        intent.setAction("org.yashtech.redalarm.RING_ACTION");
        intent.putExtra("alarm_id", id);
        intent.putExtra("ring_action", kind);
        return PendingIntent.getBroadcast(this,
                RedAlarmNativeBridge.requestCode(id, "service_notif_" + kind),
                intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

'''
    service = replace_region(
        service,
        "    private PendingIntent actionPendingIntent(String id, String kind) {",
        "    private void acquireWakeLock(int seconds) {",
        new_action_method,
        "native ring notification action",
    )
    finish_helper = r'''    private void notifyRingFinished() {
        if (TextUtils.isEmpty(alarmId)) return;
        Intent finished = new Intent(RedAlarmRingActivity.ACTION_RING_FINISHED);
        finished.setPackage(getPackageName());
        finished.putExtra("alarm_id", alarmId);
        sendBroadcast(finished);
    }

'''
    service = replace_once(
        service,
        "    private void stopAndFinish() {\n",
        finish_helper + "    private void stopAndFinish() {\n",
        "ring service finish broadcast helper",
    )
    service = replace_once(
        service,
        '''        getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                .putBoolean("ringing:" + alarmId, false).remove("ringing_id").apply();
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
''',
        '''        getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                .putBoolean("ringing:" + alarmId, false).remove("ringing_id").apply();
        notifyRingFinished();
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
''',
        "ring service timeout finish event",
    )

    # --- Native ring-only Activity. Normal Home/List/Editor never get lockscreen flags. ---
    ring_activity = r'''package org.yashtech.redalarm;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONException;
import org.json.JSONObject;

/** A minimal full-screen alarm UI. It never exposes Home, settings, or alarm editing. */
public final class RedAlarmRingActivity extends Activity {
    public static final String ACTION_RING_FINISHED = "org.yashtech.redalarm.RING_FINISHED";
    private String alarmId = "";
    private boolean receiverRegistered = false;

    private final BroadcastReceiver finishedReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (intent == null || !ACTION_RING_FINISHED.equals(intent.getAction())) return;
            String finishedId = intent.getStringExtra("alarm_id");
            if (TextUtils.isEmpty(finishedId) || finishedId.equals(alarmId)) finishAndRemoveTask();
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        alarmId = getIntent() == null ? "" : getIntent().getStringExtra("alarm_id");
        if (TextUtils.isEmpty(alarmId) || !RedAlarmNativeBridge.isRinging(this, alarmId)) {
            finishAndRemoveTask();
            return;
        }
        applyRingWindowFlags();
        showRingOnlyUi();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        alarmId = intent == null ? "" : intent.getStringExtra("alarm_id");
        if (TextUtils.isEmpty(alarmId) || !RedAlarmNativeBridge.isRinging(this, alarmId)) {
            finishAndRemoveTask();
            return;
        }
        showRingOnlyUi();
    }

    private void applyRingWindowFlags() {
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        }
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
    }

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void showRingOnlyUi() {
        String label = "Alarm";
        int hour = 7;
        int minute = 0;
        try {
            String raw = RedAlarmNativeBridge.getConfig(this, alarmId);
            if (!TextUtils.isEmpty(raw)) {
                JSONObject config = new JSONObject(raw);
                label = config.optString("label", "Alarm").trim();
                if (label.isEmpty()) label = "Alarm";
                hour = Math.max(0, Math.min(23, config.optInt("hour", 7)));
                minute = Math.max(0, Math.min(59, config.optInt("minute", 0)));
            }
        } catch (JSONException e) {
            android.util.Log.e("RedAlarmNative", "Could not read ring screen settings", e);
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(28), dp(28), dp(28), dp(28));
        root.setBackgroundColor(Color.rgb(8, 8, 10));

        TextView heading = new TextView(this);
        heading.setText("ALARM");
        heading.setTextColor(Color.rgb(190, 40, 40));
        heading.setTextSize(14);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        heading.setGravity(Gravity.CENTER);
        root.addView(heading, new LinearLayout.LayoutParams(-1, dp(32)));

        TextView labelView = new TextView(this);
        labelView.setText(label);
        labelView.setTextColor(Color.WHITE);
        labelView.setTextSize(23);
        labelView.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        labelView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams labelParams = new LinearLayout.LayoutParams(-1, dp(54));
        labelParams.bottomMargin = dp(12);
        root.addView(labelView, labelParams);

        int hour12 = hour % 12 == 0 ? 12 : hour % 12;
        TextView timeView = new TextView(this);
        timeView.setText(hour12 + ":" + String.format(java.util.Locale.getDefault(), "%02d", minute)
                + (hour >= 12 ? " PM" : " AM"));
        timeView.setTextColor(Color.WHITE);
        timeView.setTextSize(58);
        timeView.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        timeView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams timeParams = new LinearLayout.LayoutParams(-1, dp(100));
        timeParams.bottomMargin = dp(30);
        root.addView(timeView, timeParams);

        Button snooze = makeButton("Snooze", Color.rgb(48, 48, 53));
        snooze.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { takeAction("snooze"); }
        });
        LinearLayout.LayoutParams snoozeParams = new LinearLayout.LayoutParams(-1, dp(62));
        snoozeParams.bottomMargin = dp(14);
        root.addView(snooze, snoozeParams);

        Button dismiss = makeButton("Dismiss", Color.rgb(156, 12, 12));
        dismiss.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { takeAction("dismiss"); }
        });
        root.addView(dismiss, new LinearLayout.LayoutParams(-1, dp(62)));
        setContentView(root);
    }

    private Button makeButton(String title, int color) {
        Button button = new Button(this);
        button.setText(title);
        button.setTextColor(Color.WHITE);
        button.setTextSize(17);
        button.setAllCaps(false);
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(18));
        button.setBackground(shape);
        return button;
    }

    private void takeAction(String kind) {
        if (!TextUtils.isEmpty(alarmId)) {
            RedAlarmNativeBridge.performRingAction(getApplicationContext(), alarmId, kind);
        }
        finishAndRemoveTask();
    }

    @Override protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter(ACTION_RING_FINISHED);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(finishedReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(finishedReceiver, filter);
        receiverRegistered = true;
        if (TextUtils.isEmpty(alarmId) || !RedAlarmNativeBridge.isRinging(this, alarmId)) finishAndRemoveTask();
    }

    @Override protected void onStop() {
        if (receiverRegistered) {
            try { unregisterReceiver(finishedReceiver); } catch (Throwable ignored) { }
            receiverRegistered = false;
        }
        super.onStop();
    }

    @Override public void onBackPressed() {
        // Use Dismiss or Snooze; Back must not silently stop the alarm.
    }
}
'''

    # --- Only RedAlarmRingActivity can show over the keyguard. ---
    app_java = r'''package org.yashtech.redalarm;

import android.app.Activity;
import android.app.Application;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

/** Keep all normal RedAlarm screens below the lockscreen. */
public class RedAlarmApplication extends Application {
    @Override public void onCreate() {
        super.onCreate();
        registerActivityLifecycleCallbacks(new ActivityLifecycleCallbacks() {
            private void apply(Activity activity, boolean shouldShow) {
                boolean allow = shouldShow && activity instanceof RedAlarmRingActivity;
                try {
                    if (Build.VERSION.SDK_INT >= 27) {
                        activity.setShowWhenLocked(allow);
                        activity.setTurnScreenOn(allow);
                    }
                    if (allow) {
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

            private boolean ringing(Activity activity) {
                if (!(activity instanceof RedAlarmRingActivity)) return false;
                try {
                    String id = activity.getIntent() == null ? null
                            : activity.getIntent().getStringExtra("alarm_id");
                    return id != null && RedAlarmNativeBridge.isRinging(activity, id);
                } catch (Throwable ignored) { return false; }
            }

            @Override public void onActivityCreated(Activity activity, Bundle state) { apply(activity, ringing(activity)); }
            @Override public void onActivityResumed(Activity activity) { apply(activity, ringing(activity)); }
            @Override public void onActivityStarted(Activity activity) { }
            @Override public void onActivityPaused(Activity activity) { }
            @Override public void onActivityStopped(Activity activity) { }
            @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) { }
            @Override public void onActivityDestroyed(Activity activity) { }
        });
    }
}
'''

    # --- Register the new activity in python-for-android's generated manifest. ---
    if "RedAlarmRingActivity" in hook:
        raise RuntimeError("Manifest hook already contains RedAlarmRingActivity; inspect current changes")
    hook = replace_once(
        hook,
        '    owned = [\n        ("receiver", "org.kivy.android.KivyAlarmReceiver"),\n',
        '    owned = [\n        ("activity", "org.yashtech.redalarm.RedAlarmRingActivity"),\n'
        '        ("receiver", "org.kivy.android.KivyAlarmReceiver"),\n',
        "manifest cleanup registry",
    )
    components = r'''    components = """
        <activity
            android:name="org.yashtech.redalarm.RedAlarmRingActivity"
            android:enabled="true"
            android:exported="false"
            android:launchMode="singleTask"
            android:taskAffinity="org.yashtech.redalarm.ring"
            android:excludeFromRecents="true"
            android:showWhenLocked="true"
            android:turnScreenOn="true" />
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
'''
    hook = replace_region(
        hook,
        '    components = """',
        '    text = text[:app.end()] + components + text[app.end():]',
        components,
        "manifest activity/receiver/service registration",
    )

    # --- Python activity is never granted lockscreen visibility. ---
    main_py = replace_region(
        main_py,
        "    def android_show_over_lockscreen(show):",
        "    def android_copy_content_uri_to_file(uri_string, dest_path):",
        '''    def android_show_over_lockscreen(show):
        """Lockscreen visibility is exclusively owned by RedAlarmRingActivity."""
        _apply_lockscreen_flags(False)

''',
        "normal Python activity lockscreen flags",
    )

    # Notification action PendingIntents are broadcasts rather than PythonActivity launches.
    main_py = replace_region(
        main_py,
        "    def _notification_action_pending_intent(alarm_id, kind):",
        "    def android_apply_notification_logo(builder):",
        '''    def _notification_action_pending_intent(alarm_id, kind):
        """Send Dismiss/Snooze directly to the native receiver, never Home/settings."""
        context = _activity().getApplicationContext()
        Receiver = autoclass("org.yashtech.redalarm.RedAlarmAlarmReceiver")
        intent = Intent(context, Receiver)
        intent.setAction(JString("org.yashtech.redalarm.RING_ACTION"))
        intent.putExtra("alarm_id", JString(str(alarm_id)))
        intent.putExtra("ring_action", JString(str(kind)))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        request_code = stable_request_code(alarm_id, "notif_" + kind)
        return PendingIntent.getBroadcast(_activity(), request_code, intent, flags)

''',
        "Python notification action PendingIntent",
    )

    fallback_notification = '''    def android_show_ring_notification(alarm_id, title, text):
        """Fallback ring notification launches only the native minimal ring screen."""
        context = _activity().getApplicationContext()
        Notification = autoclass("android.app.Notification")
        AndroidR_drawable = autoclass("android.R$drawable")
        RingActivity = autoclass("org.yashtech.redalarm.RedAlarmRingActivity")
        tap_intent = Intent(context, RingActivity)
        tap_intent.setAction(JString("org.yashtech.redalarm.OPEN_RING." + str(alarm_id)))
        tap_intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP)
        tap_intent.putExtra("alarm_id", JString(str(alarm_id)))
        flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        tap_pending_intent = PendingIntent.getActivity(
            _activity(), stable_request_code(alarm_id, "ring_tap"), tap_intent, flags
        )
        dismiss_pi = _notification_action_pending_intent(alarm_id, "dismiss")
        snooze_pi = _notification_action_pending_intent(alarm_id, "snooze")
        if BuildVersion.SDK_INT >= 26:
            builder = autoclass("android.app.Notification$Builder")(context, JString(_RING_CHANNEL_ID))
        else:
            builder = autoclass("android.app.Notification$Builder")(context)
            builder.setPriority(2)
        builder.setContentTitle(JString(title))
        builder.setContentText(JString(text))
        builder.setSmallIcon(AndroidR_drawable.ic_lock_idle_alarm)
        android_apply_notification_logo(builder)
        builder.setCategory(Notification.CATEGORY_ALARM)
        builder.setVisibility(Notification.VISIBILITY_PUBLIC)
        builder.setFullScreenIntent(tap_pending_intent, True)
        builder.setContentIntent(tap_pending_intent)
        builder.addAction(AndroidR_drawable.ic_menu_close_clear_cancel, JString("Dismiss"), dismiss_pi)
        builder.addAction(AndroidR_drawable.ic_popup_reminder, JString("Snooze"), snooze_pi)
        builder.setOngoing(True)
        builder.setAutoCancel(False)
        manager = cast("android.app.NotificationManager", context.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.notify(_RING_NOTIF_ID, builder.build())

'''
    main_py = replace_region(
        main_py,
        "    def android_show_ring_notification(alarm_id, title, text):",
        "    def android_cancel_ring_notification():",
        fallback_notification,
        "fallback ringing notification target",
    )

    # Done should dismiss the normal app task after the alarm is actually committed.
    toast_line = '                Clock.schedule_once(lambda _dt: android_show_toast(message), 0.12)\n'
    if toast_line not in main_py:
        raise RuntimeError("Could not find the alarm-set toast callback; no source files written")
    main_py = replace_once(
        main_py, toast_line,
        toast_line + '                Clock.schedule_once(lambda _dt: android_close_alarm_task(), 0.45)\n',
        "close app after alarm setup",
    )

    # Checks before writing any files.
    compile(main_py, "main.py", "exec")
    if "new Intent(this, RedAlarmRingActivity.class)" not in service:
        raise RuntimeError("Service is not pointed at the ring-only Activity")
    if "performRingAction" not in bridge or "ring_action" not in receiver:
        raise RuntimeError("Native Dismiss/Snooze path is incomplete")
    if "RedAlarmRingActivity" not in hook or "taskAffinity=\"org.yashtech.redalarm.ring\"" not in hook:
        raise RuntimeError("Ring-only Activity manifest registration is incomplete")
    if 'text: "←  BACK"' in kv or 'text: "BACK"' not in kv:
        raise RuntimeError("Back header glyph replacement did not apply")
    if "_apply_lockscreen_flags(False)" not in main_py:
        raise RuntimeError("Normal app lockscreen guard is missing")

    # Backup originals after all safe transformations validated, then atomically save.
    backup = pathlib.Path("/tmp") / ("redalarm-lockscreen-header-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    for rel in FILES_TO_BACK_UP:
        src = root / rel
        if src.exists():
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    print(f"[RedAlarm patch] Backup: {backup}")

    changes = {
        pathlib.Path("main.py"): main_py,
        pathlib.Path("alarm.kv"): kv,
        pathlib.Path("java_src/manifest_hook.py"): hook,
        NATIVE_ROOT / "RedAlarmNativeBridge.java": bridge,
        NATIVE_ROOT / "RedAlarmAlarmReceiver.java": receiver,
        NATIVE_ROOT / "RedAlarmRingingService.java": service,
        NATIVE_ROOT / "RedAlarmApplication.java": app_java,
        NATIVE_ROOT / "RedAlarmRingActivity.java": ring_activity,
    }
    for rel, content in changes.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_suffix(dest.suffix + ".patch-tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(dest)
        print("[RedAlarm patch] Updated", rel.as_posix())

    result = subprocess.run(
        [sys.executable, "-m", "py_compile", "main.py"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError("Patch applied, but main.py syntax validation failed:\n" + result.stderr)
    print("\nSUCCESS: Python syntax passed. Review the diff and run tests before committing.")
    print("Next: git diff --check && python validate_redalarm_timepicker_integration.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\n[RedAlarm patch] ABORTED: {exc}", file=sys.stderr)
        raise SystemExit(1)
