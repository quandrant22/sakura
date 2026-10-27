package app.sakura.mobile.ui.summary;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import app.sakura.mobile.R;

/** Вкладка «Сводка». */
public class SummaryFragment extends Fragment {
    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_summary, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        SummaryModel model = new ViewModelProvider(requireActivity()).get(SummaryModel.class);
        SummaryScreen screen = new SummaryScreen(view, model::load);
        model.state().observe(getViewLifecycleOwner(), screen::render);
    }
}
