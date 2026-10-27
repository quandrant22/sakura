package app.sakura.mobile.ui.scenarios;

import android.view.LayoutInflater;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.Rows;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.Models;

/** Список сценариев: запуск с журналом шагов, удаление; кнопка «Создать». */
public final class ScenariosScreen {

    public interface Callbacks {
        void run(Models.Scenario s);

        void delete(Models.Scenario s);

        void create();

        void retry();
    }

    public static final class State {
        public Loadable<List<Models.Scenario>> list = Loadable.loading();
        public String journalTitle;
        public List<String> journal = new ArrayList<>();
        public String note;
    }

    private final StateView state;
    private final LinearLayout list;
    private final View journalCard;
    private final TextView journalTitle;
    private final LinearLayout journal;
    private final TextView note;
    private final Callbacks cb;

    public ScenariosScreen(View root, Callbacks cb) {
        this.cb = cb;
        state = root.findViewById(R.id.state);
        list = root.findViewById(R.id.list);
        journalCard = root.findViewById(R.id.journal_card);
        journalTitle = root.findViewById(R.id.journal_title);
        journal = root.findViewById(R.id.journal);
        note = root.findViewById(R.id.note);
        state.setEmptyText("Сценариев пока нет. Нажмите «Создать»");
        state.setSection("сценарии");
        root.findViewById(R.id.btn_create).setOnClickListener(v -> cb.create());
    }

    public void render(State s) {
        state.show(s.list, cb::retry);
        note.setVisibility(s.note == null ? View.GONE : View.VISIBLE);
        note.setText(s.note);
        journalCard.setVisibility(s.journalTitle == null ? View.GONE : View.VISIBLE);
        journalTitle.setText(s.journalTitle);
        journal.removeAllViews();
        for (String line : s.journal) {
            Rows.add(journal, line, null, null);
        }
        list.removeAllViews();
        if (s.list.data == null) {
            return;
        }
        LayoutInflater inf = LayoutInflater.from(list.getContext());
        for (Models.Scenario sc : s.list.data) {
            View card = inf.inflate(R.layout.item_scenario, list, false);
            ((TextView) card.findViewById(R.id.sc_name)).setText(sc.name + (sc.enabled ? "" : " (выключен)"));
            ((TextView) card.findViewById(R.id.sc_summary)).setText(ScenarioTypes.summary(sc));
            View del = card.findViewById(R.id.sc_delete);
            del.setVisibility(sc.builtin ? View.GONE : View.VISIBLE);
            del.setOnClickListener(v -> cb.delete(sc));
            card.findViewById(R.id.sc_run).setOnClickListener(v -> cb.run(sc));
            list.addView(card);
        }
    }
}
