package app.sakura.mobile.exec;

import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.AlarmClock;
import android.view.KeyEvent;

import androidx.core.app.NotificationCompat;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import app.sakura.mobile.R;
import app.sakura.mobile.app.Notifications;
import app.sakura.mobile.app.Permissions;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.ui.MainActivity;

/** PhoneApis на Android API. Вызывается из потока исполнителя («sakura-exec»). */
public final class AndroidPhoneApis implements PhoneApis {
    private static final AtomicInteger NOTIFY_ID = new AtomicInteger(Notifications.ID_NOTIFY_BASE);

    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private MediaPlayer ringing;
    private int savedAlarmVolume = -1;

    public AndroidPhoneApis(Context context) {
        this.context = context.getApplicationContext();
    }

    private static Missing missing(Permissions.Kind k) {
        return new Missing(Permissions.entry(k).title);
    }

    /** Запуск чужой активности из фона Android разрешает только видимому приложению или с «поверх окон». */
    private void checkCanStartActivity() throws Missing {
        SakuraApp app = SakuraApp.get();
        boolean foreground = app != null && app.inForeground();
        if (!foreground && !Permissions.granted(context, Permissions.Kind.OVERLAY)) {
            throw missing(Permissions.Kind.OVERLAY);
        }
    }

    private void start(Intent i) throws Missing, Failed {
        checkCanStartActivity();
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (i.resolveActivity(context.getPackageManager()) == null) {
            throw new Failed("нет приложения для этого действия");
        }
        try {
            context.startActivity(i);
        } catch (RuntimeException e) {
            throw new Failed("система не дала открыть");
        }
    }

    /** Действие, которому нужен main thread (буфер обмена, MediaPlayer). */
    private void onMain(Runnable r) throws Failed {
        CountDownLatch done = new CountDownLatch(1);
        RuntimeException[] err = new RuntimeException[1];
        main.post(() -> {
            try {
                r.run();
            } catch (RuntimeException e) {
                err[0] = e;
            } finally {
                done.countDown();
            }
        });
        try {
            if (!done.await(5, TimeUnit.SECONDS) || err[0] != null) {
                throw new Failed("не получилось");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new Failed("прервано");
        }
    }

    @Override
    public void ring(int seconds) throws Failed {
        AudioManager am = context.getSystemService(AudioManager.class);
        Uri uri = RingtoneManager.getActualDefaultRingtoneUri(context, RingtoneManager.TYPE_ALARM);
        if (uri == null) {
            uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
        }
        Uri sound = uri;
        onMain(() -> {
            stopRinging();
            if (am != null) {
                savedAlarmVolume = am.getStreamVolume(AudioManager.STREAM_ALARM);
                am.setStreamVolume(AudioManager.STREAM_ALARM, am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
            }
            MediaPlayer p = new MediaPlayer();
            try {
                p.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                p.setDataSource(context, sound);
                p.setLooping(true);
                p.prepare();
                p.start();
            } catch (java.io.IOException | RuntimeException e) {
                p.release();
                throw new IllegalStateException(e);
            }
            ringing = p;
            main.postAtTime(this::stopRinging, SystemClock.uptimeMillis() + seconds * 1000L);
        });
    }

    private void stopRinging() {
        if (ringing != null) {
            ringing.stop();
            ringing.release();
            ringing = null;
        }
        AudioManager am = context.getSystemService(AudioManager.class);
        if (am != null && savedAlarmVolume >= 0) {
            am.setStreamVolume(AudioManager.STREAM_ALARM, savedAlarmVolume, 0);
            savedAlarmVolume = -1;
        }
    }

    @Override
    public void dnd(boolean on) throws Missing {
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm == null || !nm.isNotificationPolicyAccessGranted()) {
            throw missing(Permissions.Kind.DND);
        }
        nm.setInterruptionFilter(on ? NotificationManager.INTERRUPTION_FILTER_PRIORITY
                : NotificationManager.INTERRUPTION_FILTER_ALL);
    }

    @Override
    public void alarm(int hour, int minute) throws Missing, Failed {
        start(new Intent(AlarmClock.ACTION_SET_ALARM)
                .putExtra(AlarmClock.EXTRA_HOUR, hour)
                .putExtra(AlarmClock.EXTRA_MINUTES, minute)
                .putExtra(AlarmClock.EXTRA_MESSAGE, "Сакура")
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true));
    }

