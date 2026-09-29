package org.kivy.android;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * OPTIONAL / ADVANCED — see java_src/README.md before using this.
 *
 * AlarmManager entries are wiped when the phone reboots. This receiver
 * listens for BOOT_COMPLETED and re-launches the app so main.py's
 * RedAlarmApp.on_start() can re-read alarms.json and re-arm every enabled
 * alarm with AlarmManager again.
 *
 * Caveat (read this): Android 10+ restricts starting Activities from the
 * background, which is exactly what a BroadcastReceiver is. On some OEM
 * skins this call will simply be ignored. The dependable fallback that
 * costs zero extra code is: just open the app once after a reboot (or add
 * it to your phone's "autostart" / "protected apps" list) — that alone
 * re-arms every alarm, because on_start() re-syncs everything.
 */
public class KivyAlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || intent.getAction() == null) return;
        if (intent.getAction().equals(Intent.ACTION_BOOT_COMPLETED)) {
            try {
                Intent launch = new Intent(context, PythonActivity.class);
                launch.putExtra("boot_resync", true);
                launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                context.startActivity(launch);
            } catch (Exception e) {
                // Swallow — see the background-start caveat above. Worst
                // case, the user opens the app manually and alarms re-arm.
            }
        }
    }
}
