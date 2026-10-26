package app.sakura.mobile.app;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;
import androidx.core.content.ContextCompat;

import app.sakura.mobile.R;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.MainActivity;

/**
 * Foreground-служба «Всегда на связи»: тип specialUse (держит связь с Сакурой) и microphone,
 * пока включено прослушивание. Уведомление — состояние связи, «Говорить», «Отключиться».
 */
public class SakuraService extends Service {
    public static final String ACTION_DISCONNECT = "app.sakura.mobile.DISCONNECT";
    public static final String ACTION_LISTENING = "app.sakura.mobile.LISTENING";
    public static final String EXTRA_ON = "on";

    private static volatile boolean running;

    private final Handler main = new Handler(Looper.getMainLooper());
    private Runnable unsubscribe;
    private boolean listening;
    private SakuraClient.Status last;

    public static void start(Context context) {
        ContextCompat.startForegroundService(context, new Intent(context, SakuraService.class));
    }

    public static void stop(Context context) {
        context.stopService(new Intent(context, SakuraService.class));
    }

    public static boolean isRunning() {
        return running;
    }

    /** Добавить/убрать тип microphone (вызывать из открытого приложения). */
    public static void setListening(Context context, boolean on) {
        if (!running) {
            return;
        }
        Intent i = new Intent(context, SakuraService.class).setAction(ACTION_LISTENING).putExtra(EXTRA_ON, on);
        context.startService(i);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        SakuraApp app = SakuraApp.get();
        foreground(app.client().status());
        unsubscribe = app.client().onStatus(s -> main.post(() -> update(s)));
        app.client().start();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_DISCONNECT.equals(action)) {
            SakuraApp.get().setAlwaysOn(false);
            if (!SakuraApp.get().inForeground()) {
                SakuraApp.get().client().stop();
            }
            stopSelf();
            return START_NOT_STICKY;
        }
        if (ACTION_LISTENING.equals(action)) {
            listening = intent.getBooleanExtra(EXTRA_ON, false);
            foreground(SakuraApp.get().client().status());
        }
        return START_STICKY;
    }

    private void update(SakuraClient.Status s) {
        last = s;
        if (running) {
            foreground(s);
        }
    }

    private void foreground(SakuraClient.Status s) {
        int type = ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE;
        if (listening) {
            type |= ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE;
        }
        try {
            ServiceCompat.startForeground(this, Notifications.ID_SERVICE, build(s), type);
        } catch (RuntimeException e) {
            // microphone из фона запрещён — остаёмся specialUse
            listening = false;
            ServiceCompat.startForeground(this, Notifications.ID_SERVICE, build(s),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        }
    }

    static String stateText(SakuraClient.Status s) {
        switch (s.conn) {
            case ONLINE:
                return "Онлайн";
            case CONNECTING:
                return "Подключаюсь…";
            case UNPAIRED:
                return "Не спарено — откройте приложение";
            case OFFLINE:
            case STOPPED:
            default:
                return "Нет связи";
        }
    }

    private Notification build(SakuraClient.Status s) {
        int piFlags = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), piFlags);
        PendingIntent speak = PendingIntent.getActivity(this, 1,
                new Intent(this, MainActivity.class).setAction(MainActivity.ACTION_LISTEN)
                        .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), piFlags);
        PendingIntent off = PendingIntent.getService(this, 2,
                new Intent(this, SakuraService.class).setAction(ACTION_DISCONNECT), piFlags);
        return new NotificationCompat.Builder(this, Notifications.CHANNEL_LINK)
                .setSmallIcon(R.drawable.ic_stat_sakura)
                .setContentTitle("Сакура")
                .setContentText(stateText(s) + (listening ? " · микрофон" : ""))
                .setContentIntent(open)
                .setOngoing(true)
                .setSilent(true)
                .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
                .addAction(0, "Говорить", speak)
                .addAction(0, "Отключиться", off)
                .build();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (unsubscribe != null) {
            unsubscribe.run();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
