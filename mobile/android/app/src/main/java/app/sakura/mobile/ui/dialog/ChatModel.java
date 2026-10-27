package app.sakura.mobile.ui.dialog;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.Models;

/**
 * Данные «Диалога»: history_request (+ «Загрузить раньше» по before_id), push chat_message,
 * chat_send с подтверждением chat_ack, chat_search, chat_delete. Только в памяти.
 */
public final class ChatModel extends ViewModel {
    public static final int PAGE = 50;

    private final SakuraClient client;
    private final MutableLiveData<ChatScreen.State> state = new MutableLiveData<>();
    private final List<Models.Message> messages = new ArrayList<>();
    private ChatScreen.State cur = new ChatScreen.State();
    private final Runnable unsubscribePush;
    private final Runnable unsubscribeStatus;
    private boolean loadedOnce;

    public ChatModel() {
        this(SakuraApp.get().client());
    }

    ChatModel(SakuraClient client) {
        this.client = client;
        unsubscribePush = client.bus().subscribe("chat_message", this::onPush);
        unsubscribeStatus = client.onStatus(this::onStatus);
        state.postValue(cur);
    }

    public LiveData<ChatScreen.State> state() {
        return state;
    }

    private synchronized void publish(boolean animateNew) {
        ChatScreen.State s = new ChatScreen.State();
        s.messages = cur.messages.status == Loadable.Status.READY || !messages.isEmpty()
                ? (messages.isEmpty() ? Loadable.empty() : Loadable.ready(new ArrayList<>(messages)))
                : cur.messages;
        s.hasMore = cur.hasMore;
        s.found = cur.found;
        s.note = cur.note;
        s.animateNew = animateNew;
        cur = s;
        state.postValue(s);
    }

    private synchronized void setLoadable(Loadable<List<Models.Message>> l) {
        cur.messages = l;
        publish(false);
    }

    private synchronized void note(String text) {
        cur.note = text;
        publish(false);
    }

    private void onStatus(SakuraClient.Status s) {
        if (s.conn == SakuraClient.Conn.ONLINE && (!loadedOnce || cur.messages.status != Loadable.Status.READY)) {
            load();
        } else if (s.conn != SakuraClient.Conn.ONLINE && !loadedOnce) {
            setLoadable(s.conn == SakuraClient.Conn.CONNECTING ? Loadable.loading() : Loadable.offline());
        }
    }

    public void load() {
        loadedOnce = true;
        synchronized (this) {
            if (messages.isEmpty()) {
                cur.messages = Loadable.loading();
                publish(false);
            }
        }
        client.request(Json.obj("type", "history_request", "limit", PAGE), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (ChatModel.this) {
                    List<Models.Message> got = Models.list(Json.optArr(r, "messages"), Models.Message::of);
                    List<Models.Message> pending = new ArrayList<>();
                    for (Models.Message m : messages) {
                        if (m.pending) {
                            pending.add(m);
                        }
                    }
                    messages.clear();
                    messages.addAll(got);
                    messages.addAll(pending);
                    cur.hasMore = r.optBoolean("has_more", got.size() >= PAGE);
                    cur.messages = messages.isEmpty() ? Loadable.empty() : Loadable.ready(messages);
                    publish(false);
                }
            }

            @Override
            public void onError(ApiError e) {
                setLoadable(Loadable.failed(e));
            }
        });
    }

    public void older() {
        String before;
        synchronized (this) {
            if (messages.isEmpty()) {
                return;
            }
            before = messages.get(0).id;
        }
        client.request(Json.obj("type", "history_request", "limit", PAGE, "before_id", before),
                new RequestClient.Callback() {
                    @Override
                    public void onResult(JSONObject r) {
                        synchronized (ChatModel.this) {
                            List<Models.Message> got = Models.list(Json.optArr(r, "messages"), Models.Message::of);
                            messages.addAll(0, got);
                            cur.hasMore = r.optBoolean("has_more", got.size() >= PAGE);
                            publish(false);
                        }
                    }

                    @Override
                    public void onError(ApiError e) {
                        note(ErrorText.text(e));
                    }
                });
    }

    private void onPush(JSONObject m) {
        JSONObject o = Json.optObj(m, "message");
        if (o == null) {
            return;
        }
        Models.Message msg = Models.Message.of(o);
        String cmid = o.optString("client_msg_id", "");
        synchronized (this) {
            for (int i = 0; i < messages.size(); i++) {
                Models.Message x = messages.get(i);
                if (x.id.equals(msg.id) || (!cmid.isEmpty() && x.id.equals("local-" + cmid))) {
                    messages.set(i, msg);
                    publish(false);
                    return;
                }
            }
            messages.add(msg);
            publish(true);
        }
    }

    /** Текст из поля ввода: chat_send (speak по «Ответам текстом»); сервер v1 — voice_command. */
    public void send(String text) {
        SakuraApp app = SakuraApp.get();
        boolean speak = app.voice().speakReplies();
        app.input().touch();
        app.voice().markThinking();
        if (client.status().proto < 2 && client.status().conn == SakuraClient.Conn.ONLINE) {
            client.voice(text, "text", speak, app.voice().confirmPending(), null);
            return;
        }
        String cmid = UUID.randomUUID().toString();
        Models.Message local = new Models.Message("local-" + cmid, System.currentTimeMillis() / 1000.0, "user", text,
                "text", "phone", true);
        synchronized (this) {
            messages.add(local);
            if (cur.messages.status != Loadable.Status.READY) {
                cur.messages = Loadable.ready(messages);
            }
            publish(true);
        }
        client.chatSend(text, speak, new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (ChatModel.this) {
                    String id = Json.optStr(r, "id");
                    for (int i = 0; i < messages.size(); i++) {
                        if (messages.get(i) == local) {
                            if (id == null) {
                                messages.remove(i);   // фраза приватности: в журнал не пишется
                            } else {
                                messages.set(i, new Models.Message(id, local.ts, "user", text, "text", "phone", false));
                            }
                            break;
                        }
                    }
                    publish(false);
                }
            }

            @Override
            public void onError(ApiError e) {
                if (ApiError.OFFLINE.equals(e.code)) {
                    note("Нет связи — сообщение отправится, когда связь появится (до 2 минут)");
                } else {
                    synchronized (ChatModel.this) {
                        messages.remove(local);
                    }
                    note(ErrorText.text(e));
                }
            }
        });
    }

    public void search(String q) {
        client.request(Json.obj("type", "chat_search", "q", q, "limit", 50), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (ChatModel.this) {
                    cur.found = Models.list(Json.optArr(r, "messages"), Models.Message::of);
                    cur.note = null;
                    publish(false);
                }
            }

            @Override
            public void onError(ApiError e) {
                note(ErrorText.text(e, "поиск по переписке"));
            }
        });
    }

    public synchronized void closeSearch() {
        cur.found = null;
        cur.note = null;
        publish(false);
    }

    public void delete(Models.Message m) {
        client.request(Json.obj("type", "chat_delete", "id", m.id), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                synchronized (ChatModel.this) {
                    messages.removeIf(x -> x.id.equals(m.id));
                    if (cur.found != null) {
                        cur.found.removeIf(x -> x.id.equals(m.id));
                    }
                    publish(false);
                }
            }

            @Override
            public void onError(ApiError e) {
                note(ErrorText.text(e, "удаление сообщений"));
            }
        });
    }

    /** Загруженная переписка для экспорта. */
    public synchronized String exportText() {
        return Models.export(messages);
    }

    @Override
    protected void onCleared() {
        unsubscribePush.run();
        unsubscribeStatus.run();
    }
}
