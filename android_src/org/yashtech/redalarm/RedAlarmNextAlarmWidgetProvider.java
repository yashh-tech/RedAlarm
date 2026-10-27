package org.yashtech.redalarm;

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

/** Upcoming-alarm widget with passive, display-only countdown text. */
public class RedAlarmNextAlarmWidgetProvider extends AppWidgetProvider {
    private static final String ACTION_UPDATE = "org.yashtech.redalarm.UPDATE_WIDGETS";

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.redalarm_next_alarm_widget);
            views.setTextViewText(R.id.redalarm_next_alarm_text, RedAlarmWidgetData.upcomingText(context));
            RedAlarmWidgetData.bindLaunch(context, views, R.id.redalarm_next_alarm_widget_root, 7401 + id);
            manager.updateAppWidget(id, views);
        }
    }

    @Override public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        if (intent != null && ACTION_UPDATE.equals(intent.getAction())) {
            AppWidgetManager manager = AppWidgetManager.getInstance(context);
            int[] ids = manager.getAppWidgetIds(new ComponentName(context, RedAlarmNextAlarmWidgetProvider.class));
            onUpdate(context, manager, ids);
        }
    }
}

