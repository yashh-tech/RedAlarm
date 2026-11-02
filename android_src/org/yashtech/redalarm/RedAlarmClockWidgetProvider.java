package org.yashtech.redalarm;

import android.app.AlarmManager;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.app.PendingIntent;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.res.Configuration;
import android.os.Build;
import android.os.Bundle;
import android.util.SizeF;
import android.widget.RemoteViews;

import java.util.HashMap;
import java.util.Map;

/**
 * One resizable home-screen widget with three designs:
 * 4x2 (live clock + next two alarms), 4x1 (clock + next alarm), 2x2 (countdown).
 * Whatever size the launcher allows, the closest design is shown.
 */
public class RedAlarmClockWidgetProvider extends AppWidgetProvider {
    private static final String ACTION_UPDATE = "org.yashtech.redalarm.UPDATE_WIDGETS";
    private static final String ACTION_TICK = "org.yashtech.redalarm.UPDATE_WIDGET_TICK";
    private static final int TICK_REQUEST_CODE = 7601;

    private static final float WIDE_MIN_WIDTH_DP = 220f;
    private static final float LARGE_MIN_HEIGHT_DP = 100f;

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) updateWidget(context, manager, id);
        scheduleNextTick(context);
    }

    @Override public void onAppWidgetOptionsChanged(Context context, AppWidgetManager manager,
                                                    int id, Bundle newOptions) {
        super.onAppWidgetOptionsChanged(context, manager, id, newOptions);
        updateWidget(context, manager, id);
    }

    @Override public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        if (intent != null && (ACTION_UPDATE.equals(intent.getAction()) || ACTION_TICK.equals(intent.getAction()))) {
            AppWidgetManager manager = AppWidgetManager.getInstance(context);
            int[] ids = manager.getAppWidgetIds(new ComponentName(context, RedAlarmClockWidgetProvider.class));
            onUpdate(context, manager, ids);
        }
    }

    @Override public void onDisabled(Context context) {
        super.onDisabled(context);
        PendingIntent tick = tickPendingIntent(context);
        AlarmManager alarms = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarms != null) alarms.cancel(tick);
    }

    private static void updateWidget(Context context, AppWidgetManager manager, int id) {
        RemoteViews square = buildViews(context, R.layout.redalarm_widget_square, id);
        RemoteViews wide = buildViews(context, R.layout.redalarm_widget_wide, id);
        RemoteViews large = buildViews(context, R.layout.redalarm_widget_large, id);
        RemoteViews views;
        if (Build.VERSION.SDK_INT >= 31) {
            // Android 12+: the launcher picks the biggest design that fits the current size.
            Map<SizeF, RemoteViews> bySize = new HashMap<>();
            bySize.put(new SizeF(100f, 100f), square);
            bySize.put(new SizeF(WIDE_MIN_WIDTH_DP, 40f), wide);
            bySize.put(new SizeF(WIDE_MIN_WIDTH_DP, LARGE_MIN_HEIGHT_DP), large);
            views = new RemoteViews(bySize);
        } else {
            // Launchers report portrait as (minWidth, maxHeight) and landscape as
            // (maxWidth, minHeight); never mix dimensions from different orientations.
            Bundle options = manager.getAppWidgetOptions(id);
            boolean landscape = context.getResources().getConfiguration().orientation
                    == Configuration.ORIENTATION_LANDSCAPE;
            int width = options.getInt(landscape ? AppWidgetManager.OPTION_APPWIDGET_MAX_WIDTH
                    : AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 0);
            int height = options.getInt(landscape ? AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT
                    : AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 0);
            if (width == 0 && height == 0) views = large;
            else if (width >= WIDE_MIN_WIDTH_DP && height >= LARGE_MIN_HEIGHT_DP) views = large;
            else if (width >= WIDE_MIN_WIDTH_DP) views = wide;
            else views = square;
        }
        manager.updateAppWidget(id, views);
    }

    private static RemoteViews buildViews(Context context, int layout, int id) {
        RemoteViews views = new RemoteViews(context.getPackageName(), layout);
        views.setTextViewText(R.id.ra_next_time, RedAlarmWidgetData.alarmTimeText(context, false));
        views.setTextViewText(R.id.ra_next_days, RedAlarmWidgetData.alarmDaysText(context, false));
        if (layout != R.layout.redalarm_widget_wide) {
            views.setTextViewText(R.id.ra_next_label, RedAlarmWidgetData.alarmLabelText(context, false));
        }
        if (layout == R.layout.redalarm_widget_large) {
            views.setTextViewText(R.id.ra_second_time, RedAlarmWidgetData.alarmTimeText(context, true));
            views.setTextViewText(R.id.ra_second_label, RedAlarmWidgetData.alarmLabelText(context, true));
            views.setTextViewText(R.id.ra_second_days, RedAlarmWidgetData.alarmDaysText(context, true));
        }
        if (layout == R.layout.redalarm_widget_square) {
            views.setTextViewText(R.id.ra_countdown, RedAlarmWidgetData.countdownText(context));
        } else if (layout == R.layout.redalarm_widget_large) {
            views.setTextViewText(R.id.ra_countdown, RedAlarmWidgetData.countdownSecondsText(context));
        }
        RedAlarmWidgetData.bindLaunch(context, views, R.id.ra_widget_root, 7301 + id);
        return views;
    }

    // One re-armed exact tick: 1s while an alarm is pending (live countdown),
    // 60s once nothing is upcoming.
    private static void scheduleNextTick(Context context) {
        AlarmManager alarms = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarms == null) return;
        long interval = RedAlarmWidgetData.hasUpcomingAlarm(context) ? 1_000L : 60_000L;
        PendingIntent tick = tickPendingIntent(context);
        long at = System.currentTimeMillis() + interval;
        if (Build.VERSION.SDK_INT >= 23) alarms.setExactAndAllowWhileIdle(AlarmManager.RTC, at, tick);
        else if (Build.VERSION.SDK_INT >= 19) alarms.setExact(AlarmManager.RTC, at, tick);
        else alarms.set(AlarmManager.RTC, at, tick);
    }

    private static PendingIntent tickPendingIntent(Context context) {
        Intent tick = new Intent(context, RedAlarmClockWidgetProvider.class);
        tick.setAction(ACTION_TICK);
        return PendingIntent.getBroadcast(context, TICK_REQUEST_CODE, tick,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
}
