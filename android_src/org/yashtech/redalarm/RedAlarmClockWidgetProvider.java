package org.yashtech.redalarm;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

/** Medium-small digital clock widget; contains no alarm-control or playback code. */
public class RedAlarmClockWidgetProvider extends AppWidgetProvider {
    private static final String ACTION_UPDATE = "org.yashtech.redalarm.UPDATE_WIDGETS";

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.redalarm_clock_widget);
            RedAlarmWidgetData.bindLaunch(context, views, R.id.redalarm_clock_widget_root, 7301 + id);
            manager.updateAppWidget(id, views);
        }
    }

    @Override public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        if (intent != null && ACTION_UPDATE.equals(intent.getAction())) {
            AppWidgetManager manager = AppWidgetManager.getInstance(context);
            int[] ids = manager.getAppWidgetIds(new ComponentName(context, RedAlarmClockWidgetProvider.class));
            onUpdate(context, manager, ids);
        }
    }
}

