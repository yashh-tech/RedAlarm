package org.yashtech.redalarm;

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
