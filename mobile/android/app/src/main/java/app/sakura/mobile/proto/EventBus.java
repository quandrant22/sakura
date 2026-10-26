package app.sakura.mobile.proto;

import org.json.JSONObject;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Consumer;

/**
 * Шина push-событий сервера (сообщения без ожидающего request_id). Подписка по `type` или на всё («*»).
 * Обработчики вызываются в потоке сети; интерфейс сам переносит работу на main.
 */
public final class EventBus {
    public static final String ANY = "*";

    private final Map<String, List<Consumer<JSONObject>>> subs = new ConcurrentHashMap<>();

    /** Возвращает функцию отписки. */
    public Runnable subscribe(String type, Consumer<JSONObject> handler) {
        List<Consumer<JSONObject>> list = subs.computeIfAbsent(type, k -> new CopyOnWriteArrayList<>());
        list.add(handler);
        return () -> list.remove(handler);
    }

    public void post(JSONObject event) {
        String type = event.optString("type", "");
        deliver(subs.get(type), event);
        deliver(subs.get(ANY), event);
    }

    private static void deliver(List<Consumer<JSONObject>> list, JSONObject event) {
        if (list == null) {
            return;
        }
        for (Consumer<JSONObject> c : list) {
            try {
                c.accept(event);
            } catch (RuntimeException ignored) {
                // ошибка одного подписчика не ломает остальных
            }
        }
    }
}
