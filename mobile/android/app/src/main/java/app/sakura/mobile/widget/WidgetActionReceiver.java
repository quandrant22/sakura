package app.sakura.mobile.widget;

import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;

import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import app.sakura.mobile.R;
import app.sakura.mobile.app.Notifications;
import app.sakura.mobile.app.Permissions;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;

/**
 * Кнопка виджета → action_run. Связь поднимается на время запроса (до 8 с ожидания) и, если
 * «Всегда на связи» выключен и приложение закрыто, опускается после ответа. Ошибка — уведомлением.
 */
public class WidgetActionReceiver extends BroadcastReceiver {
    public static final String ACTION_RUN = "app.sakura.mobile.WIDGET_RUN";
    public static final String EXTRA_ACTION = "action";
    static final long WAIT_MS = 8000;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!ACTION_RUN.equals(intent.getAction())) {
            return;
        }
        String action = intent.getStringExtra(EXTRA_ACTION);
        if (action == null || action.isEmpty()) {
            return;
        }
        PendingResult pending = goAsync();
        SakuraApp app = SakuraApp.get();
        SakuraClient client = app.client();
        boolean temporary = client.status().conn != SakuraClient.Conn.ONLINE;
        client.start();
        Handler main = new Handler(Looper.getMainLooper());
        long end = System.currentTimeMillis() + WAIT_MS;
        Runnable[] tick = new Runnable[1];
        tick[0] = () -> {
            if (client.status().conn == SakuraClient.Conn.ONLINE || System.currentTimeMillis() > end) {
                client.request(Json.obj("type", "action_run", "action", action), new RequestClient.Callback() {
                    @Override
                    public void onResult(JSONObject result) {
                        finish(app, temporary, pending);
                    }

                    @Override
                    public void onError(ApiError error) {
                        notifyError(context, ErrorText.text(error));
                        finish(app, temporary, pending);
                    }
                });
            } else {
                main.postDelayed(tick[0], 200);
            }
        };
        main.post(tick[0]);
    }

    private static void finish(SakuraApp app, boolean temporary, PendingResult pending) {
        if (temporary && !app.settings().alwaysOn() && !app.inForeground()) {
            app.client().stop();
        }
        pending.finish();
    }

    private static void notifyError(Context c, String text) {
        if (!Permissions.granted(c, Permissions.Kind.NOTIFICATIONS)) {
            return;
        }
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.notify(Notifications.ID_NOTIFY_BASE - 1, new NotificationCompat.Builder(c, Notifications.CHANNEL_SAKURA)
                    .setSmallIcon(R.drawable.ic_stat_sakura)
                    .setContentTitle("Кнопка виджета не сработала")
                    .setContentText(text)
                    .setAutoCancel(true)
                    .build());
        }
    }
}
