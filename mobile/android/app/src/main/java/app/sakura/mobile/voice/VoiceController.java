package app.sakura.mobile.voice;

import android.content.Context;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import org.json.JSONObject;

import app.sakura.mobile.app.SakuraService;
import app.sakura.mobile.app.Settings;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.SakuraClient;

/**
 * Голос телефона: распознавание → voice_command, озвучка tts_chunk/tts_end, состояния ядра
 * (Онлайн / Слушаю / Думаю / Говорю / Нет связи), перебивание, дослушивание, «Ответы текстом»,
 * слово «Сакура». Все публичные методы — main thread.
 */
public final class VoiceController implements SpeechInput.Listener, PlaybackController.Listener, WakeWord.Listener {
    static final long THINKING_TIMEOUT_MS = 20_000;

    private final Context context;
    private final SakuraClient client;
    private final Settings settings;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final SpeechInput input;
    private final Player player;
    private final WakeWord wake;
    private final ModelInstaller models;

    private final MutableLiveData<CoreFrame.State> state = new MutableLiveData<>(CoreFrame.State.OFFLINE);
    private final MutableLiveData<String> transcript = new MutableLiveData<>("");
    private volatile float level;

    private boolean online;
    private boolean speaking;
    private boolean thinking;
    private boolean foreground;
    private boolean followUpOpen;
    private boolean confirmPending;
    private String lastKind;
    private String lastText;
    private final Runnable thinkingTimeout = () -> {
        thinking = false;
        publish();
    };
    private final Runnable followUpTimeout = this::closeFollowUp;

    private void closeFollowUp() {
        if (followUpOpen) {
            followUpOpen = false;
            input.cancel();
        }
    }

    public VoiceController(Context context, SakuraClient client, Settings settings, ModelInstaller models) {
        this.context = context.getApplicationContext();
        this.client = client;
        this.settings = settings;
        this.models = models;
        this.input = new SpeechInput(context, this);
        this.player = new Player(context, this);
        this.wake = new WakeWord(context, models, this);
        client.onStatus(s -> main.post(() -> {
            online = s.conn == SakuraClient.Conn.ONLINE;
            publish();
        }));
        client.bus().subscribe("tts_chunk", m -> player.chunk(Json.optStr(m, "turn_id"),
                m.optString("audio", m.optString("data", "")), m.optInt("sample_rate", PlaybackController.DEFAULT_RATE)));
        client.bus().subscribe("tts_end", m -> player.end(Json.optStr(m, "turn_id"), m.optBoolean("listen", false)));
        client.bus().subscribe("reply", m -> main.post(() -> onReply(m)));
    }

    public LiveData<CoreFrame.State> state() {
        return state;
    }

    public LiveData<String> transcript() {
        return transcript;
    }

    /** Уровень звука для ядра (микрофон или озвучка). */
    public float level() {
        return level;
    }

    public ModelInstaller models() {
        return models;
    }

    public int playbackGaps() {
        return player.gaps();
    }

    public boolean onDeviceRecognition() {
        return input.onDevice();
    }

    private void publish() {
        CoreFrame.State s;
        if (input.listening()) {
            s = CoreFrame.State.LISTENING;
        } else if (speaking) {
            s = CoreFrame.State.SPEAKING;
        } else if (thinking) {
            s = CoreFrame.State.THINKING;
        } else if (!online) {
            s = CoreFrame.State.OFFLINE;
        } else {
            s = CoreFrame.State.IDLE;
        }
        if (state.getValue() != s) {
            state.setValue(s);
        }
    }

    /** «Ответы текстом» вручную или беззвучный режим телефона → speak:false. */
    public boolean speakReplies() {
        if (settings.textReplies()) {
            return false;
        }
        AudioManager am = context.getSystemService(AudioManager.class);
        return am == null || am.getRingerMode() == AudioManager.RINGER_MODE_NORMAL;
    }

    // ── вход ──

    /** Приложение на экране: можно слушать «Сакура», работает кнопка гарнитуры. */
    public void setForeground(boolean on) {
        foreground = on;
        if (on && settings.wakeWord()) {
            wake.start();
        } else if (!on) {
            wake.stop();
            input.cancel();
            followUpOpen = false;
        }
    }

    public void setWakeWordEnabled(boolean on) {
        settings.setWakeWord(on);
        if (on && foreground) {
            wake.start();
        } else {
            wake.stop();
        }
    }

    /** Тап по ядру / кнопка / плитка: перебить озвучку и слушать; повторный тап — стоп. */
    public void tap() {
        if (input.listening()) {
            input.finish();
            return;
        }
        if (speaking) {
            interrupt();
        }
        listen();
    }

    /** Удержание (PTT): начать. */
    public void pttDown() {
        if (speaking) {
            interrupt();
        }
        listen();
    }

    /** Удержание отпущено: дождаться финала распознавания. */
    public void pttUp() {
        input.finish();
    }

    public void interrupt() {
        player.interrupt();
    }

