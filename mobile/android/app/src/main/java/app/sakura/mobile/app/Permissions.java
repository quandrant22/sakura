package app.sakura.mobile.app;

import android.Manifest;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;

import java.util.Arrays;
import java.util.List;

/**
 * Разрешения телефона: что выдано и как выдать. Используется экраном «Разрешения» и исполнителем
 * (status unsupported «нет разрешения: …» с уведомлением-ссылкой).
 */
public final class Permissions {

    public enum Kind { MICROPHONE, NOTIFICATIONS, CAMERA, DND, OVERLAY }

    public static final class Entry {
        public final Kind kind;
        public final String title;
        public final String why;

        Entry(Kind kind, String title, String why) {
            this.kind = kind;
            this.title = title;
            this.why = why;
        }
    }

    public static final List<Entry> ALL = Arrays.asList(
            new Entry(Kind.MICROPHONE, "Микрофон", "голосовой ввод и слово «Сакура»"),
            new Entry(Kind.NOTIFICATIONS, "Уведомления", "phone.notify, буфер обмена, состояние связи"),
            new Entry(Kind.CAMERA, "Камера", "QR спаривания, «Что это?», фонарик"),
            new Entry(Kind.DND, "Режим «Не беспокоить»", "phone.dnd_on / phone.dnd_off"),
            new Entry(Kind.OVERLAY, "Поверх других окон", "плавающее ядро"));

    private Permissions() {
    }

    public static Entry entry(Kind k) {
        for (Entry e : ALL) {
            if (e.kind == k) {
                return e;
            }
        }
        throw new IllegalArgumentException(k.name());
    }

    public static boolean granted(Context c, Kind k) {
        switch (k) {
            case MICROPHONE:
                return c.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
            case NOTIFICATIONS:
                return c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
            case CAMERA:
                return c.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
            case DND: {
                NotificationManager nm = c.getSystemService(NotificationManager.class);
                return nm != null && nm.isNotificationPolicyAccessGranted();
            }
            case OVERLAY:
                return android.provider.Settings.canDrawOverlays(c);
            default:
                return false;
        }
    }

    /** Системный runtime-запрос (иначе — экран настроек через {@link #settingsIntent}). */
    public static String runtime(Kind k) {
        switch (k) {
            case MICROPHONE:
                return Manifest.permission.RECORD_AUDIO;
            case NOTIFICATIONS:
                return Manifest.permission.POST_NOTIFICATIONS;
            case CAMERA:
                return Manifest.permission.CAMERA;
            default:
                return null;
        }
    }

    public static Intent settingsIntent(Context c, Kind k) {
        switch (k) {
            case DND:
                return new Intent(android.provider.Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS);
            case OVERLAY:
                return new Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + c.getPackageName()));
            default:
                return new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + c.getPackageName()));
        }
    }
}
