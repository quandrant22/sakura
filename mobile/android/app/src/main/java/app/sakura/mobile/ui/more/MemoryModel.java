package app.sakura.mobile.ui.more;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Iterator;
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

/**
 * memory_list / memory_search / memory_update / memory_delete. Без кэша: модель живёт, пока открыт
 * экран (ViewModel фрагмента), на диск ничего не пишется.
 */
public final class MemoryModel extends ViewModel {
    static final int LIMIT = 100;

    private final SakuraClient client;
    private final MutableLiveData<MemoryScreen.State> state = new MutableLiveData<>(new MemoryScreen.State());
    private MemoryScreen.State cur = new MemoryScreen.State();

    public MemoryModel() {
        client = SakuraApp.get().client();
    }

    public LiveData<MemoryScreen.State> state() {
        return state;
    }

    private synchronized void update(Consumer<MemoryScreen.State> change) {
        MemoryScreen.State s = new MemoryScreen.State();
        s.items = cur.items;
        s.counts = cur.counts;
        s.category = cur.category;
        s.note = cur.note;
        change.accept(s);
        cur = s;
        state.postValue(s);
    }

    private RequestClient.Callback items() {
        return new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                List<Models.MemoryItem> list = Models.list(Json.optArr(r, "items"), Models.MemoryItem::of);
                JSONObject counts = Json.optObj(r, "counts");
                update(s -> {
                    s.items = list.isEmpty() ? Loadable.empty() : Loadable.ready(list);
                    s.note = null;
                    if (counts != null) {
                        s.counts = new java.util.LinkedHashMap<>();
                        Iterator<String> keys = counts.keys();
                        while (keys.hasNext()) {
                            String k = keys.next();
                            s.counts.put(k, counts.optInt(k));
                        }
                    }
                });
            }

            @Override
            public void onError(ApiError e) {
                update(s -> s.items = Loadable.failed(e));
            }
        };
    }

    public void load() {
        String cat = cur.category;
        update(s -> s.items = Loadable.loading());
        JSONObject m = Json.obj("type", "memory_list", "offset", 0, "limit", LIMIT);
        if (cat != null) {
            Json.put(m, "category", cat);
        }
        client.request(m, items());
    }

    public void category(String c) {
        update(s -> s.category = c);
        load();
    }

    public void search(String q) {
        if (q.isEmpty()) {
            load();
            return;
        }
        update(s -> s.items = Loadable.loading());
        client.request(Json.obj("type", "memory_search", "q", q, "limit", LIMIT), items());
    }

    public void edit(Models.MemoryItem item, String text) {
        client.request(Json.obj("type", "memory_update", "id", item.id, "text", text), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                List<Models.MemoryItem> changed = Models.list(Json.optArr(r, "items"), Models.MemoryItem::of);
                update(s -> {
                    if (s.items.data != null) {
                        List<Models.MemoryItem> next = new ArrayList<>();
                        for (Models.MemoryItem x : s.items.data) {
                            Models.MemoryItem rep = x;
                            for (Models.MemoryItem c : changed) {
                                if (c.id.equals(x.id)) {
                                    rep = c;
                                }
                            }
                            next.add(rep);
                        }
                        s.items = Loadable.ready(next);
                    }
                });
            }

            @Override
            public void onError(ApiError e) {
                update(s -> s.note = ErrorText.text(e, "правку памяти"));
            }
        });
    }

    public void delete(Models.MemoryItem item) {
        client.request(Json.obj("type", "memory_delete", "id", item.id), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                update(s -> {
                    if (s.items.data != null) {
                        List<Models.MemoryItem> next = new ArrayList<>(s.items.data);
                        next.removeIf(x -> x.id.equals(item.id));
                        s.items = next.isEmpty() ? Loadable.empty() : Loadable.ready(next);
                    }
                });
            }

            @Override
            public void onError(ApiError e) {
                update(s -> s.note = ErrorText.text(e, "удаление из памяти"));
            }
        });
    }

    public boolean online() {
        return client.status().conn == SakuraClient.Conn.ONLINE;
    }
}