    @Override
    public void timer(int seconds) throws Missing, Failed {
        start(new Intent(AlarmClock.ACTION_SET_TIMER)
                .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
                .putExtra(AlarmClock.EXTRA_MESSAGE, "Сакура")
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true));
    }

    @Override
    public boolean torch(boolean on) throws Failed {
        CameraManager cm = context.getSystemService(CameraManager.class);
        if (cm == null) {
            return false;
        }
        try {
            for (String id : cm.getCameraIdList()) {
                Boolean flash = cm.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                if (Boolean.TRUE.equals(flash)) {
                    cm.setTorchMode(id, on);
                    return true;
                }
            }
        } catch (CameraAccessException | IllegalArgumentException e) {
            throw new Failed("камера занята");
        }
        return false;
    }

    @Override
    public void volume(int percent) throws Missing {
        AudioManager am = context.getSystemService(AudioManager.class);
        if (am == null) {
            return;
        }
        int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        try {
            am.setStreamVolume(AudioManager.STREAM_MUSIC, Math.round(max * percent / 100f), 0);
        } catch (SecurityException e) {
            throw missing(Permissions.Kind.DND);
        }
    }

    @Override
    public void clipboard(String text) throws Failed {
        onMain(() -> {
            ClipboardManager cm = context.getSystemService(ClipboardManager.class);
            if (cm == null) {
                throw new IllegalStateException();
            }
            cm.setPrimaryClip(ClipData.newPlainText("Сакура", text));
        });
        if (Permissions.granted(context, Permissions.Kind.NOTIFICATIONS)) {
            post(Notifications.ID_CLIPBOARD, "Скопировано с компьютера",
                    text.length() > 60 ? text.substring(0, 60) + "…" : text, null);
        }
    }

    @Override
    public void openUrl(String url) throws Missing, Failed {
        start(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
    }

    @Override
    public List<App> launchableApps() {
        PackageManager pm = context.getPackageManager();
        Intent i = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<App> out = new ArrayList<>();
        for (ResolveInfo r : pm.queryIntentActivities(i, 0)) {
            out.add(new App(String.valueOf(r.loadLabel(pm)), r.activityInfo.packageName));
        }
        return out;
    }

    @Override
    public void launch(App app) throws Missing, Failed {
        Intent i = context.getPackageManager().getLaunchIntentForPackage(app.pkg);
        if (i == null) {
            throw new Failed("приложение не запускается");
        }
        start(i);
    }

    @Override
    public void mediaKey(int keyCode) {
        AudioManager am = context.getSystemService(AudioManager.class);
        if (am == null) {
            return;
        }
        am.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, keyCode));
        am.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, keyCode));
    }

    @Override
    public void notify(String text) throws Missing {
        if (!Permissions.granted(context, Permissions.Kind.NOTIFICATIONS)) {
            throw missing(Permissions.Kind.NOTIFICATIONS);
        }
        post(NOTIFY_ID.getAndIncrement(), "Сакура", text, null);
    }

    @Override
    public void notifyMissing(String title) {
        if (!Permissions.granted(context, Permissions.Kind.NOTIFICATIONS)) {
            return;
        }
        PendingIntent open = PendingIntent.getActivity(context, 3,
                new Intent(context, MainActivity.class).setAction(MainActivity.ACTION_PERMISSIONS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        post(Notifications.ID_PERMISSION, "Сакуре нужно разрешение", "Нет разрешения: " + title + " — нажмите, чтобы выдать",
                open);
    }

    private void post(int id, String title, String text, PendingIntent click) {
        NotificationManager nm = context.getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        NotificationCompat.Builder b = new NotificationCompat.Builder(context, Notifications.CHANNEL_SAKURA)
                .setSmallIcon(R.drawable.ic_stat_sakura)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(text))
                .setAutoCancel(true);
        if (click != null) {
            b.setContentIntent(click);
        }
        nm.notify(id, b.build());
    }
}
