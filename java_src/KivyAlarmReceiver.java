package org.kivy.android;

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
