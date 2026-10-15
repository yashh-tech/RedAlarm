package org.yashtech.redalarm;

import android.app.Activity;
import android.app.Application;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

/**
 * Makes RedAlarm's activity eligible to appear over the LOCK SCREEN and to
 * turn the screen on, from the moment it is created.
 *
 * Why this exists: when an activity is started while the phone is locked,
 * Android keeps it in the stopped state (hidden behind the keyguard) unless
 * showWhenLocked is already set. Setting it later from Python (after the
 * activity has already been resumed/stopped) is too late, which is why the
 * alarm screen only appeared after unlocking. This is the code equivalent
 * of android:showWhenLocked / android:turnScreenOn in the manifest (p4a's
 * manifest template has no hook for activity attributes, but it does let us
 * set the <application> class — see extra_manifest_application_arguments.xml).
 *
 * It deliberately does NOT call requestDismissKeyguard(): the alarm screen
 * is shown OVER a secure lock screen, so Dismiss/Snooze work without a PIN.
 */
public class RedAlarmApplication extends Application {

    @Override
    public void onCreate() {
        super.onCreate();
        registerActivityLifecycleCallbacks(new ActivityLifecycleCallbacks() {
            @Override
            public void onActivityCreated(Activity activity, Bundle savedInstanceState) {
                try {
                    if (Build.VERSION.SDK_INT >= 27) {
                        activity.setShowWhenLocked(true);
                        activity.setTurnScreenOn(true);
                    } else {
                        activity.getWindow().addFlags(
                                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                                        | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
                    }
                } catch (Throwable ignored) {
                    // never let a lock-screen nicety crash app startup
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
