package app.sakura.mobile.ui.summary;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.Models;

/** status_request + devices_request + последние ответы; пуши status, device_update, scenario_event, chat_message. */
public final class SummaryModel extends ViewModel {
    static final int REPLIES = 5;
    static final int EVENTS = 10;

    private final SakuraClient client;
    private final MutableLiveData<Loadable<SummaryScreen.Data>> state = new MutableLiveData<>(Loadable.loading());
    private final SummaryScreen.Data data = new SummaryScreen.Data();
    private boolean ready;
    private final List<Runnable> unsubs = new ArrayList<>();

    public SummaryModel() {
        client = SakuraApp.get().client();
        unsubs.add(client.bus().subscribe("status", m -> {
            synchronized (this) {
                data.status = status(m);
                publish();
            }
        }));
        unsubs.add(client.bus().subscribe("device_update", m -> {
            JSONObject o = Json.optObj(m, "device");
            if (o == null) {
                return;
            }
            Models.Device d = Models.Device.of(o);
            synchronized (this) {
                data.devices.removeIf(x -> x.id.equals(d.id));
                data.devices.add(d);
                publish();
            }
        }));
        unsubs.add(client.bus().subscribe("scenario_event", m -> {
            synchronized (this) {
                data.events.add(0, eventLine(m));
                while (data.events.size() > EVENTS) {
                    data.events.remove(data.events.size() - 1);
                }
                publish();
            }
        }));
        unsubs.add(client.bus().subscribe("chat_message", m -> {
            JSONObject o = Json.optObj(m, "message");
            if (o != null && "assistant".equals(o.optString("role"))) {
                synchronized (this) {
                    data.replies.add(0, Models.Message.of(o));
                    while (data.replies.size() > REPLIES) {
                        data.replies.remove(data.replies.size() - 1);
                    }
                    publish();
                }
            }
        }));
        unsubs.add(client.onStatus(s -> {
            if (s.conn == SakuraClient.Conn.ONLINE && !ready) {
                load();
            } else if (s.conn == SakuraClient.Conn.OFFLINE && !ready) {
                state.postValue(Loadable.offline());
            }
        }));
    }

    static SummaryScreen.Status status(JSONObject m) {
        return new SummaryScreen.Status(m.optString("mode", "обычный"), m.optString("tone", ""), m.optString("quote", ""));
    }

    static String eventLine(JSONObject m) {
        String st = m.optString("status");
        String mark = "error".equals(st) ? "ошибка" : "done".equals(st) ? "готово" : "шаг " + m.optInt("step", 0);
        String detail = m.optString("detail", "");
        return mark + (detail.isEmpty() ? "" : ": " + detail);
    }

    public LiveData<Loadable<SummaryScreen.Data>> state() {
        return state;
    }

    private void publish() {
        if (ready) {
            state.postValue(Loadable.ready(copy()));
        }
    }

    private SummaryScreen.Data copy() {
        SummaryScreen.Data d = new SummaryScreen.Data();
        d.status = data.status;
        d.devices = new ArrayList<>(data.devices);
        d.events = new ArrayList<>(data.events);
        d.replies = new ArrayList<>(data.replies);
        return d;
    }

    public void load() {
        if (!ready) {
            state.postValue(Loadable.loading());
        }
        client.request(Json.obj("type", "status_request"), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (SummaryModel.this) {
                    data.status = status(r);
                }
                loadDevices();
            }

            @Override
            public void onError(ApiError e) {
                state.postValue(Loadable.failed(e));
            }
        });
    }

    private void loadDevices() {
        client.request(Json.obj("type", "devices_request"), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (SummaryModel.this) {
                    data.devices = Models.list(Json.optArr(r, "devices"), Models.Device::of);
                    ready = true;
                    publish();
                }
                loadReplies();
            }

            @Override
            public void onError(ApiError e) {
                state.postValue(Loadable.failed(e));
            }
        });
    }

    /** Последние ответы — из истории (приватный класс; без защищённого канала секция просто пуста). */
    private void loadReplies() {
        client.request(Json.obj("type", "history_request", "limit", 20), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                List<Models.Message> all = Models.list(Json.optArr(r, "messages"), Models.Message::of);
                synchronized (SummaryModel.this) {
                    data.replies.clear();
                    for (int i = all.size() - 1; i >= 0 && data.replies.size() < REPLIES; i--) {
                        if ("assistant".equals(all.get(i).role)) {
                            data.replies.add(all.get(i));
                        }
                    }
                    publish();
                }
            }

            @Override
            public void onError(ApiError e) {
                // секция остаётся пустой
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
