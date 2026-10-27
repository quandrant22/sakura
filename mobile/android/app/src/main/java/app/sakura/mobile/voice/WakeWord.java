package app.sakura.mobile.voice;

import android.content.Context;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.audiofx.AcousticEchoCanceler;

import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;
import org.vosk.android.RecognitionListener;
import org.vosk.android.SpeechService;

import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Слово «Сакура» на Vosk (vosk-model-small-ru-0.22, грамматика из одного слова). Работает только
 * при открытом приложении; во время озвучки — только при AcousticEchoCanceler или гарнитуре.
 * Модель грузится и распознаётся вне main thread; колбэк — в main thread.
 */
public final class WakeWord {
    static final String GRAMMAR = "[\"сакура\", \"[unk]\"]";

    public interface Listener {
        void onWake();
    }

    private final Context context;
    private final ModelInstaller installer;
    private final Listener listener;
    private final ExecutorService loader = Executors.newSingleThreadExecutor(r -> new Thread(r, "sakura-vosk"));
    private Model model;
    private SpeechService service;
    private boolean wanted;
    private boolean paused;

    public WakeWord(Context context, ModelInstaller installer, Listener listener) {
        this.context = context.getApplicationContext();
        this.installer = installer;
        this.listener = listener;
    }

    /** Можно ли слушать слово во время речи Сакуры (иначе слышит сама себя). */
    public boolean allowedDuringSpeech() {
        return AcousticEchoCanceler.isAvailable() || headset(context);
    }

    static boolean headset(Context context) {
        AudioManager am = context.getSystemService(AudioManager.class);
        if (am == null) {
            return false;
        }
        for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
            switch (d.getType()) {
                case AudioDeviceInfo.TYPE_WIRED_HEADSET:
                case AudioDeviceInfo.TYPE_WIRED_HEADPHONES:
                case AudioDeviceInfo.TYPE_BLUETOOTH_A2DP:
                case AudioDeviceInfo.TYPE_BLUETOOTH_SCO:
                case AudioDeviceInfo.TYPE_BLE_HEADSET:
                case AudioDeviceInfo.TYPE_USB_HEADSET:
                    return true;
                default:
            }
        }
        return false;
    }

    /** Включить (только из открытого приложения). */
    public void start() {
        wanted = true;
        paused = false;
        if (!installer.installed()) {
            return;
        }
        loader.execute(() -> {
            try {
                if (model == null) {
                    model = new Model(installer.modelDir().getAbsolutePath());
                }
                Recognizer rec = new Recognizer(model, 16000.0f, GRAMMAR);
                synchronized (this) {
                    if (!wanted || service != null) {
                        rec.close();
                        return;
                    }
                    service = new SpeechService(rec, 16000.0f);
                    service.startListening(new Bridge());
                }
            } catch (IOException | RuntimeException e) {
                stop();
            }
        });
    }

    public synchronized void stop() {
        wanted = false;
        if (service != null) {
            service.stop();
            service.shutdown();
            service = null;
        }
    }

    /** Микрофон нужен распознаванию — Vosk отпускает его. */
    public synchronized void pause(boolean on) {
        paused = on;
        if (service != null) {
            service.setPause(on);
        }
    }

    public synchronized boolean running() {
        return service != null && !paused;
    }

    static boolean hasWord(String json) {
        if (json == null) {
            return false;
        }
        try {
            JSONObject o = new JSONObject(json);
            String t = o.optString("text", o.optString("partial", ""));
            return t.contains("сакура");
        } catch (Exception e) {
            return json.contains("сакура");
        }
    }

    private final class Bridge implements RecognitionListener {
        @Override
        public void onPartialResult(String hypothesis) {
            if (hasWord(hypothesis)) {
                fire();
            }
        }

        @Override
        public void onResult(String hypothesis) {
            if (hasWord(hypothesis)) {
                fire();
            }
        }

        @Override
        public void onFinalResult(String hypothesis) {
        }

        @Override
        public void onError(Exception exception) {
            stop();
        }

        @Override
        public void onTimeout() {
        }

        private void fire() {
            synchronized (WakeWord.this) {
                if (paused) {
                    return;
                }
            }
            listener.onWake();
        }
    }
}
