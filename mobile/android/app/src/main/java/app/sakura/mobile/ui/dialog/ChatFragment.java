package app.sakura.mobile.ui.dialog;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.ui.MainActivity;
import app.sakura.mobile.ui.Motion;
import app.sakura.mobile.ui.model.Models;
import app.sakura.mobile.voice.VoiceController;

/** Вкладка «Диалог»: ядро и статус, чат, поле ввода и микрофон. */
public class ChatFragment extends Fragment {
    private ChatScreen screen;
    private final Runnable levelPump = new Runnable() {
        @Override
        public void run() {
            screen.core.setLevel(SakuraApp.get().voice().level());
            screen.core.postOnAnimation(this);
        }
    };

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_dialog, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        ChatModel model = new ViewModelProvider(requireActivity()).get(ChatModel.class);
        VoiceController voice = SakuraApp.get().voice();
        MainActivity activity = (MainActivity) requireActivity();
        screen = new ChatScreen(view, new ChatScreen.Callbacks() {
            @Override
            public void send(String text) {
                model.send(text);
            }

            @Override
            public void mic() {
                activity.withMic(voice::tap);
            }

            @Override
            public void older() {
                model.older();
            }

            @Override
            public void retry() {
                model.load();
            }

            @Override
            public void search(String q) {
                model.search(q);
            }

            @Override
            public void closeSearch() {
                model.closeSearch();
            }

            @Override
            public void delete(Models.Message m) {
                new MaterialAlertDialogBuilder(requireContext())
                        .setMessage("Удалить сообщение?")
                        .setPositiveButton("Да", (d, w) -> {
                            Motion.confirm(view);
                            model.delete(m);
                        })
                        .setNegativeButton("Нет", null)
                        .show();
            }

            @Override
            public void export() {
                Intent send = new Intent(Intent.ACTION_SEND)
                        .setType("text/plain")
                        .putExtra(Intent.EXTRA_SUBJECT, "Переписка с Сакурой")
                        .putExtra(Intent.EXTRA_TEXT, model.exportText());
                startActivity(Intent.createChooser(send, "Экспорт переписки"));
            }
        });
        activity.bindCore(screen.core);
        model.state().observe(getViewLifecycleOwner(), screen::render);
        voice.state().observe(getViewLifecycleOwner(),
                s -> screen.renderCore(s, voice.transcript().getValue()));
        voice.transcript().observe(getViewLifecycleOwner(),
                t -> screen.renderCore(voice.state().getValue() == null ? CoreFrame.State.OFFLINE
                        : voice.state().getValue(), t));
    }

    @Override
    public void onStart() {
        super.onStart();
        screen.core.postOnAnimation(levelPump);
    }

    @Override
    public void onStop() {
        screen.core.removeCallbacks(levelPump);
        super.onStop();
    }
}
