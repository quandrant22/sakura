package app.sakura.mobile.ui.more;

import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.Rows;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.Models;

/** «Память»: категории (counts), поиск, правка по тапу, удаление по долгому нажатию. */
public final class MemoryScreen {

    public interface Callbacks {
        void category(String c);

        void search(String q);

        void edit(Models.MemoryItem item);

        void delete(Models.MemoryItem item);

        void retry();
    }

    public static final class State {
        public Loadable<List<Models.MemoryItem>> items = Loadable.loading();
        public Map<String, Integer> counts = new LinkedHashMap<>();
        public String category;
        public String note;
    }

    private final StateView state;
    private final ChipGroup chips;
    private final LinearLayout items;
    private final TextView note;
    private final Callbacks cb;

    public MemoryScreen(View root, Callbacks cb) {
        this.cb = cb;
        state = root.findViewById(R.id.state);
        chips = root.findViewById(R.id.categories);
        items = root.findViewById(R.id.items);
        note = root.findViewById(R.id.note);
        EditText q = root.findViewById(R.id.query);
        state.setEmptyText("В памяти пока ничего нет");
        state.setSection("память");
        root.findViewById(R.id.search).setOnClickListener(v -> cb.search(q.getText().toString().trim()));
        q.setOnEditorActionListener((v, id, e) -> {
            cb.search(q.getText().toString().trim());
            return true;
        });
    }

    static String categoryLabel(String c) {
        switch (c) {
            case "preferences":
                return "Предпочтения";
            case "facts":
                return "Факты";
            case "bookmarks":
                return "Закладки";
            case "people":
                return "Люди";
            default:
                return c;
        }
    }

    public void render(State s) {
        state.show(s.items, cb::retry);
        note.setVisibility(s.note == null ? View.GONE : View.VISIBLE);
        note.setText(s.note);
        chips.removeAllViews();
        addChip(null, "Все", s.category == null);
        for (Map.Entry<String, Integer> e : s.counts.entrySet()) {
            addChip(e.getKey(), categoryLabel(e.getKey()) + " " + e.getValue(), e.getKey().equals(s.category));
        }
        items.removeAllViews();
        if (s.items.data == null) {
            return;
        }
        for (Models.MemoryItem it : s.items.data) {
            View row = Rows.add(items, it.text, categoryLabel(it.category), null);
            row.setOnClickListener(v -> cb.edit(it));
            row.setOnLongClickListener(v -> {
                cb.delete(it);
                return true;
            });
        }
    }

    private void addChip(String id, String label, boolean checked) {
        Chip c = new Chip(chips.getContext());
        c.setText(label);
        c.setCheckable(true);
        c.setChecked(checked);
        c.setOnClickListener(v -> cb.category(id));
        chips.addView(c);
    }
}
