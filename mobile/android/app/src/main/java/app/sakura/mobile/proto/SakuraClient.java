package app.sakura.mobile.proto;

import org.json.JSONObject;

import java.util.List;
import java.util.Random;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import java.util.function.LongSupplier;

import app.sakura.mobile.keys.DeviceKeyStore;
import app.sakura.mobile.link.SecureLink;
import okhttp3.OkHttpClient;

/**
 * Сеанс приложения поверх SecureLink: register/ping с proto 2, запросы, шина push-событий,
 * outbox реплик, bye. Все обработчики — в потоке scheduler («sakura-net»).
 */
public final class SakuraClient implements SecureLink.Listener, RequestClient.Transport {
    public static final int PROTO = 2;
    public static final long PING_MS = 30_000;
    public static final long REGISTER_WAIT_MS = 5_000;

    public enum Conn { UNPAIRED, CONNECTING, ONLINE, OFFLINE, STOPPED }

    /** Снимок состояния связи для интерфейса и уведомления. */
    public static final class Status {
        public final Conn conn;
        /** 0 — ещё неизвестно, 1 — сервер v1, 2 — v2. */
        public final int proto;
        public final boolean master;
        public final int closeCode;

        public Status(Conn conn, int proto, boolean master, int closeCode) {
            this.conn = conn;
            this.proto = proto;
            this.master = master;
            this.closeCode = closeCode;
        }
    }

    private final SecureLink link;
    private final DeviceKeyStore keys;
    private final ScheduledExecutorService scheduler;
    private final LongSupplier clock;
    private final DeviceInfo info;
    private final RequestClient requests;
    private final EventBus bus = new EventBus();
    private final Outbox outbox = new Outbox();
    private final List<Consumer<Status>> statusListeners = new CopyOnWriteArrayList<>();

    private volatile Status status = new Status(Conn.STOPPED, 0, false, 0);
    private long pingMs = PING_MS;
    private ScheduledFuture<?> pingTask;
    private ScheduledFuture<?> registerWait;
    private boolean linkOpen;

    public SakuraClient(OkHttpClient http, DeviceKeyStore keys, ScheduledExecutorService scheduler,
                        LongSupplier clock, DeviceInfo info) {
        this.keys = keys;
        this.scheduler = scheduler;
        this.clock = clock;
        this.info = info;
        this.link = new SecureLink(http, keys, this, scheduler, clock, new Random());
        this.requests = new RequestClient(this, scheduler);
    }

    /** Интервал ping (по умолчанию 30 с); меньше — только в тестах. */
    public void setPingIntervalMs(long ms) {
        pingMs = ms;
    }

    public EventBus bus() {
        return bus;
    }

    public Status status() {
        return status;
    }

    public Runnable onStatus(Consumer<Status> listener) {
        statusListeners.add(listener);
        listener.accept(status);
        return () -> statusListeners.remove(listener);
    }

    public String deviceId() {
        DeviceKeyStore.Server s = keys.server();
        return s == null ? "phone" : s.deviceId;
    }

    public void start() {
        link.start();
    }

    public void reconnectNow() {
        link.reconnectNow();
    }

    /** Выход: bye{reason:"exit"} и закрытие. */
    public void stop() {
        scheduler.execute(() -> {
            if (linkOpen) {
                link.send(Json.obj("type", "bye", "device_id", deviceId(), "reason", "exit").toString());
            }
            link.stop();
        });
    }

    private void setStatus(Status s) {
        status = s;
        for (Consumer<Status> l : statusListeners) {
            l.accept(s);
        }
    }

    // ── RequestClient.Transport ──

    @Override
    public boolean ready() {
        return linkOpen;
    }

    @Override
    public int proto() {
        return status.proto;
    }

    @Override
    public boolean send(String json) {
        return link.send(json);
    }

    // ── SecureLink.Listener ──

    @Override
    public void onState(SecureLink.State state, int lastCloseCode) {
        Status cur = status;
        switch (state) {
            case OPEN:
                linkOpen = true;
                setStatus(new Status(Conn.CONNECTING, 0, false, 0));
                sendRegister();
                registerWait = scheduler.schedule(this::registerTimedOut, REGISTER_WAIT_MS, TimeUnit.MILLISECONDS);
                break;
            case UNPAIRED:
                down();
                setStatus(new Status(Conn.UNPAIRED, 0, false, 0));
                break;
            case CONNECTING:
                setStatus(new Status(cur.conn == Conn.ONLINE ? Conn.OFFLINE : Conn.CONNECTING, cur.proto,
                        cur.master, cur.closeCode));
                break;
            case WAITING:
                down();
                setStatus(new Status(Conn.OFFLINE, cur.proto, cur.master, lastCloseCode));
                break;
            case STOPPED:
            default:
                down();
                setStatus(new Status(Conn.STOPPED, cur.proto, cur.master, lastCloseCode));
        }
    }

