package app.sakura.mobile.ui.scenarios;

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
import app.sakura.mobile.ui.MainActivity;
import app.sakura.mobile.ui.Motion;
import app.sakura.mobile.ui.model.Models;

/** Вкладка «Сценарии». */
public class ScenariosFragment extends Fragment {
    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_scenarios, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        ScenariosModel model = new ViewModelProvider(requireActivity()).get(ScenariosModel.class);
        ScenariosScreen screen = new ScenariosScreen(view, new ScenariosScreen.Callbacks() {
            @Override
            public void run(Models.Scenario s) {
                model.run(s);
            }

            @Override
            public void delete(Models.Scenario s) {
                new MaterialAlertDialogBuilder(requireContext())
                        .setMessage("Удалить сценарий «" + s.name + "»?")
                        .setPositiveButton("Да", (d, w) -> {
                            Motion.confirm(view);
                            model.delete(s);
                        })
                        .setNegativeButton("Нет", null)
                        .show();
            }

            @Override
            public void create() {
                ((MainActivity) requireActivity()).push(new BuilderFragment());
            }

            @Override
            public void retry() {
                model.load();
            }
        });
        model.state().observe(getViewLifecycleOwner(), screen::render);
    }
}
