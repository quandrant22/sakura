package app.sakura.mobile.ui.dialog;

import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.TextView;

import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.Collections;
import java.util.List;
import java.util.function.Consumer;

import app.sakura.mobile.R;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.Models;

/** Разметка и отрисовка «Диалога» без зависимости от связи (используется и в снимках). */
public final class ChatScreen {

    public interface Callbacks {
        void send(String text);

        void mic();

        void older();

        void retry();

        void search(String q);

        void closeSearch();

        void delete(Models.Message m);

        void export();
    }

    /** Что показывать. found != null — режим результатов поиска. */
    public static final class State {
        public Loadable<List<Models.Message>> messages = Loadable.loading();
        public boolean hasMore;
        public List<Models.Message> found;
        public CoreFrame.State core = CoreFrame.State.OFFLINE;
        public String transcript = "";
        public String note;
        public boolean animateNew;
    }

    public final SakuraCoreView core;
    private final TextView status;
    private final TextView transcript;
    private final TextView note;
    private final View searchBar;
    private final EditText searchQuery;
    private final StateView state;
    private final RecyclerView list;
    private final EditText input;
    private final ChatAdapter adapter = new ChatAdapter();

    public ChatScreen(View root, Callbacks cb) {
        core = root.findViewById(R.id.core);
        status = root.findViewById(R.id.core_status);
        transcript = root.findViewById(R.id.transcript);
        note = root.findViewById(R.id.note);
        searchBar = root.findViewById(R.id.search_bar);
        searchQuery = root.findViewById(R.id.search_query);
        state = root.findViewById(R.id.state);
        list = root.findViewById(R.id.messages);
        input = root.findViewById(R.id.input);
        state.setEmptyText("Здесь будет ваша переписка. Напишите или скажите «Сакура…»");
        state.setSection("историю переписки");
        LinearLayoutManager lm = new LinearLayoutManager(root.getContext());
        lm.setStackFromEnd(true);
        list.setLayoutManager(lm);
        list.setAdapter(adapter);
        adapter.setCallbacks(cb::older, cb::delete);
        root.findViewById(R.id.btn_send).setOnClickListener(v -> submit(cb));
        input.setOnEditorActionListener((v, actionId, e) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                submit(cb);
                return true;
            }
            return false;
        });
        root.findViewById(R.id.btn_mic).setOnClickListener(v -> cb.mic());
        root.findViewById(R.id.btn_export).setOnClickListener(v -> cb.export());
        root.findViewById(R.id.btn_search).setOnClickListener(v -> {
            boolean open = searchBar.getVisibility() != View.VISIBLE;
            searchBar.setVisibility(open ? View.VISIBLE : View.GONE);
            if (!open) {
                cb.closeSearch();
            }
        });
        Consumer<String> go = q -> {
            if (q.trim().isEmpty()) {
                cb.closeSearch();
            } else {
                cb.search(q.trim());
            }
        };
        root.findViewById(R.id.search_go).setOnClickListener(v -> go.accept(searchQuery.getText().toString()));
        searchQuery.setOnEditorActionListener((v, id, e) -> {
            go.accept(searchQuery.getText().toString());
            return true;
        });
        stateRetry = cb::retry;
    }

    private final Runnable stateRetry;

    private void submit(Callbacks cb) {
        String t = input.getText().toString().trim();
        if (!t.isEmpty()) {
            input.setText("");
            cb.send(t);
        }
    }

    public static String statusText(CoreFrame.State s) {
        switch (s) {
            case LISTENING:
                return "Слушаю";
            case THINKING:
                return "Думаю";
            case SPEAKING:
                return "Говорю";
            case OFFLINE:
                return "Нет связи";
            case IDLE:
            default:
                return "Онлайн";
        }
    }

    public void renderCore(CoreFrame.State s, String text) {
        core.setState(s);
        status.setText(statusText(s));
        transcript.setText(text == null ? "" : text);
    }

    public void render(State s) {
        renderCore(s.core, s.transcript);
        note.setVisibility(s.note == null ? View.GONE : View.VISIBLE);
        note.setText(s.note);
        if (s.found != null) {
            state.show(Loadable.ready(s.found), null);
            note.setVisibility(View.VISIBLE);
            note.setText("Найдено: " + s.found.size() + (s.note == null ? "" : " · " + s.note));
            adapter.submit(s.found, false, false);
            return;
        }
        Loadable<List<Models.Message>> m = s.messages;
        state.show(m, stateRetry);
        List<Models.Message> items = m.data == null ? Collections.emptyList() : m.data;
        adapter.submit(items, s.hasMore, s.animateNew);
        if (s.animateNew && !items.isEmpty()) {
            list.scrollToPosition(adapter.getItemCount() - 1);
        }
    }

    public List<Models.Message> shown() {
        return adapter.items();
    }
}