    private void listen() {
        if (!foreground) {
            return;   // микрофон — только из открытого приложения (D18)
        }
        main.removeCallbacks(followUpTimeout);
        wake.pause(true);
        SakuraService.setListening(context, true);
        transcript.setValue("");
        input.start();
        publish();
    }

    /** Текст из поля ввода: voice_command channel:"text". */
    public void sendText(String text) {
        startThinking();
        client.voice(text, "text", speakReplies(), confirmPending, null);
        confirmPending = false;
    }

    /** Ответ кнопкой на kind:"confirm": «да»/«нет», channel:"text", не в outbox. */
    public void answerConfirm(boolean yes) {
        confirmPending = false;
        followUpOpen = false;
        input.cancel();
        startThinking();
        client.voice(FollowUp.confirmWord(yes), "text", speakReplies(), true, null);
    }

    /** Реплика ушла из чата (chat_send) — ядро «думает» до ответа. */
    public void markThinking() {
        startThinking();
    }

    /** Ответ на вопрос confirm ещё ждёт — следующая реплика считается ответом на него. */
    public boolean confirmPending() {
        return confirmPending;
    }

    private void startThinking() {
        thinking = true;
        main.removeCallbacks(thinkingTimeout);
        main.postDelayed(thinkingTimeout, THINKING_TIMEOUT_MS);
        publish();
    }

    // ── SpeechInput.Listener ──

    @Override
    public void onListening(boolean on) {
        if (!on) {
            SakuraService.setListening(context, false);
            wake.pause(false);
        }
        publish();
    }

    @Override
    public void onPartial(String text) {
        transcript.setValue(text);
    }

    @Override
    public void onFinal(String text) {
        followUpOpen = false;
        transcript.setValue(text);
        startThinking();
        client.voice(text, "voice", speakReplies(), confirmPending, null);
        confirmPending = false;
    }

    @Override
    public void onLevel(float l) {
        level = l;
    }

    @Override
    public void onNothing(int error) {
        followUpOpen = false;
        publish();
    }

    @Override
    public void onSpeechBegan() {
        main.removeCallbacks(followUpTimeout);
    }

    // ── сервер ──

    private void onReply(JSONObject m) {
        lastKind = m.optString("kind", "llm");
        lastText = m.optString("text", "");
        if ("confirm".equals(lastKind)) {
            confirmPending = true;
        }
        thinking = false;
        main.removeCallbacks(thinkingTimeout);
        if (!speaking && !player.active()) {
            // без озвучки (speak:false) — дослушивание сразу после ответа
            maybeFollowUp(false);
        }
        publish();
    }

    // ── PlaybackController.Listener (аудиопоток) ──

    @Override
    public void onSpeaking(boolean on) {
        main.post(() -> {
            speaking = on;
            if (on) {
                thinking = false;
                main.removeCallbacks(thinkingTimeout);
                if (!wake.allowedDuringSpeech()) {
                    wake.pause(true);
                }
            } else if (!input.listening()) {
                wake.pause(false);
            }
            publish();
        });
    }

    @Override
    public void onFinished(String turnId, boolean listen, boolean stalled) {
        main.post(() -> {
            speaking = false;
            maybeFollowUp(listen);
            publish();
        });
    }

    private void maybeFollowUp(boolean serverAsked) {
        long window = FollowUp.windowMs(settings.followupSeconds());
        if (window == 0 || !foreground || input.listening()) {
            return;
        }
        if (serverAsked || FollowUp.isQuestion(lastKind, lastText)) {
            lastKind = null;
            lastText = null;
            followUpOpen = true;
            listen();
            main.postDelayed(followUpTimeout, window);
        }
    }

    // ── WakeWord.Listener ──

    @Override
    public void onWake() {
        if (!foreground) {
            return;
        }
        if (speaking) {
            interrupt();
        }
        listen();
    }

    /**
     * Скачать модель «Сакура» по кнопке: проверка SHA-256 до распаковки. Колбэк — main thread:
     * null — успех, иначе текст ошибки.
     */
    public void installModel(okhttp3.OkHttpClient http, ModelInstaller.Progress progress,
                             java.util.function.Consumer<String> done) {
        new Thread(() -> {
            String err = null;
            okhttp3.Request req = new okhttp3.Request.Builder().url(ModelInstaller.URL).build();
            try (okhttp3.Response r = http.newCall(req).execute()) {
                if (!r.isSuccessful() || r.body() == null) {
                    err = "не удалось скачать модель (" + r.code() + ")";
                } else {
                    java.io.File zip = models.download(r.body().byteStream(), ModelInstaller.SHA256, progress);
                    models.unpack(zip);
                }
            } catch (java.io.IOException e) {
                err = "нет связи для загрузки модели";
            } catch (ModelInstaller.ModelException e) {
                err = e.getMessage();
            }
            String result = err;
            main.post(() -> {
                if (result == null && foreground && settings.wakeWord()) {
                    wake.start();
                }
                done.accept(result);
            });
        }, "sakura-model").start();
    }

    public void release() {
        wake.stop();
        input.destroy();
    }
}
