package app.sakura.mobile.e2e;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import app.sakura.mobile.keys.DeviceKeyStore;
import app.sakura.mobile.link.CloseCodes;
import app.sakura.mobile.mock.MockSakuraServer;
import app.sakura.mobile.pairing.PairingCodes;
import app.sakura.mobile.pairing.PairingSession;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.DeviceInfo;
import app.sakura.mobile.proto.EventBus;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.testutil.SoftWrapper;
import okhttp3.OkHttpClient;

/** Сквозные сценарии клиента с MockSakuraServer: спаривание, сеанс, запросы, режимы, outbox. */
public class MockServerE2ETest {
    static final String WORDS = "лес кот мост река гора снег дом сад";

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private MockSakuraServer srv;
    private ScheduledExecutorService net;
    private OkHttpClient http;
    private DeviceKeyStore keys;
    private SakuraClient client;
    private final BlockingQueue<JSONObject> events = new LinkedBlockingQueue<>();

    private static final DeviceInfo INFO = new DeviceInfo() {
        @Override
        public JSONObject stats() {
            return Json.obj("battery", 78, "charging", true, "wifi", "wifi", "signal", 3);
        }

        @Override
        public double inputIdleSeconds() {
            return 4.2;
        }
    };

    @Before
    public void setUp() throws Exception {
        srv = new MockSakuraServer();
        net = Executors.newSingleThreadScheduledExecutor();
        http = new OkHttpClient();
        keys = new DeviceKeyStore(tmp.newFolder("keys"), new SoftWrapper());
    }

    @After
    public void tearDown() throws Exception {
        if (client != null) {
            client.stop();
            Thread.sleep(100);
        }
        srv.close();
        net.shutdownNow();
        http.dispatcher().executorService().shutdownNow();
    }

    private String qr(byte[] key) {
        return "sakura-pair://1?u=" + URLEncoder.encode(srv.url(), StandardCharsets.UTF_8) + "&k="
                + PairingCodes.b64url(key) + "&w=" + URLEncoder.encode(WORDS.replace(' ', '-'), StandardCharsets.UTF_8)
                + "&e=" + (System.currentTimeMillis() / 1000 + 600);
    }

    /** Результат спаривания: отпечаток или «!текст ошибки». */
    private String pair(String uri, String words) throws Exception {
        CompletableFuture<String> done = new CompletableFuture<>();
        PairingSession ps = new PairingSession(http, keys, net, new PairingSession.Callback() {
            @Override
            public void onPaired(DeviceKeyStore.Server server, String fingerprint) {
                done.complete(fingerprint);
            }

            @Override
            public void onFailed(String message) {
                done.complete("!" + message);
            }
        });
        if (uri != null) {
            ps.startFromQr(PairingCodes.parseQrUri(uri, System.currentTimeMillis() / 1000));
        } else {
            ps.startManual(srv.url(), words);
        }
        return done.get(15, TimeUnit.SECONDS);
    }

    private SakuraClient.Status awaitStatus(SakuraClient c, SakuraClient.Conn conn, long ms) throws Exception {
        long end = System.currentTimeMillis() + ms;
        while (System.currentTimeMillis() < end) {
            SakuraClient.Status s = c.status();
            if (s.conn == conn) {
                return s;
            }
            Thread.sleep(20);
        }
        return c.status();
    }

    private SakuraClient connect() throws Exception {
        client = new SakuraClient(http, keys, net, System::currentTimeMillis, INFO);
        client.bus().subscribe(EventBus.ANY, events::add);
        client.start();
        return client;
    }

    private JSONObject awaitEvent(String type, long ms) throws InterruptedException {
        long end = System.currentTimeMillis() + ms;
        while (true) {
            long left = end - System.currentTimeMillis();
            if (left <= 0) {
                return null;
            }
            JSONObject e = events.poll(left, TimeUnit.MILLISECONDS);
            if (e != null && type.equals(e.optString("type"))) {
                return e;
            }
        }
    }

