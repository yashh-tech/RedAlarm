package org.yashtech.redalarm;

import android.app.Activity;
import android.app.Application;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

/**
 * Enable lock-screen visibility only when Android creates the activity for a
 * real alarm launch. Normal Home/clock/editor launches must remain behind the
 * keyguard. Dismiss/Snooze notification actions also must not reveal the app.
 *
 * A cold-start alarm needs these flags during Activity creation; setting them
 * only later from Python can be too late for Android to display it over lock.
 */
public class RedAlarmApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        registerActivityLifecycleCallbacks(new ActivityLifecycleCallbacks() {
            @Override
            public void onActivityCreated(Activity activity, Bundle savedInstanceState) {
                try {
                    Intent intent = activity.getIntent();
                    String alarmId = intent == null ? null : intent.getStringExtra("alarm_id");
                    String actionKind = intent == null ? null : intent.getStringExtra("action_kind");
                    boolean isAlarmLaunch = alarmId != null && actionKind == null;

                    if (Build.VERSION.SDK_INT >= 27) {
                        activity.setShowWhenLocked(isAlarmLaunch);
                        activity.setTurnScreenOn(isAlarmLaunch);
                    } else if (isAlarmLaunch) {
                        activity.getWindow().addFlags(
                                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                                        | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
                    } else {
                        activity.getWindow().clearFlags(
                                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                                        | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
                    }
                } catch (Throwable ignored) {
                    // Never let lock-screen setup crash application startup.
                }
            }

            @Override public void onActivityStarted(Activity activity) { }
            @Override public void onActivityResumed(Activity activity) { }
            @Override public void onActivityPaused(Activity activity) { }
            @Override public void onActivityStopped(Activity activity) { }
            @Override public void onActivitySaveInstanceState(Activity activity, Bundle outState) { }
            @Override public void onActivityDestroyed(Activity activity) { }
        });
    }
}
