package app.sakura.mobile.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;

/** Каналы уведомлений: «Связь» (тихий, для службы) и «Сакура» (сообщения и phone.notify). */
public final class Notifications {
    public static final String CHANNEL_LINK = "link";
    public static final String CHANNEL_SAKURA = "sakura";
    public static final int ID_SERVICE = 1;
    public static final int ID_PERMISSION = 2;
    public static final int ID_CLIPBOARD = 3;
    public static final int ID_NOTIFY_BASE = 100;

    private Notifications() {
    }

    public static void createChannels(Context context) {
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        NotificationChannel link = new NotificationChannel(CHANNEL_LINK, "Связь", NotificationManager.IMPORTANCE_LOW);
        link.setShowBadge(false);
        nm.createNotificationChannel(link);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL_SAKURA, "Сакура",
                NotificationManager.IMPORTANCE_HIGH));
    }
}
