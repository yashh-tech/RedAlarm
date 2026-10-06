package org.kivy.android;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import java.util.Calendar;

/**
 * Receives alarm triggers from AlarmManager and launches the app to show the alarm UI.
 * Also handles BOOT_COMPLETED to re-arm all alarms after a reboot.
 */
public class AlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || intent.getAction() == null) return;

        String action = intent.getAction();

        if (action.equals(Intent.ACTION_BOOT_COMPLETED)) {
            // Phone rebooted — start the app so it can re-arm all alarms
            Intent launchIntent = new Intent(context, PythonActivity.class);
            launchIntent.setAction(Intent.ACTION_BOOT_COMPLETED);
            launchIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            context.startActivity(launchIntent);

            // Also start the foreground service to ensure alarm processing stays alive
            startAlarmService(context);
        } else if (action.equals("org.yashtech.redalarm.ALARM_TRIGGER")) {
            // An alarm has fired — show the alarm UI with full-screen, lock-screen, and wake flags
            String alarmId = intent.getStringExtra("alarm_id");

            Intent launchIntent = new Intent(context, PythonActivity.class);
            launchIntent.setAction("org.yashtech.redalarm.ALARM_TRIGGER");
            launchIntent.putExtra("alarm_id", alarmId);
            launchIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);

            // Full-screen on lock screen, wake the device
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
                context.startActivity(launchIntent);
            } else {
                context.startActivity(launchIntent);
            }

            // Keep the service alive
            startAlarmService(context);
        }
    }

    private void startAlarmService(Context context) {
        Intent serviceIntent = new Intent(context, AlarmService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent);
        } else {
            context.startService(serviceIntent);
        }
    }
}
