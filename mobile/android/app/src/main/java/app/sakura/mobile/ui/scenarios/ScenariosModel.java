package app.sakura.mobile.ui.scenarios;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.Models;

/** scenarios_list / scenario_run (+ scenario_event) / scenario_delete / scenario_save / scenario_from_text. */
public final class ScenariosModel extends ViewModel {
    private final SakuraClient client;
    private final MutableLiveData<ScenariosScreen.State> state = new MutableLiveData<>(new ScenariosScreen.State());
    private ScenariosScreen.State cur = new ScenariosScreen.State();
    private String runId;
    private boolean loaded;
    private final List<Runnable> unsubs = new ArrayList<>();

    public ScenariosModel() {
        client = SakuraApp.get().client();
        unsubs.add(client.bus().subscribe("scenario_event", this::onEvent));
        unsubs.add(client.onStatus(s -> {
            if (s.conn == SakuraClient.Conn.ONLINE && !loaded) {
                load();
            } else if (s.conn == SakuraClient.Conn.OFFLINE && !loaded) {
                update(st -> st.list = Loadable.offline());
            }
        }));
    }

    public LiveData<ScenariosScreen.State> state() {
        return state;
    }

    private synchronized void update(Consumer<ScenariosScreen.State> change) {
        ScenariosScreen.State s = new ScenariosScreen.State();
        s.list = cur.list;
        s.journalTitle = cur.journalTitle;
        s.journal = new ArrayList<>(cur.journal);
        s.note = cur.note;
        change.accept(s);
        cur = s;
        state.postValue(s);
    }

    private RequestClient.Callback listResult() {
        return new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                loaded = true;
                List<Models.Scenario> list = Models.list(Json.optArr(r, "scenarios"), Models.Scenario::of);
                update(s -> {
                    s.list = list.isEmpty() ? Loadable.empty() : Loadable.ready(list);
                    s.note = null;
                });
            }

            @Override
            public void onError(ApiError e) {
                update(s -> {
                    if (s.list.status == Loadable.Status.READY) {
                        s.note = ErrorText.text(e, "сценарии");
                    } else {
                        s.list = Loadable.failed(e);
                    }
                });
            }
        };
    }

    public void load() {
        update(s -> {
            if (s.list.status != Loadable.Status.READY) {
                s.list = Loadable.loading();
            }
        });
        client.request(Json.obj("type", "scenarios_list"), listResult());
    }

    public void run(Models.Scenario sc) {
        SakuraApp.get().input().touch();
        update(s -> {
            s.journalTitle = "Запуск: " + sc.name;
            s.journal = new ArrayList<>();
            s.note = null;
        });
        client.request(Json.obj("type", "scenario_run", "id", sc.id), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                runId = r.optString("run_id", null);
                update(s -> s.journal.add("запущен"));
            }

            @Override
            public void onError(ApiError e) {
                update(s -> s.journal.add("ошибка: " + ErrorText.text(e, "запуск сценариев")));
            }
        });
    }

    private void onEvent(JSONObject m) {
        String rid = m.optString("run_id", "");
        if (runId != null && !rid.isEmpty() && !rid.equals(runId)) {
            return;
        }
        String st = m.optString("status");
        String detail = m.optString("detail", "");
        String line = ("error".equals(st) ? "✗ " : "done".equals(st) ? "✓ готово" : "• шаг " + m.optInt("step", 0))
                + (detail.isEmpty() ? "" : ("done".equals(st) ? ": " : " — ") + detail);
        update(s -> {
            if (s.journalTitle == null) {
                s.journalTitle = "Запуск сценария";
            }
            s.journal.add(line);
        });
    }

    public void delete(Models.Scenario sc) {
        client.request(Json.obj("type", "scenario_delete", "id", sc.id), listResult());
    }

    public void save(Models.Scenario sc, Consumer<String> done) {
        client.request(Json.obj("type", "scenario_save", "scenario", sc.json()), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                done.accept(null);
                load();
            }

            @Override
            public void onError(ApiError e) {
                done.accept(ErrorText.text(e, "сохранение сценариев"));
            }
        });
    }

    /** Предпросмотр из фразы: scenario_preview {scenario, warnings}; не сохраняется. */
    public void fromText(String text, java.util.function.BiConsumer<Loadable<Models.Scenario>, List<String>> done) {
        done.accept(Loadable.loading(), null);
        client.request(Json.obj("type", "scenario_from_text", "text", text), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                JSONObject sc = Json.optObj(r, "scenario");
                List<String> warnings = new ArrayList<>();
                JSONArray w = Json.optArr(r, "warnings");
                for (int i = 0; i < w.length(); i++) {
                    warnings.add(w.optString(i));
                }
                done.accept(sc == null ? Loadable.empty() : Loadable.ready(Models.Scenario.of(sc)), warnings);
            }

            @Override
            public void onError(ApiError e) {
                done.accept(Loadable.failed(e), null);
            }
        });
    }

    @Override
    protected void onCleared() {
        for (Runnable r : unsubs) {
            r.run();
        }
    }
}
