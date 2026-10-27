package app.sakura.mobile.ui.more;

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
import app.sakura.mobile.ui.Motion;
import app.sakura.mobile.ui.model.Models;

/** «Ещё → Память». ViewModel привязан к фрагменту — данные не переживают закрытия экрана. */
public class MemoryFragment extends Fragment {
    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_memory, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        MemoryModel model = new ViewModelProvider(this).get(MemoryModel.class);
        MemoryScreen screen = new MemoryScreen(view, new MemoryScreen.Callbacks() {
            @Override
            public void category(String c) {
                model.category(c);
            }

            @Override
            public void search(String q) {
                model.search(q);
            }

            @Override
            public void edit(Models.MemoryItem item) {
                EditText field = new EditText(requireContext());
                field.setText(item.text);
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle("Изменить запись")
                        .setView(field)
                        .setPositiveButton("Сохранить", (d, w) -> {
                            String t = field.getText().toString().trim();
                            if (!t.isEmpty() && !t.equals(item.text)) {
                                model.edit(item, t);
                            }
                        })
                        .setNegativeButton("Отмена", null)
                        .show();
            }

            @Override
            public void delete(Models.MemoryItem item) {
                new MaterialAlertDialogBuilder(requireContext())
                        .setMessage("Удалить из памяти?\n\n" + item.text)
                        .setPositiveButton("Да", (d, w) -> {
                            Motion.confirm(view);
                            model.delete(item);
                        })
                        .setNegativeButton("Нет", null)
                        .show();
            }

            @Override
            public void retry() {
                model.load();
            }
        });
        model.state().observe(getViewLifecycleOwner(), screen::render);
        if (savedInstanceState == null) {
            model.load();
        }
    }
}
