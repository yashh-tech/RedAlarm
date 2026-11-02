package org.yashtech.redalarm;

import android.app.AlarmManager;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.app.PendingIntent;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

/** Combined live analog/digital clock + next-alarm countdown widget. */
public class RedAlarmClockWidgetProvider extends AppWidgetProvider {
    private static final String ACTION_UPDATE = "org.yashtech.redalarm.UPDATE_WIDGETS";
    private static final String ACTION_TICK = "org.yashtech.redalarm.UPDATE_WIDGET_TICK";
    private static final int TICK_REQUEST_CODE = 7601;

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        scheduleMinuteTick(context);
        for (int id : ids) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.redalarm_clock_widget);
            views.setTextViewText(R.id.redalarm_next_alarm_text, RedAlarmWidgetData.alarmTimeText(context, false));
            views.setTextViewText(R.id.redalarm_next_alarm_label, RedAlarmWidgetData.alarmLabelText(context, false));
            RedAlarmWidgetData.bindLaunch(context, views, R.id.redalarm_clock_widget_root, 7301 + id);
            manager.updateAppWidget(id, views);
        }
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

    private static void scheduleMinuteTick(Context context) {
        AlarmManager alarms = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarms == null) return;
        long first = System.currentTimeMillis() + 60_000L;
        alarms.setInexactRepeating(AlarmManager.RTC, first, 60_000L, tickPendingIntent(context));
    }

    private static PendingIntent tickPendingIntent(Context context) {
        Intent tick = new Intent(context, RedAlarmClockWidgetProvider.class);
        tick.setAction(ACTION_TICK);
        return PendingIntent.getBroadcast(context, TICK_REQUEST_CODE, tick,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
}

