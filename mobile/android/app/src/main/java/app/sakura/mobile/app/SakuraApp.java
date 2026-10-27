package app.sakura.mobile.app;

import android.app.Activity;
import android.app.Application;
import android.net.ConnectivityManager;
import android.net.Network;
import android.os.Bundle;
import android.os.SystemClock;

import java.io.File;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import app.sakura.mobile.keys.DeviceKeyStore;
import app.sakura.mobile.keys.KeystoreWrapper;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.voice.ModelInstaller;
import app.sakura.mobile.voice.VoiceController;
import okhttp3.OkHttpClient;

/**
 * Одна связь на процесс. Пока открыто приложение — связь есть; в фоне — только при
 * «Всегда на связи» (тогда держит foreground-служба).
 */
public class SakuraApp extends Application {
    private static SakuraApp instance;

    private ScheduledExecutorService net;
    private OkHttpClient http;
    private DeviceKeyStore keys;
    private SakuraClient client;
    private VoiceController voice;
    private Settings settings;
    private final InputTracker input = new InputTracker();
    private int started;

    public static SakuraApp get() {
        return instance;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
        settings = new Settings(this);
        ScheduledThreadPoolExecutor ex = new ScheduledThreadPoolExecutor(1, r -> {
            Thread t = new Thread(r, "sakura-net");
            t.setDaemon(true);
            return t;
        });
        ex.setRemoveOnCancelPolicy(true);
        net = ex;
        http = new OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .pingInterval(20, TimeUnit.SECONDS)
                .build();
        keys = new DeviceKeyStore(new File(getFilesDir(), "keys"), new KeystoreWrapper());
        client = new SakuraClient(http, keys, net, SystemClock::elapsedRealtime, new AndroidDeviceInfo(this, input));
        voice = new VoiceController(this, client, settings, new ModelInstaller(new File(getFilesDir(), "vosk")));
        Notifications.createChannels(this);
        registerActivityLifecycleCallbacks(new Visibility());
        ConnectivityManager cm = getSystemService(ConnectivityManager.class);
        if (cm != null) {
            cm.registerDefaultNetworkCallback(new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    client.reconnectNow();
                }
            });
        }
        if (settings.alwaysOn()) {
            SakuraService.start(this);
        }
    }

    public SakuraClient client() {
        return client;
    }

    public VoiceController voice() {
        return voice;
    }

    public DeviceKeyStore keys() {
        return keys;
    }

    public OkHttpClient http() {
        return http;
    }

    public ScheduledExecutorService net() {
        return net;
    }

    public Settings settings() {
        return settings;
    }

    public InputTracker input() {
        return input;
    }

    public boolean inForeground() {
        return started > 0;
    }

    /** Включить или выключить «Всегда на связи». */
    public void setAlwaysOn(boolean on) {
        settings.setAlwaysOn(on);
        if (on) {
            SakuraService.start(this);
        } else {
            SakuraService.stop(this);
            if (started == 0) {
                client.stop();
            }
        }
    }

    private final class Visibility implements ActivityLifecycleCallbacks {
        @Override
        public void onActivityStarted(Activity activity) {
            if (started++ == 0) {
                client.start();
            }
        }

        @Override
        public void onActivityStopped(Activity activity) {
            if (--started == 0 && !settings.alwaysOn()) {
                client.stop();
            }
        }

        @Override
        public void onActivityCreated(Activity activity, Bundle savedInstanceState) {
        }

        @Override
        public void onActivityResumed(Activity activity) {
        }

        @Override
        public void onActivityPaused(Activity activity) {
        }

        @Override
        public void onActivitySaveInstanceState(Activity activity, Bundle outState) {
        }

        @Override
        public void onActivityDestroyed(Activity activity) {
        }
    }
}
