package app.sakura.mobile.ui.control;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.Models;

/** devices_request + device_update; action_run с device = выбранный (по умолчанию активный) ПК. */
public final class ControlModel extends ViewModel {
    private final SakuraClient client;
    private final MutableLiveData<ControlScreen.State> state = new MutableLiveData<>();
    private final List<Models.Device> devices = new ArrayList<>();
    private Loadable.Status status = Loadable.Status.LOADING;
    private ApiError error;
    private String selected;
    private String note;
    private final Runnable unsubscribe;
    private final Runnable unsubscribeStatus;

    public ControlModel() {
        client = SakuraApp.get().client();
        unsubscribe = client.bus().subscribe("device_update", this::onUpdate);
        unsubscribeStatus = client.onStatus(s -> {
            if (s.conn == SakuraClient.Conn.ONLINE && status != Loadable.Status.READY) {
                load();
            } else if (s.conn == SakuraClient.Conn.OFFLINE && devices.isEmpty()) {
                fail(new ApiError(ApiError.OFFLINE, ""));
            }
        });
    }

    public LiveData<ControlScreen.State> state() {
        return state;
    }

    private synchronized void publish() {
        ControlScreen.State s = new ControlScreen.State();
        if (status == Loadable.Status.READY) {
            List<Models.Device> pcs = new ArrayList<>();
            for (Models.Device d : devices) {
                if (d.isPc()) {
                    pcs.add(d);
                }
            }
            s.devices = pcs.isEmpty() ? Loadable.empty() : Loadable.ready(new ArrayList<>(devices));
        } else if (status == Loadable.Status.LOADING) {
            s.devices = Loadable.loading();
        } else {
            s.devices = Loadable.failed(error);
        }
        if (selected == null) {
            for (Models.Device d : devices) {
                if (d.isPc() && d.active) {
                    selected = d.id;
                }
            }
            for (Models.Device d : devices) {
                if (selected == null && d.isPc() && d.online) {
                    selected = d.id;
                }
            }
        }
        s.selected = selected;
        s.note = note;
        state.postValue(s);
    }

    private synchronized void fail(ApiError e) {
        status = Loadable.Status.ERROR;
        error = e;
        publish();
    }

    public void load() {
        synchronized (this) {
            if (devices.isEmpty()) {
                status = Loadable.Status.LOADING;
                publish();
            }
        }
        client.request(Json.obj("type", "devices_request"), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (ControlModel.this) {
                    devices.clear();
                    devices.addAll(Models.list(Json.optArr(r, "devices"), Models.Device::of));
                    status = Loadable.Status.READY;
                    publish();
                }
            }

            @Override
            public void onError(ApiError e) {
                fail(e);
            }
        });
    }

    private void onUpdate(JSONObject m) {
        JSONObject o = Json.optObj(m, "device");
        if (o == null) {
            return;
        }
        Models.Device d = Models.Device.of(o);
        synchronized (this) {
            boolean found = false;
            for (int i = 0; i < devices.size(); i++) {
                if (devices.get(i).id.equals(d.id)) {
                    devices.set(i, d);
                    found = true;
                }
            }
            if (!found) {
                devices.add(d);
            }
            if (status == Loadable.Status.READY) {
                publish();
            }
        }
    }

    public synchronized void select(String id) {
        selected = id;
        note = null;
        publish();
    }

    public void run(String action, String arg) {
        SakuraApp.get().input().touch();
        JSONObject m = Json.obj("type", "action_run", "action", action);
        if (arg != null) {
            Json.put(m, "arg", arg);
        }
        synchronized (this) {
            if (selected != null) {
                Json.put(m, "device", selected);
            }
            note = null;
        }
        if (action.startsWith("system.") || action.startsWith("power.")) {
            SakuraApp.get().voice().markThinking();   // ждём вопрос kind:"confirm"
        }
        client.request(m, new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (ControlModel.this) {
                    note = null;
                    publish();
                }
            }

            @Override
            public void onError(ApiError e) {
                synchronized (ControlModel.this) {
                    note = ErrorText.text(e, "кнопки пульта");
                    publish();
                }
            }
        });
    }

    @Override
    protected void onCleared() {
        unsubscribe.run();
        unsubscribeStatus.run();
    }
}
