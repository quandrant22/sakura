package app.sakura.mobile.assistant;

import android.content.Intent;
import android.os.Bundle;
import android.os.RemoteException;
import android.speech.RecognitionListener;
import android.speech.RecognitionService;
import android.speech.SpeechRecognizer;

/**
 * RecognitionService, обязательный для VoiceInteractionService: пересылает в системное
 * распознавание на устройстве (createOnDeviceSpeechRecognizer), своих моделей нет.
 */
public class SakuraRecognitionService extends RecognitionService {
    private SpeechRecognizer delegate;

    @Override
    protected void onStartListening(Intent recognizerIntent, Callback listener) {
        if (!SpeechRecognizer.isOnDeviceRecognitionAvailable(this)) {
            error(listener, SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE);
            return;
        }
        if (delegate == null) {
            delegate = SpeechRecognizer.createOnDeviceSpeechRecognizer(this);
        }
        delegate.setRecognitionListener(new RecognitionListener() {
            @Override
            public void onReadyForSpeech(Bundle params) {
                call(() -> listener.readyForSpeech(params));
            }

            @Override
            public void onBeginningOfSpeech() {
                call(listener::beginningOfSpeech);
            }

            @Override
            public void onRmsChanged(float rmsdB) {
                call(() -> listener.rmsChanged(rmsdB));
            }

            @Override
            public void onBufferReceived(byte[] buffer) {
                call(() -> listener.bufferReceived(buffer));
            }

            @Override
            public void onEndOfSpeech() {
                call(listener::endOfSpeech);
            }

            @Override
            public void onError(int error) {
                error(listener, error);
            }

            @Override
            public void onResults(Bundle results) {
                call(() -> listener.results(results));
            }

            @Override
            public void onPartialResults(Bundle partialResults) {
                call(() -> listener.partialResults(partialResults));
            }

            @Override
            public void onEvent(int eventType, Bundle params) {
            }
        });
        delegate.startListening(recognizerIntent);
    }

    private interface Remote {
        void run() throws RemoteException;
    }

    private static void call(Remote r) {
        try {
            r.run();
        } catch (RemoteException ignored) {
            // клиент ушёл
        }
    }

    private static void error(Callback listener, int code) {
        call(() -> listener.error(code));
    }

    @Override
    protected void onCancel(Callback listener) {
        if (delegate != null) {
            delegate.cancel();
        }
    }

    @Override
    protected void onStopListening(Callback listener) {
        if (delegate != null) {
            delegate.stopListening();
        }
    }

    @Override
    public void onDestroy() {
        if (delegate != null) {
            delegate.destroy();
            delegate = null;
        }
        super.onDestroy();
    }
}
