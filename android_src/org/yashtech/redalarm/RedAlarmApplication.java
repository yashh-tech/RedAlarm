package org.yashtech.redalarm;

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
