package app.sakura.mobile.proto;

import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/**
 * Неотправленные голосовые и текстовые реплики (voice_command, chat_send) с TTL 120 с.
 * Только в памяти: тексты приватные, на диск не пишутся. Ответы на вопрос kind:"confirm"
 * сюда не попадают — «да» через минуту опасно.
 */
public final class Outbox {
    public static final long TTL_MS = 120_000;
    public static final int MAX = 32;

    private static final class Entry {
        final JSONObject message;
        final long createdAt;

        Entry(JSONObject message, long createdAt) {
            this.message = message;
            this.createdAt = createdAt;
        }
    }

    private final Deque<Entry> queue = new ArrayDeque<>();

    /** Только voice_command и chat_send, и не ответ на confirm. */
    public static boolean eligible(JSONObject message, boolean confirmAnswer) {
        if (confirmAnswer) {
            return false;
        }
        String t = message.optString("type");
        return "voice_command".equals(t) || "chat_send".equals(t);
    }

    public synchronized boolean offer(JSONObject message, boolean confirmAnswer, long now) {
        if (!eligible(message, confirmAnswer)) {
            return false;
        }
        prune(now);
        while (queue.size() >= MAX) {
            queue.pollFirst();
        }
        queue.addLast(new Entry(message, now));
        return true;
    }

    /** Всё живое по порядку; очередь очищается. */
    public synchronized List<JSONObject> drain(long now) {
        prune(now);
        List<JSONObject> out = new ArrayList<>(queue.size());
        for (Entry e : queue) {
            out.add(e.message);
        }
        queue.clear();
        return out;
    }

    public synchronized int size(long now) {
        prune(now);
        return queue.size();
    }

    public synchronized void clear() {
        queue.clear();
    }

    private void prune(long now) {
        while (!queue.isEmpty() && now - queue.peekFirst().createdAt >= TTL_MS) {
            queue.pollFirst();
        }
    }
}
