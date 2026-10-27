package app.sakura.mobile.widget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.ui.MainActivity;
import app.sakura.mobile.ui.model.ActionCatalog;

/** Виджет: статичный кадр ядра (тап — говорить), «Говорить», три кнопки action_run из настроек. */
public class CoreWidget extends AppWidgetProvider {
    static final int[] BUTTONS = {R.id.w_a1, R.id.w_a2, R.id.w_a3};

    /** Короткая подпись кнопки по id действия. */
    static String label(Context c, String action) {
        switch (action) {
            case "music.play_pause":
                return "⏯ Пауза";
            case "music.next":
                return "⏭ Дальше";
            case "music.prev":
                return "⏮ Назад";
            case "music.wave":
                return "Волна";
            case "kettle.boil":
            case "kettle.on":
                return "Чайник";
            case "screenshot.run":
                return "Скриншот";
            default:
                ActionCatalog.Action a = ActionCatalog.get(c).find(action);
                return a == null || a.desc.isEmpty() ? action : a.desc;
        }
    }

    public static String[] actions(Context c) {
        String[] a = SakuraApp.get().settings().widgetActions().split(",");
        String[] out = new String[3];
        for (int i = 0; i < 3; i++) {
            out[i] = i < a.length ? a[i].trim() : "music.play_pause";
        }
        return out;
    }

    static RemoteViews build(Context c) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_core);
        int size = c.getResources().getDimensionPixelSize(R.dimen.core_floating) * 2;
        v.setImageViewBitmap(R.id.w_core, SakuraCoreView.renderStatic(c, CoreFrame.State.IDLE, size));
        PendingIntent listen = PendingIntent.getActivity(c, 20,
                new Intent(c, MainActivity.class).setAction(MainActivity.ACTION_LISTEN)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        v.setOnClickPendingIntent(R.id.w_core, listen);
        v.setOnClickPendingIntent(R.id.w_mic, listen);
        String[] acts = actions(c);
        for (int i = 0; i < BUTTONS.length; i++) {
            v.setTextViewText(BUTTONS[i], label(c, acts[i]));
            v.setContentDescription(BUTTONS[i], label(c, acts[i]));
            Intent run = new Intent(c, WidgetActionReceiver.class).setAction(WidgetActionReceiver.ACTION_RUN)
                    .putExtra(WidgetActionReceiver.EXTRA_ACTION, acts[i]);
            v.setOnClickPendingIntent(BUTTONS[i], PendingIntent.getBroadcast(c, 30 + i, run,
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        }
        return v;
    }

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        RemoteViews v = build(context);
        for (int id : ids) {
            manager.updateAppWidget(id, v);
        }
    }

    /** Перерисовать все экземпляры (смена кнопок в настройках). */
    public static void refresh(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] ids = m.getAppWidgetIds(new ComponentName(c, CoreWidget.class));
        if (ids.length > 0) {
            RemoteViews v = build(c);
            for (int id : ids) {
                m.updateAppWidget(id, v);
            }
        }
    }
}
