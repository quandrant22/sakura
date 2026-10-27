package app.sakura.mobile.voice;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;

import java.util.ArrayList;

/**
 * Распознавание ru-RU: createOnDeviceSpeechRecognizer, если доступен; иначе обычный с
 * EXTRA_PREFER_OFFLINE. Только main thread (требование SpeechRecognizer).
 */
public final class SpeechInput {

    public interface Listener {
        void onListening(boolean on);

        void onPartial(String text);

        void onFinal(String text);

        void onLevel(float level);

        /** Речь так и не началась / ошибка — text null. */
        void onNothing(int error);

        void onSpeechBegan();
    }

    private final Context context;
    private final Listener listener;
    private SpeechRecognizer recognizer;
    private boolean onDevice;
    private boolean listening;

    public SpeechInput(Context context, Listener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
    }

    public boolean listening() {
        return listening;
    }

    public boolean onDevice() {
        return onDevice;
    }

    private SpeechRecognizer recognizer() {
        if (recognizer == null) {
            onDevice = SpeechRecognizer.isOnDeviceRecognitionAvailable(context);
            recognizer = onDevice ? SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
                    : SpeechRecognizer.createSpeechRecognizer(context);
            recognizer.setRecognitionListener(new Bridge());
        }
        return recognizer;
    }

    public void start() {
        if (listening) {
            return;
        }
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        SpeechRecognizer r = recognizer();
        if (!onDevice) {
            i.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true);
        }
        listening = true;
        listener.onListening(true);
        r.startListening(i);
    }

    /** Отпустили PTT: дождаться финального результата. */
    public void finish() {
        if (listening && recognizer != null) {
            recognizer.stopListening();
        }
    }

    public void cancel() {
        if (recognizer != null && listening) {
            recognizer.cancel();
        }
        done();
    }

    public void destroy() {
        cancel();
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
    }

    private void done() {
        if (listening) {
            listening = false;
            listener.onLevel(0);
            listener.onListening(false);
        }
    }

    private static String first(Bundle b) {
        ArrayList<String> r = b == null ? null : b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        return r == null || r.isEmpty() ? null : r.get(0);
    }

    private final class Bridge implements RecognitionListener {
        @Override
        public void onReadyForSpeech(Bundle params) {
        }

        @Override
        public void onBeginningOfSpeech() {
            listener.onSpeechBegan();
        }

        @Override
        public void onRmsChanged(float rmsdB) {
            // типично −2…10 дБ → 0..1
            listener.onLevel(Math.max(0, Math.min(1, (rmsdB + 2) / 12f)));
        }

        @Override
        public void onBufferReceived(byte[] buffer) {
        }

        @Override
        public void onEndOfSpeech() {
        }

        @Override
        public void onError(int error) {
            done();
            listener.onNothing(error);
        }

        @Override
        public void onResults(Bundle results) {
            String t = first(results);
            done();
            if (t == null || t.trim().isEmpty()) {
                listener.onNothing(SpeechRecognizer.ERROR_NO_MATCH);
            } else {
                listener.onFinal(t.trim());
            }
        }

        @Override
        public void onPartialResults(Bundle partialResults) {
            String t = first(partialResults);
            if (t != null) {
                listener.onPartial(t);
            }
        }

        @Override
        public void onEvent(int eventType, Bundle params) {
        }
    }
}
