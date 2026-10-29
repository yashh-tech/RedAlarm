package org.yashtech.redalarm;

import android.app.KeyguardManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.TextUtils;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Shows the RedAlarm ringing controls over the current app when Android is
 * unlocked. Locked-screen presentation remains owned by RedAlarmRingActivity's
 * full-screen alarm notification. This overlay never schedules or plays audio.
 */
final class RedAlarmUnlockedOverlay {
    private static final String TAG = "RedAlarmNative";
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private static Context appContext;
    private static WindowManager windowManager;
    private static View overlayView;
    private static TextView countdownView;
    private static String activeAlarmId = "";
    private static int fallbackDurationSeconds = 5;
    private static long fallbackDeadlineElapsed;

    private RedAlarmUnlockedOverlay() { }

    static void show(Context context, String alarmId, JSONObject config) {
        if (context == null || TextUtils.isEmpty(alarmId)) return;
        final Context app = context.getApplicationContext();
        final String id = alarmId;
        final JSONObject safeConfig = config == null ? new JSONObject() : config;
        MAIN.post(new Runnable() {
            @Override public void run() { showOnMain(app, id, safeConfig); }
        });
    }

    static void hide(Context context) {
        MAIN.post(new Runnable() {
            @Override public void run() { hideOnMain(); }
        });
    }

    private static void showOnMain(Context context, String id, JSONObject config) {
        hideOnMain();
        if (context == null || TextUtils.isEmpty(id)) return;

        PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        if (power == null || !power.isInteractive()) return;

        KeyguardManager keyguard = (KeyguardManager) context.getSystemService(Context.KEYGUARD_SERVICE);
        if (keyguard != null && keyguard.isKeyguardLocked()) {
            // Do not place a SYSTEM_ALERT_WINDOW above the keyguard. The
            // dedicated full-screen RingActivity handles that case instead.
            return;
        }
        if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(context)) {
            Log.w(TAG, "Cannot show unlocked ringing overlay: display-over-apps permission is off");
            return;
        }

        SharedPreferences prefs = context.getSharedPreferences("redalarm_native_alarms_v1", Context.MODE_PRIVATE);
        if (!prefs.getBoolean("ringing:" + id, false)
                || !id.equals(prefs.getString("ringing_id", ""))) return;

        appContext = context;
        activeAlarmId = id;
        fallbackDurationSeconds = Math.max(1, Math.min(10800,
                config.optInt("auto_dismiss_sec", 5)));
        fallbackDeadlineElapsed = android.os.SystemClock.elapsedRealtime()
                + fallbackDurationSeconds * 1000L;

        int hour24 = Math.max(0, Math.min(23, config.optInt("hour", 7)));
        int minute = Math.max(0, Math.min(59, config.optInt("minute", 0)));
        String label = config.optString("label", "Alarm").trim();
        if (label.isEmpty()) label = "Alarm";
        String clock = String.format(java.util.Locale.getDefault(), "%d:%02d %s",
                (hour24 % 12 == 0 ? 12 : hour24 % 12), minute, hour24 >= 12 ? "PM" : "AM");

        LinearLayout root = new LinearLayout(context);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        int sidePadding = dp(context, 26);
        root.setPadding(sidePadding, dp(context, 24), sidePadding, dp(context, 24));
        root.setBackgroundColor(Color.rgb(5, 5, 7));

        TextView heading = new TextView(context);
        heading.setText("REDALARM  /  ALARM");
        heading.setTextColor(Color.rgb(210, 30, 38));
        heading.setTextSize(14);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        heading.setGravity(Gravity.CENTER);
        root.addView(heading, new LinearLayout.LayoutParams(-1, dp(context, 34)));

        TextView labelView = new TextView(context);
        labelView.setText(label);
        labelView.setTextColor(Color.WHITE);
        labelView.setTextSize(22);
        labelView.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        labelView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams labelParams = new LinearLayout.LayoutParams(-1, dp(context, 54));
        labelParams.bottomMargin = dp(context, 8);
        root.addView(labelView, labelParams);

        TextView timeView = new TextView(context);
        timeView.setText(clock);
        timeView.setTextColor(Color.WHITE);
        timeView.setTextSize(56);
        timeView.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        timeView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams timeParams = new LinearLayout.LayoutParams(-1, dp(context, 90));
        timeParams.bottomMargin = dp(context, 18);
        root.addView(timeView, timeParams);

        LinearLayout countdownCard = new LinearLayout(context);
        countdownCard.setOrientation(LinearLayout.VERTICAL);
        countdownCard.setGravity(Gravity.CENTER);
        countdownCard.setPadding(dp(context, 12), dp(context, 5), dp(context, 12), dp(context, 5));
        GradientDrawable cardShape = new GradientDrawable();
        cardShape.setColor(Color.rgb(34, 8, 11));
        cardShape.setCornerRadius(dp(context, 18));
        cardShape.setStroke(dp(context, 1), Color.rgb(156, 12, 12));
        countdownCard.setBackground(cardShape);