    private Object request(JSONObject msg) throws Exception {
        CompletableFuture<Object> f = new CompletableFuture<>();
        client.request(msg, new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject result) {
                f.complete(result);
            }

            @Override
            public void onError(ApiError error) {
                f.complete(error);
            }
        });
        return f.get(15, TimeUnit.SECONDS);
    }

    private void pairAndConnect() throws Exception {
        srv.pairingWords = WORDS;
        String fp = pair(qr(srv.serverPub), null);
        assertEquals(PairingCodes.fingerprint(srv.serverPub), fp);
        connect();
        assertEquals(SakuraClient.Conn.ONLINE, awaitStatus(client, SakuraClient.Conn.ONLINE, 10_000).conn);
    }

    @Test
    public void pairingByQrThenSessionAndRegister() throws Exception {
        pairAndConnect();
        DeviceKeyStore.Server s = keys.server();
        assertArrayEquals(srv.serverPub, s.pub);
        assertEquals("phone", s.deviceId);
        assertEquals(srv.url(), s.url);
        SakuraClient.Status st = client.status();
        assertEquals(2, st.proto);
        assertTrue(st.master);
        JSONObject reg = srv.awaitType("register", 5000);
        assertNotNull(reg);
        assertEquals(2, reg.getInt("proto"));
        assertEquals("phone", reg.getString("kind"));
        assertEquals("phone", reg.getString("device_id"));
        assertFalse("токен не нужен", reg.has("token"));
        JSONObject stats = reg.getJSONObject("system_info").getJSONObject("stats");
        assertEquals(78, stats.getInt("battery"));
        assertEquals("wifi", stats.getString("wifi"));
        assertEquals(3, stats.getInt("signal"));
        assertEquals(4, reg.getLong("input_idle_s"));
    }

    @Test
    public void manualPairingAndWrongWords() throws Exception {
        srv.pairingWords = WORDS;
        String bad = pair(null, "лес кот мост река гора снег дом пень");
        assertTrue(bad, bad.startsWith("!"));
        assertNull("ключ не сохранён", keys.server());
        srv.pairingWords = WORDS;
        String ok = pair(null, "Лес, кот, мост, река, гора, снег, дом, сад");
        assertEquals(PairingCodes.fingerprint(srv.serverPub), ok);
    }

    @Test
    public void qrKeyMismatchAbortsBeforeXx3() throws Exception {
        srv.pairingWords = WORDS;
        byte[] other = srv.serverPub.clone();
        other[0] ^= 1;
        String r = pair(qr(other), null);
        assertTrue(r, r.contains("не совпал"));
        assertNull(keys.server());
    }

    @Test
    public void unknownKeyGetsSilence4408() throws Exception {
        keys.saveServer(new DeviceKeyStore.Server(srv.url(), srv.serverPub, "phone", 0));
        connect();
        Thread.sleep(1500);
        SakuraClient.Status s = client.status();
        assertTrue(s.conn == SakuraClient.Conn.OFFLINE || s.conn == SakuraClient.Conn.CONNECTING);
        assertEquals(Integer.valueOf(CloseCodes.HANDSHAKE_FAILED), srv.closes.poll(5, TimeUnit.SECONDS));
    }

    @Test
    public void pingCarriesStats() throws Exception {
        pairAndConnect();
        client.stop();
        client = new SakuraClient(http, keys, net, System::currentTimeMillis, INFO);
        client.setPingIntervalMs(200);
        client.start();
        JSONObject ping = srv.awaitType("ping", 5000);
        assertNotNull(ping);
        assertEquals(78, ping.getJSONObject("system_info").getJSONObject("stats").getInt("battery"));
        assertTrue(ping.has("input_idle_s"));
    }

    @Test
    public void requestsAndDevicesWithActiveAndTrack() throws Exception {
        pairAndConnect();
        JSONObject devs = (JSONObject) request(Json.obj("type", "devices_request"));
        JSONArray list = devs.getJSONArray("devices");
        JSONObject pc = list.getJSONObject(0);
        assertTrue(pc.getBoolean("active"));
        assertEquals("Numb", pc.getJSONObject("track").getString("title"));
        assertTrue(list.getJSONObject(1).isNull("track"));
        JSONObject hist = (JSONObject) request(Json.obj("type", "history_request", "limit", 50));
        assertEquals(2, hist.getJSONArray("messages").length());
    }

    @Test
    public void modeUnsupportedServerV1() throws Exception {
        srv.mode = MockSakuraServer.Mode.UNSUPPORTED;
        pairAndConnect();
        assertEquals(1, client.status().proto);
        ApiError e = (ApiError) request(Json.obj("type", "devices_request"));
        assertEquals(ApiError.UNSUPPORTED, e.code);
    }

    @Test
    public void modeNotMaster() throws Exception {
        srv.mode = MockSakuraServer.Mode.NOT_MASTER;
        pairAndConnect();
        assertFalse(client.status().master);
        ApiError e = (ApiError) request(Json.obj("type", "action_run", "action", "music.next"));
        assertEquals(ApiError.NOT_MASTER, e.code);
    }

    @Test
    public void modeSecureChannelRequired() throws Exception {
        srv.mode = MockSakuraServer.Mode.SECURE_REQUIRED;
        pairAndConnect();
        ApiError e = (ApiError) request(Json.obj("type", "history_request"));
        assertEquals(ApiError.SECURE_REQUIRED, e.code);
        assertTrue(request(Json.obj("type", "devices_request")) instanceof JSONObject);
    }

    @Test
    public void actionRunAndPowerConfirm() throws Exception {
        pairAndConnect();
        JSONObject started = (JSONObject) request(Json.obj("type", "action_run", "action", "system.shutdown",
                "device", "pc"));
        assertEquals("action_started", started.getString("type"));
        assertEquals("system.shutdown", started.getString("action"));
        JSONObject q = awaitEvent("reply", 5000);
        assertEquals("confirm", q.getString("kind"));
        CompletableFuture<Boolean> sent = new CompletableFuture<>();
        client.voice("да", "text", true, true, sent::complete);
        assertTrue(sent.get(5, TimeUnit.SECONDS));
        JSONObject yes = srv.await(m -> "voice_command".equals(m.optString("type")), 5000);
        assertEquals("да", yes.getString("text"));
        assertEquals("text", yes.getString("channel"));
        ApiError nf = (ApiError) request(Json.obj("type", "action_run", "action", "nope.x"));
        assertEquals(ApiError.NOT_FOUND, nf.code);
        ApiError br = (ApiError) request(Json.obj("type", "action_run"));
        assertEquals(ApiError.BAD_REQUEST, br.code);
    }

    @Test
    public void speakFalseHasNoTts() throws Exception {
        pairAndConnect();
        client.voice("погода", "voice", false, false, null);
        JSONObject vc = srv.awaitType("voice_command", 5000);
        assertFalse(vc.getBoolean("speak"));
        assertNotNull(awaitEvent("chat_message", 5000));
        boolean tts = false;
        for (JSONObject e : events) {
            tts |= e.optString("type").startsWith("tts_");
        }
        assertFalse(tts);
        client.voice("ещё", "voice", true, false, null);
        assertNotNull(awaitEvent("tts_chunk", 5000));
        assertNotNull(awaitEvent("tts_end", 5000));
    }

    @Test
    public void outboxFlushedAfterReconnectButConfirmDropped() throws Exception {
        pairAndConnect();
        client.stop();
        awaitStatus(client, SakuraClient.Conn.STOPPED, 5000);
        CompletableFuture<Boolean> queued = new CompletableFuture<>();
        client.voice("включи свет", "voice", true, false, queued::complete);
        assertTrue(queued.get(5, TimeUnit.SECONDS));
        CompletableFuture<Boolean> dropped = new CompletableFuture<>();
        client.voice("да", "text", true, true, dropped::complete);
        assertFalse(dropped.get(5, TimeUnit.SECONDS));
        assertEquals(1, client.outboxSize());
        srv.received.clear();
        client.start();
        JSONObject vc = srv.awaitType("voice_command", 10_000);
        assertEquals("включи свет", vc.getString("text"));
        assertNull(srv.await(m -> "да".equals(m.optString("text")), 500));
    }

    @Test
    public void reconnectsAfterDrop() throws Exception {
        pairAndConnect();
        srv.dropAll();
        awaitStatus(client, SakuraClient.Conn.OFFLINE, 5000);
        assertEquals(SakuraClient.Conn.ONLINE, awaitStatus(client, SakuraClient.Conn.ONLINE, 10_000).conn);
    }

    @Test
    public void serverKeyRotation() throws Exception {
        pairAndConnect();
        byte[] next = new byte[32];
        next[1] = 5;
        srv.push(Json.obj("type", "secure_server_key", "pub", PairingCodes.b64url(next), "fp", "x",
                "retire_after", 1.0));
        long end = System.currentTimeMillis() + 5000;
        while (System.currentTimeMillis() < end && !java.util.Arrays.equals(next, keys.server().pub)) {
            Thread.sleep(20);
        }
        assertArrayEquals(next, keys.server().pub);
    }

    @Test
    public void phoneCommandColdPath() throws Exception {
        pairAndConnect();
        app.sakura.mobile.exec.FakePhone phone = new app.sakura.mobile.exec.FakePhone();
        new app.sakura.mobile.exec.CommandRouter(client, new app.sakura.mobile.exec.PhoneExecutor(phone),
                new app.sakura.mobile.exec.OfflineMatcher(java.util.Collections.emptyList()), Runnable::run);
        srv.sendCommand("c7", "phone.flashlight", "on");
        JSONObject r = srv.await(m -> "command_result".equals(m.optString("type")), 5000);
        assertEquals("c7", r.getString("id"));
        assertTrue(r.getBoolean("ok"));
        assertEquals("done", r.getString("status"));
        assertTrue(phone.calls.contains("torch true"));
        phone.dndAccess = false;
        srv.sendCommand("c8", "phone.dnd_on", JSONObject.NULL);
        JSONObject u = srv.await(m -> "command_result".equals(m.optString("type")), 5000);
        assertEquals("unsupported", u.getString("status"));
        assertEquals("нет разрешения: Режим «Не беспокоить»", u.getString("detail"));
        srv.sendCommand("c9", "music.next", JSONObject.NULL);
        JSONObject pc = srv.await(m -> "command_result".equals(m.optString("type")), 5000);
        assertEquals("unsupported", pc.getString("status"));
    }

    @Test
    public void offlinePhraseRunsLocallyNotQueued() throws Exception {
        keys.saveServer(new DeviceKeyStore.Server(srv.url(), srv.serverPub, "phone", 0));
        client = new SakuraClient(http, keys, net, System::currentTimeMillis, INFO);   // не запущен: офлайн
        app.sakura.mobile.exec.FakePhone phone = new app.sakura.mobile.exec.FakePhone();
        app.sakura.mobile.exec.CommandRouter router = new app.sakura.mobile.exec.CommandRouter(client,
                new app.sakura.mobile.exec.PhoneExecutor(phone),
                app.sakura.mobile.exec.PhoneExecutorTest.matcher(), Runnable::run);
        CompletableFuture<String> res = new CompletableFuture<>();
        assertTrue(router.tryOffline("включи фонарик", res::complete));
        assertTrue(res.get(5, TimeUnit.SECONDS).contains("фонарик включён"));
        assertFalse(router.tryOffline("какая погода", r -> { }));
        assertEquals(0, client.outboxSize());
        client = null;
    }

    @Test
    public void byeOnStop() throws Exception {
        pairAndConnect();
        client.stop();
        JSONObject bye = srv.awaitType("bye", 5000);
        assertEquals("exit", bye.getString("reason"));
        client = null;
    }
}
