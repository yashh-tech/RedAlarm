package org.yashtech.redalarm;

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
