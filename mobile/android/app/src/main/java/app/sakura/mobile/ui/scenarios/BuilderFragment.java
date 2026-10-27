package app.sakura.mobile.ui.scenarios;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.model.ActionCatalog;
import app.sakura.mobile.ui.model.Models;

/** Конструктор сценария (открывается поверх вкладки «Сценарии»). */
public class BuilderFragment extends Fragment {
    private String lastPhrase;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_scenario_builder, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        ScenariosModel model = new ViewModelProvider(requireActivity()).get(ScenariosModel.class);
        BuilderScreen[] screen = new BuilderScreen[1];
        screen[0] = new BuilderScreen(view, ActionCatalog.get(requireContext()), new BuilderScreen.Callbacks() {
            @Override
            public void preview(String phrase) {
                lastPhrase = phrase;
                model.fromText(phrase, (l, w) -> view.post(() ->
                        screen[0].renderPreview(l, w, () -> preview(lastPhrase))));
            }

            @Override
            public void save(Models.Scenario s) {
                model.save(s, err -> view.post(() -> {
                    if (err == null) {
                        requireActivity().getOnBackPressedDispatcher().onBackPressed();
                    } else {
                        screen[0].showNote(err);
                    }
                }));
            }
        });
    }
}
