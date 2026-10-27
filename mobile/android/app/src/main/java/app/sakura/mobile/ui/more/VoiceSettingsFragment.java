package app.sakura.mobile.ui.more;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.progressindicator.LinearProgressIndicator;
import com.google.android.material.slider.Slider;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.app.Settings;
import app.sakura.mobile.voice.ModelInstaller;
import app.sakura.mobile.voice.VoiceController;

/** «Ещё → Голос»: ответы текстом, слово «Сакура» (модель по кнопке), окно дослушивания 0–15 с. */
public class VoiceSettingsFragment extends Fragment {

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_voice, container, false);
    }

    /** Заполнение без зависимостей от службы (используется и снимками). */
    public static void bind(View v, Settings s, boolean modelInstalled, boolean onDevice) {
        ((MaterialSwitch) v.findViewById(R.id.text_replies)).setChecked(s.textReplies());
        MaterialSwitch wake = v.findViewById(R.id.wake_word);
        wake.setChecked(s.wakeWord() && modelInstalled);
        wake.setEnabled(modelInstalled);
        ((TextView) v.findViewById(R.id.model_status)).setText(modelInstalled
                ? "Модель vosk-model-small-ru-0.22 установлена (проверена SHA-256)"
                : "Нужна модель распознавания слова: скачивается один раз");
        v.findViewById(R.id.model_download).setVisibility(modelInstalled ? View.GONE : View.VISIBLE);
        Slider f = v.findViewById(R.id.followup);
        f.setValue(s.followupSeconds());
        label(v, s.followupSeconds());
        ((TextView) v.findViewById(R.id.recognizer)).setText(onDevice
                ? "Распознавание речи: на устройстве"
                : "Распознавание речи: системное (предпочтительно офлайн)");
    }

    static void label(View v, int sec) {
        ((TextView) v.findViewById(R.id.followup_label)).setText(sec == 0
                ? "Выключено" : "Микрофон после вопроса открыт " + sec + " с");
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        SakuraApp app = SakuraApp.get();
        Settings s = app.settings();
        VoiceController voice = app.voice();
        bind(view, s, voice.models().installed(), voice.onDeviceRecognition());
        ((MaterialSwitch) view.findViewById(R.id.text_replies))
                .setOnCheckedChangeListener((b, on) -> s.setTextReplies(on));
        ((MaterialSwitch) view.findViewById(R.id.wake_word))
                .setOnCheckedChangeListener((b, on) -> voice.setWakeWordEnabled(on));
        Slider f = view.findViewById(R.id.followup);
        f.addOnChangeListener((sl, value, fromUser) -> {
            s.setFollowupSeconds((int) value);
            label(view, (int) value);
        });
        LinearProgressIndicator progress = view.findViewById(R.id.model_progress);
        TextView status = view.findViewById(R.id.model_status);
        view.findViewById(R.id.model_download).setOnClickListener(b -> {
            b.setEnabled(false);
            progress.setVisibility(View.VISIBLE);
            progress.setMax(100);
            voice.installModel(app.http(), (done, total) -> view.post(() ->
                            progress.setProgress((int) (100 * done / Math.max(1, ModelInstaller.SIZE)))),
                    err -> {
                        progress.setVisibility(View.GONE);
                        b.setEnabled(true);
                        if (err == null) {
                            bind(view, s, true, voice.onDeviceRecognition());
                        } else {
                            status.setText(err);
                        }
                    });
        });
    }
}
