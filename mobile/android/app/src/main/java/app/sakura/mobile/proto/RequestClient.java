package app.sakura.mobile.proto;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * Запросы v2: request_id уникален в соединении, ответ повторяет его; ожидание 10 с → `timeout`.
 * Нет связи → `offline`; сервер v1 (нет `registered` с proto 2) → `unsupported` без отправки.
 */
public final class RequestClient {
    public static final long TIMEOUT_MS = 10_000;

    public interface Transport {
        boolean ready();

        int proto();

        boolean send(String json);
    }

    public interface Callback {
        void onResult(JSONObject result);

        void onError(ApiError error);
    }

    private static final class Pending {
        final Callback callback;
        final ScheduledFuture<?> timer;

        Pending(Callback callback, ScheduledFuture<?> timer) {
            this.callback = callback;
            this.timer = timer;
        }
    }

    private final Transport transport;
    private final ScheduledExecutorService scheduler;
    private final Map<String, Pending> pending = new HashMap<>();
    private long seq;

    public RequestClient(Transport transport, ScheduledExecutorService scheduler) {
        this.transport = transport;
        this.scheduler = scheduler;
    }

    /** Отправить запрос; message изменяется (добавляется request_id). Возвращает request_id или null. */
    public String request(JSONObject message, Callback callback) {
        return request(message, TIMEOUT_MS, callback);
    }

    /** То же с собственным таймаутом (vision_request — ответ LLM дольше 10 с). */
    public String request(JSONObject message, long timeoutMs, Callback callback) {
        if (!transport.ready()) {
            scheduler.execute(() -> callback.onError(new ApiError(ApiError.OFFLINE, "")));
            return null;
        }
        if (transport.proto() < 2) {
            scheduler.execute(() -> callback.onError(new ApiError(ApiError.UNSUPPORTED, "")));
            return null;
        }
        String id;
        synchronized (this) {
            id = "r" + (++seq);
            try {
                message.put("request_id", id);
            } catch (JSONException e) {
                return null;
            }
            ScheduledFuture<?> timer = scheduler.schedule(() -> expire(id), timeoutMs, TimeUnit.MILLISECONDS);
            pending.put(id, new Pending(callback, timer));
        }
        if (!transport.send(message.toString())) {
            Pending p;
            synchronized (this) {
                p = pending.remove(id);
            }
            if (p != null) {
                p.timer.cancel(false);
                scheduler.execute(() -> p.callback.onError(new ApiError(ApiError.OFFLINE, "")));
            }
            return null;
        }
        return id;
    }

    private void expire(String id) {
        Pending p;
        synchronized (this) {
            p = pending.remove(id);
        }
        if (p != null) {
            p.callback.onError(new ApiError(ApiError.TIMEOUT, ""));
        }
    }

    /** Ответ на наш запрос? Тогда он отдаётся ожидающему и не идёт в шину. */
    public boolean onMessage(JSONObject msg) {
        String id = msg.optString("request_id", "");
        if (id.isEmpty()) {
            return false;
        }
        Pending p;
        synchronized (this) {
            p = pending.remove(id);
        }
        if (p == null) {
            return false;
        }
        p.timer.cancel(false);
        if ("error".equals(msg.optString("type"))) {
            p.callback.onError(new ApiError(msg.optString("code", "error"), msg.optString("message", "")));
        } else {
            p.callback.onResult(msg);
        }
        return true;
    }

    /** Обрыв связи: все ожидающие получают `offline`. */
    public void failAll() {
        List<Pending> all;
        synchronized (this) {
            all = new ArrayList<>(pending.values());
            pending.clear();
        }
        for (Pending p : all) {
            p.timer.cancel(false);
            p.callback.onError(new ApiError(ApiError.OFFLINE, ""));
        }
    }

    public synchronized int pendingCount() {
        return pending.size();
    }
}
