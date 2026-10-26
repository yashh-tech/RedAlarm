package org.yashtech.redalarm;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.text.TextUtils;
import org.json.JSONException;
import org.json.JSONObject;

/** Receives an exact AlarmManager broadcast and starts the independent ring service. */
public final class RedAlarmAlarmReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        String id = intent.getStringExtra("alarm_id");
        String kind = intent.getStringExtra("alarm_kind");
        if (TextUtils.isEmpty(id)) return;
        boolean snooze = "snooze".equals(kind);
        String raw = RedAlarmNativeBridge.getConfig(context, id);
        if (TextUtils.isEmpty(raw)) return;
        JSONObject config;
        try { config = new JSONObject(raw); }
        catch (JSONException e) { android.util.Log.e("RedAlarmNative", "Bad alarm configuration", e); return; }
        SharedPreferences p = context.getApplicationContext().getSharedPreferences("redalarm_native_alarms_v1", Context.MODE_PRIVATE);
        if (!snooze && !RedAlarmNativeBridge.isEnabled(context, id, config)) {
            RedAlarmNativeBridge.refreshNextAlarm(context); return;
        }
        if (snooze) {
            p.edit().remove("snooze:" + id).apply();
        } else {
            p.edit().remove("time:" + id).apply();
            if (RedAlarmNativeBridge.isRepeating(config)) {
                long next = RedAlarmNativeBridge.nextRepeatTrigger(config, System.currentTimeMillis());
                if (next > 0L) RedAlarmNativeBridge.scheduleAlarm(context, id, raw,
                        RedAlarmNativeBridge.getStorePath(context), next, false);
            } else {
                // Persist this before starting Activity/Service so restart cannot
                // turn a one-shot into tomorrow's alarm if Python never runs.
                RedAlarmNativeBridge.markOneTimeComplete(context, id);
            }
        }
        p.edit().putBoolean("ringing:" + id, true).putString("ringing_id", id)
                .putLong("last_fire:" + id, System.currentTimeMillis()).apply();
        Intent service = new Intent(context, RedAlarmRingingService.class);
        service.setAction(RedAlarmRingingService.ACTION_RING);
        service.putExtra("alarm_id", id);
        service.putExtra("alarm_json", raw);
        service.putExtra("alarm_kind", snooze ? "snooze" : "regular");
        try {
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(service);
            else context.startService(service);
        } catch (Throwable e) {
            android.util.Log.e("RedAlarmNative", "Could not start native ringing service", e);
            p.edit().putBoolean("ringing:" + id, false).remove("ringing_id").apply();
        }
        RedAlarmNativeBridge.refreshNextAlarm(context);
    }
}
