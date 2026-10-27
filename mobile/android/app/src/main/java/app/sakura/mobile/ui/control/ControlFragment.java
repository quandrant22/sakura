package app.sakura.mobile.ui.control;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import app.sakura.mobile.R;

/** Вкладка «Пульт». */
public class ControlFragment extends Fragment {

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_control, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        ControlModel model = new ViewModelProvider(requireActivity()).get(ControlModel.class);
        ControlScreen screen = new ControlScreen(view, new ControlScreen.Callbacks() {
            @Override
            public void select(String deviceId) {
                model.select(deviceId);
            }

            @Override
            public void run(String action, String arg) {
                model.run(action, arg);
            }

            @Override
            public void openApp() {
                EditText name = new EditText(requireContext());
                name.setHint("Название приложения");
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle("Открыть на компьютере")
                        .setView(name)
                        .setPositiveButton("Открыть", (d, w) -> {
                            String n = name.getText().toString().trim();
                            if (!n.isEmpty()) {
                                model.run("open.app", n);
                            }
                        })
                        .setNegativeButton("Отмена", null)
                        .show();
            }

            @Override
            public void gameMode() {
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle("Игровой режим")
                        .setItems(new String[]{"Включить", "Выключить"},
                                (d, which) -> model.run(which == 0 ? "game_mode.on" : "game_mode.off", null))
                        .show();
            }

            @Override
            public void retry() {
                model.load();
            }
        });
        model.state().observe(getViewLifecycleOwner(), screen::render);
    }
}