    private void down() {
        linkOpen = false;
        if (pingTask != null) {
            pingTask.cancel(false);
            pingTask = null;
        }
        if (registerWait != null) {
            registerWait.cancel(false);
        }
        requests.failAll();
    }

    private JSONObject presence(String type) {
        return Json.obj("type", type,
                "device_id", deviceId(),
                "active_window", "",
                "system_info", Json.obj("stats", info.stats()),
                "input_idle_s", Math.max(0, Math.round(info.inputIdleSeconds())));
    }

    private void sendRegister() {
        JSONObject r = presence("register");
        Json.put(r, "proto", PROTO);
        Json.put(r, "kind", "phone");
        link.send(r.toString());
    }

    private void registerTimedOut() {
        if (linkOpen && status.proto == 0) {
            online(1, false);   // сервер без v2: запросы v2 сразу unsupported
        }
    }

    private void online(int proto, boolean master) {
        setStatus(new Status(Conn.ONLINE, proto, master, 0));
        if (pingTask == null) {
            pingTask = scheduler.scheduleWithFixedDelay(this::ping, pingMs, pingMs, TimeUnit.MILLISECONDS);
        }
        flushOutbox();
    }

    private void ping() {
        if (linkOpen) {
            link.send(presence("ping").toString());
        }
    }

    @Override
    public void onMessage(String json) {
        JSONObject m = Json.parse(json);
        if (m == null) {
            return;
        }
        if ("registered".equals(m.optString("type")) && m.optString("request_id", "").isEmpty()) {
            if (registerWait != null) {
                registerWait.cancel(false);
            }
            online(m.optInt("proto", 1), m.optBoolean("master", false));
            bus.post(m);
            return;
        }
        if (requests.onMessage(m)) {
            return;
        }
        bus.post(m);
    }

    // ── API для интерфейса и исполнителя ──

    /** Произвольный запрос v2 (history_request, devices_request, action_run, …). */
    public void request(JSONObject message, RequestClient.Callback callback) {
        request(message, RequestClient.TIMEOUT_MS, callback);
    }

    public void request(JSONObject message, long timeoutMs, RequestClient.Callback callback) {
        scheduler.execute(() -> {
            Json.put(message, "device_id", deviceId());
            requests.request(message, timeoutMs, callback);
        });
    }

    /** Отправка без ожидания ответа (command_result, vision_request, …). */
    public void sendRaw(JSONObject message) {
        scheduler.execute(() -> {
            if (linkOpen) {
                Json.put(message, "device_id", deviceId());
                link.send(message.toString());
            }
        });
    }

    /**
     * Голосовая или текстовая реплика: voice_command. speak=false — ответ без озвучки.
     * confirmAnswer=true — ответ «да»/«нет» на kind:"confirm": без связи он отбрасывается.
     * Возвращает false, если реплика не ушла и не встала в очередь.
     */
    public void voice(String text, String channel, boolean speak, boolean confirmAnswer,
                      Consumer<Boolean> sent) {
        JSONObject m = Json.obj("type", "voice_command", "text", text, "channel", channel,
                "active_window", "", "context", Json.arr());
        if (!speak) {
            Json.put(m, "speak", false);
        }
        scheduler.execute(() -> {
            Json.put(m, "device_id", deviceId());
            boolean ok = linkOpen && link.send(m.toString());
            if (!ok) {
                ok = outbox.offer(m, confirmAnswer, clock.getAsLong());
            }
            if (sent != null) {
                sent.accept(ok);
            }
        });
    }

    /** chat_send с client_msg_id (сервер отвечает chat_ack); без связи — в outbox. */
    public void chatSend(String text, boolean speak, RequestClient.Callback callback) {
        JSONObject m = Json.obj("type", "chat_send", "text", text, "client_msg_id", UUID.randomUUID().toString());
        if (!speak) {
            Json.put(m, "speak", false);
        }
        scheduler.execute(() -> {
            Json.put(m, "device_id", deviceId());
            if (linkOpen && status.conn == Conn.ONLINE) {
                requests.request(m, callback);
            } else {
                outbox.offer(m, false, clock.getAsLong());
                callback.onError(new ApiError(ApiError.OFFLINE, "в очереди"));
            }
        });
    }

    private void flushOutbox() {
        for (JSONObject m : outbox.drain(clock.getAsLong())) {
            m.remove("request_id");
            if ("chat_send".equals(m.optString("type"))) {
                requests.request(m, new RequestClient.Callback() {
                    @Override
                    public void onResult(JSONObject result) {
                    }

                    @Override
                    public void onError(ApiError error) {
                    }
                });
            } else {
                link.send(m.toString());
            }
        }
    }

    public int outboxSize() {
        return outbox.size(clock.getAsLong());
    }

    /** «Забыть сервер». */
    public void forget() {
        scheduler.execute(() -> {
            link.stop();
            outbox.clear();
            keys.forget();
            setStatus(new Status(Conn.UNPAIRED, 0, false, 0));
        });
    }
}
