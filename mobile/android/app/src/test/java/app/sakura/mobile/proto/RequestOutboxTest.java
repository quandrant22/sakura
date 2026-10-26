package app.sakura.mobile.proto;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class RequestOutboxTest {
    private final ScheduledExecutorService sched = Executors.newSingleThreadScheduledExecutor();

    @After
    public void tearDown() {
        sched.shutdownNow();
    }

    static final class FakeTransport implements RequestClient.Transport {
        boolean ready = true;
        int proto = 2;
        boolean accept = true;
        final List<String> sent = new ArrayList<>();

        @Override
        public boolean ready() {
            return ready;
        }

        @Override
        public int proto() {
            return proto;
        }

        @Override
        public boolean send(String json) {
            sent.add(json);
            return accept;
        }
    }

    static final class Result implements RequestClient.Callback {
        final CompletableFuture<Object> f = new CompletableFuture<>();

        @Override
        public void onResult(JSONObject result) {
            f.complete(result);
        }

        @Override
        public void onError(ApiError error) {
            f.complete(error);
        }

        Object get() throws Exception {
            return f.get(15, TimeUnit.SECONDS);
        }
    }

    @Test
    public void responseRoutedByRequestId() throws Exception {
        FakeTransport t = new FakeTransport();
        RequestClient rc = new RequestClient(t, sched);
        Result r = new Result();
        String id = rc.request(Json.obj("type", "devices_request"), r);
        assertEquals("r1", id);
        assertTrue(t.sent.get(0).contains("\"request_id\":\"r1\""));
        assertFalse(rc.onMessage(Json.obj("type", "devices", "request_id", "r9")));
        assertFalse(rc.onMessage(Json.obj("type", "device_update")));
        assertTrue(rc.onMessage(Json.obj("type", "devices", "request_id", "r1")));
        assertEquals("devices", ((JSONObject) r.get()).optString("type"));
        assertEquals(0, rc.pendingCount());
    }

    @Test
    public void errorsMapped() throws Exception {
        FakeTransport t = new FakeTransport();
        RequestClient rc = new RequestClient(t, sched);
        Result r = new Result();
        rc.request(Json.obj("type", "memory_list"), r);
        rc.onMessage(Json.obj("type", "error", "request_id", "r1", "code", "secure_channel_required", "message", "x"));
        ApiError e = (ApiError) r.get();
        assertEquals(ApiError.SECURE_REQUIRED, e.code);
        assertEquals(ErrorText.SECURE_REQUIRED, ErrorText.text(e));
    }

    @Test
    public void offlineAndV1AreImmediate() throws Exception {
        FakeTransport t = new FakeTransport();
        RequestClient rc = new RequestClient(t, sched);
        t.ready = false;
        Result off = new Result();
        assertNull(rc.request(Json.obj("type", "status_request"), off));
        assertEquals(ApiError.OFFLINE, ((ApiError) off.get()).code);
        t.ready = true;
        t.proto = 1;
        Result v1 = new Result();
        rc.request(Json.obj("type", "status_request"), v1);
        assertEquals(ApiError.UNSUPPORTED, ((ApiError) v1.get()).code);
        assertTrue(t.sent.isEmpty());
    }

    @Test
    public void timeoutAfter10s() throws Exception {
        FakeTransport t = new FakeTransport();
        RequestClient rc = new RequestClient(t, sched);
        Result r = new Result();
        long start = System.currentTimeMillis();
        rc.request(Json.obj("type", "status_request"), r);
        assertEquals(ApiError.TIMEOUT, ((ApiError) r.get()).code);
        assertTrue(System.currentTimeMillis() - start >= RequestClient.TIMEOUT_MS - 50);
        assertFalse("поздний ответ не ловится", rc.onMessage(Json.obj("type", "status", "request_id", "r1")));
    }

    @Test
    public void failAllOnDisconnect() throws Exception {
        FakeTransport t = new FakeTransport();
        RequestClient rc = new RequestClient(t, sched);
        Result a = new Result();
        Result b = new Result();
        rc.request(Json.obj("type", "a"), a);
        rc.request(Json.obj("type", "b"), b);
        rc.failAll();
        assertEquals(ApiError.OFFLINE, ((ApiError) a.get()).code);
        assertEquals(ApiError.OFFLINE, ((ApiError) b.get()).code);
    }

    @Test
    public void outboxTtlAndConfirm() {
        Outbox o = new Outbox();
        assertTrue(o.offer(Json.obj("type", "voice_command", "text", "1"), false, 0));
        assertTrue(o.offer(Json.obj("type", "chat_send", "text", "2"), false, 60_000));
        assertFalse("ответ на confirm не копится", o.offer(Json.obj("type", "voice_command", "text", "да"), true, 0));
        assertFalse("прочее не копится", o.offer(Json.obj("type", "action_run"), false, 0));
        assertEquals(2, o.size(100_000));
        List<JSONObject> live = o.drain(Outbox.TTL_MS + 1);
        assertEquals(1, live.size());
        assertEquals("2", live.get(0).optString("text"));
        assertEquals(0, o.size(0));
    }

    @Test
    public void outboxCapped() {
        Outbox o = new Outbox();
        for (int i = 0; i < Outbox.MAX + 5; i++) {
            o.offer(Json.obj("type", "voice_command", "text", String.valueOf(i)), false, i);
        }
        List<JSONObject> all = o.drain(100);
        assertEquals(Outbox.MAX, all.size());
        assertEquals("5", all.get(0).optString("text"));
    }

    @Test
    public void errorTextsVerbatim() {
        assertEquals("Сервер ещё не поддерживает", ErrorText.text(new ApiError("unsupported", "")));
        assertEquals("Сервер ещё не поддерживает сценарии",
                ErrorText.text(new ApiError("unknown_type", ""), "сценарии"));
        assertEquals("Сервер не отвечает", ErrorText.text(new ApiError("timeout", "")));
        assertEquals("Нет связи с сервером", ErrorText.text(new ApiError("offline", "")));
        assertEquals("запись не найдена", ErrorText.text(new ApiError("not_found", "")));
        assertEquals("status_request: только для master-устройств",
                ErrorText.text(new ApiError("not_master", "status_request: только для master-устройств")));
        assertFalse(ErrorText.retryable(new ApiError("unsupported", "")));
        assertTrue(ErrorText.retryable(new ApiError("timeout", "")));
    }
}