        TextView countdownTitle = new TextView(context);
        countdownTitle.setText("AUTO-DISMISS IN");
        countdownTitle.setTextColor(Color.rgb(226, 145, 150));
        countdownTitle.setTextSize(13);
        countdownTitle.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        countdownTitle.setGravity(Gravity.CENTER);
        countdownCard.addView(countdownTitle, new LinearLayout.LayoutParams(-1, dp(context, 24)));

        countdownView = new TextView(context);
        countdownView.setTextColor(Color.WHITE);
        countdownView.setTextSize(38);
        countdownView.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        countdownView.setGravity(Gravity.CENTER);
        countdownCard.addView(countdownView, new LinearLayout.LayoutParams(-1, dp(context, 48)));
        LinearLayout.LayoutParams countdownParams = new LinearLayout.LayoutParams(-1, dp(context, 82));
        countdownParams.bottomMargin = dp(context, 24);
        root.addView(countdownCard, countdownParams);

        Button snooze = makeButton(context, "Snooze", Color.rgb(48, 48, 53));
        snooze.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                RedAlarmNativeBridge.performRingAction(context, id, "snooze");
            }
        });
        LinearLayout.LayoutParams snoozeParams = new LinearLayout.LayoutParams(-1, dp(context, 58));
        snoozeParams.bottomMargin = dp(context, 12);
        root.addView(snooze, snoozeParams);

        Button dismiss = makeButton(context, "Dismiss", Color.rgb(156, 12, 12));
        dismiss.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                RedAlarmNativeBridge.performRingAction(context, id, "dismiss");
            }
        });
        root.addView(dismiss, new LinearLayout.LayoutParams(-1, dp(context, 58)));

        windowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
        if (windowManager == null) {
            hideOnMain();
            return;
        }
        int type = Build.VERSION.SDK_INT >= 26
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
                type,
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        params.setTitle("RedAlarm ringing controls");
        try {
            overlayView = root;
            windowManager.addView(overlayView, params);
            updateCountdown();
            MAIN.removeCallbacks(countdownTick);
            MAIN.post(countdownTick);
        } catch (Throwable error) {
            Log.e(TAG, "Could not show unlocked ringing overlay", error);
            hideOnMain();
        }
    }

    private static final Runnable countdownTick = new Runnable() {
        @Override public void run() {
            if (overlayView == null || appContext == null || TextUtils.isEmpty(activeAlarmId)
                    || countdownView == null) return;
            SharedPreferences prefs = appContext.getSharedPreferences(
                    "redalarm_native_alarms_v1", Context.MODE_PRIVATE);
            if (!prefs.getBoolean("ringing:" + activeAlarmId, false)
                    || !activeAlarmId.equals(prefs.getString("ringing_id", ""))) {
                hideOnMain();
                return;
            }
            updateCountdown();
            long started = prefs.getLong("ring_started_elapsed:" + activeAlarmId, 0L);
            int duration = Math.max(1, prefs.getInt(
                    "ring_duration_sec:" + activeAlarmId, fallbackDurationSeconds));
            long deadline = started > 0L ? started + duration * 1000L : fallbackDeadlineElapsed;
            if (deadline > android.os.SystemClock.elapsedRealtime()) MAIN.postDelayed(this, 250L);
        }
    };

    private static void updateCountdown() {
        if (countdownView == null || appContext == null || TextUtils.isEmpty(activeAlarmId)) return;
        SharedPreferences prefs = appContext.getSharedPreferences(
                "redalarm_native_alarms_v1", Context.MODE_PRIVATE);
        long started = prefs.getLong("ring_started_elapsed:" + activeAlarmId, 0L);
        int duration = Math.max(1, prefs.getInt(
                "ring_duration_sec:" + activeAlarmId, fallbackDurationSeconds));
        long deadline = started > 0L ? started + duration * 1000L : fallbackDeadlineElapsed;
        long seconds = Math.max(0L,
                (deadline - android.os.SystemClock.elapsedRealtime() + 999L) / 1000L);
        countdownView.setText(String.format(java.util.Locale.getDefault(), "%02d:%02d",
                seconds / 60L, seconds % 60L));
    }

    private static Button makeButton(Context context, String title, int color) {
        Button button = new Button(context);
        button.setText(title);
        button.setTextColor(Color.WHITE);
        button.setTextSize(17);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(context, 18));
        button.setBackground(shape);
        return button;
    }

    private static int dp(Context context, float value) {
        return (int) (value * context.getResources().getDisplayMetrics().density + 0.5f);
    }

    private static void hideOnMain() {
        MAIN.removeCallbacks(countdownTick);
        View oldView = overlayView;
        WindowManager oldManager = windowManager;
        overlayView = null;
        countdownView = null;
        windowManager = null;
        appContext = null;
        activeAlarmId = "";
        if (oldView != null && oldManager != null) {
            try { oldManager.removeViewImmediate(oldView); }
            catch (Throwable ignored) { }
        }
    }
}
