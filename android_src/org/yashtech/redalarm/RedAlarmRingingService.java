package org.yashtech.redalarm;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.text.TextUtils;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.File;

/** Independent Android media-playback foreground service. It continues if the
 * Kivy Activity pauses, the display locks, or the Activity process is reclaimed. */
public final class RedAlarmRingingService extends Service {
    public static final String ACTION_RING = "org.yashtech.redalarm.RING";
    private static final String CHANNEL = "redalarm_ringing_v2";
    private static final int NOTIFICATION_ID = 1002;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private MediaPlayer player;
    private PowerManager.WakeLock wakeLock;
    private Vibrator vibrator;
    private String alarmId = "";
    private int session = 0;
    private final Runnable timeout = new Runnable() { @Override public void run() { stopAndFinish(); } };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || !ACTION_RING.equals(intent.getAction())) { stopSelf(startId); return START_NOT_STICKY; }
        String id = intent.getStringExtra("alarm_id");
        String raw = intent.getStringExtra("alarm_json");
        if (TextUtils.isEmpty(id)) { stopSelf(startId); return START_NOT_STICKY; }
        if (TextUtils.isEmpty(raw)) raw = RedAlarmNativeBridge.getConfig(this, id);
        JSONObject config;
        try { config = new JSONObject(raw == null ? "{}" : raw); }
        catch (JSONException e) { config = new JSONObject(); }
        stopCurrentPlayback();
        handler.removeCallbacks(timeout);
        alarmId = id;
        session++;
        ensureRingChannel();
        Notification notification = buildNotification(id, config);
        try { startForeground(NOTIFICATION_ID, notification); }
        catch (Throwable e) { android.util.Log.e("RedAlarmNative", "startForeground failed", e); }
        getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                .putBoolean("ringing:" + id, true).putString("ringing_id", id).apply();
        acquireWakeLock(Math.max(1, config.optInt("auto_dismiss_sec", 5)) + 15);
        startAudio(config);
        if (config.optBoolean("vibrate", false)) startVibration();
        int duration = Math.max(1, Math.min(10800, config.optInt("auto_dismiss_sec", 5)));
        final int run = session;
        handler.postDelayed(new Runnable() { @Override public void run() { if (run == session) stopAndFinish(); } }, duration * 1000L);
        return START_NOT_STICKY;
    }

    private void ensureRingChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Alarm ringing", NotificationManager.IMPORTANCE_HIGH);
            channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            channel.enableVibration(false);
            channel.setSound(null, null);
            nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification(String id, JSONObject config) {
        String label = config.optString("label", "Alarm").trim();
        if (label.isEmpty()) label = "Alarm";
        int hour = Math.max(0, Math.min(23, config.optInt("hour", 7)));
        int minute = Math.max(0, Math.min(59, config.optInt("minute", 0)));
        String time = String.format(java.util.Locale.getDefault(), "%d:%02d %s",
                (hour % 12 == 0 ? 12 : hour % 12), minute, hour >= 12 ? "PM" : "AM");
        String nonce = "native_" + System.currentTimeMillis();
        Intent open = new Intent(this, org.kivy.android.PythonActivity.class);
        open.setAction("org.yashtech.redalarm.NATIVE_FIRE." + id);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        open.putExtra("alarm_id", id);
        open.putExtra("fire_token", nonce);
        open.putExtra("native_ring", true);
        PendingIntent content = PendingIntent.getActivity(this, RedAlarmNativeBridge.requestCode(id, "ring_tap"), open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent dismiss = actionPendingIntent(id, "dismiss");
        PendingIntent snooze = actionPendingIntent(id, "snooze");
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this).setPriority(Notification.PRIORITY_MAX);
        b.setContentTitle(label).setContentText("Alarm • " + time)
                .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                .setCategory(Notification.CATEGORY_ALARM)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setContentIntent(content).setFullScreenIntent(content, true)
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Dismiss", dismiss)
                .addAction(android.R.drawable.ic_popup_reminder, "Snooze", snooze)
                .setOngoing(true).setAutoCancel(false).setOnlyAlertOnce(true);
        Notification n = b.build();
        n.flags |= Notification.FLAG_NO_CLEAR | Notification.FLAG_ONGOING_EVENT;
        return n;
    }

    private PendingIntent actionPendingIntent(String id, String kind) {
        Intent i = new Intent(this, org.kivy.android.PythonActivity.class);
        i.setAction("org.yashtech.redalarm.ACTION." + kind.toUpperCase() + "." + id);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        i.putExtra("alarm_id", id);
        i.putExtra("action_kind", kind);
        i.putExtra("fire_token", kind + "_" + System.currentTimeMillis());
        return PendingIntent.getActivity(this, RedAlarmNativeBridge.requestCode(id, "notif_" + kind), i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private void acquireWakeLock(int seconds) {
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null) {
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RedAlarm:NativeRinging");
                wakeLock.acquire(seconds * 1000L);
            }
        } catch (Throwable e) { android.util.Log.w("RedAlarmNative", "Wake lock unavailable", e); }
    }

    private void startAudio(JSONObject config) {
        String[] paths = new String[] {
                config.optString("native_sound_path", ""),
                config.optString("native_fallback_path", ""),
                config.optString("sound_path", "")
        };
        float volume = (float) Math.max(0.0, Math.min(1.0, config.optDouble("volume", 0.80)));
        for (String path : paths) {
            if (TextUtils.isEmpty(path) || path.startsWith("content:") || !new File(path).isFile()) continue;
            try {
                MediaPlayer mp = new MediaPlayer();
                AudioAttributes attrs = new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
                mp.setAudioAttributes(attrs);
                mp.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
                mp.setDataSource(path);
                mp.setLooping(true);
                mp.setVolume(volume, volume);
                mp.prepare(); mp.start(); player = mp; return;
            } catch (Throwable e) { android.util.Log.e("RedAlarmNative", "Ringtone path failed: " + path, e); }
        }
        try {
            Uri uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            if (uri == null) uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
            if (uri != null) {
                MediaPlayer mp = new MediaPlayer();
                mp.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                mp.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
                mp.setDataSource(this, uri); mp.setLooping(true); mp.setVolume(volume, volume);
                mp.prepare(); mp.start(); player = mp;
            }
        } catch (Throwable e) { android.util.Log.e("RedAlarmNative", "Default ringtone failed", e); }
    }

    private void startVibration() {
        try {
            vibrator = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (vibrator != null && vibrator.hasVibrator()) {
                if (Build.VERSION.SDK_INT >= 26) vibrator.vibrate(VibrationEffect.createWaveform(new long[]{0, 550, 250}, 0));
                else vibrator.vibrate(new long[]{0, 550, 250}, 0);
            }
        } catch (Throwable e) { android.util.Log.w("RedAlarmNative", "Vibration unavailable", e); }
    }

    private void stopCurrentPlayback() {
        try { if (player != null) { try { if (player.isPlaying()) player.stop(); } catch (Throwable ignored) { } player.release(); } }
        catch (Throwable ignored) { }
        player = null;
        try { if (vibrator != null) vibrator.cancel(); } catch (Throwable ignored) { }
        vibrator = null;
        try { if (wakeLock != null && wakeLock.isHeld()) wakeLock.release(); } catch (Throwable ignored) { }
        wakeLock = null;
    }

    private void stopAndFinish() {
        handler.removeCallbacks(timeout);
        stopCurrentPlayback();
        getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                .putBoolean("ringing:" + alarmId, false).remove("ringing_id").apply();
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(NOTIFICATION_ID);
        try { stopForeground(true); } catch (Throwable ignored) { }
        stopSelf();
        RedAlarmNativeBridge.refreshNextAlarm(this);
    }

    @Override public void onDestroy() {
        session++;
        handler.removeCallbacksAndMessages(null);
        stopCurrentPlayback();
        if (!TextUtils.isEmpty(alarmId)) {
            getSharedPreferences("redalarm_native_alarms_v1", MODE_PRIVATE).edit()
                    .putBoolean("ringing:" + alarmId, false).remove("ringing_id").apply();
        }
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(NOTIFICATION_ID);
        super.onDestroy();
    }
}
