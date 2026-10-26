package app.sakura.mobile.mock;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.Closeable;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Set;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;

import app.sakura.mobile.crypto.noise.CipherState;
import app.sakura.mobile.crypto.noise.HandshakeState;
import app.sakura.mobile.crypto.noise.NoiseException;
import app.sakura.mobile.crypto.noise.Primitives;
import app.sakura.mobile.link.CloseCodes;
import app.sakura.mobile.link.FrameCodec;
import app.sakura.mobile.link.SecureChannel;
import app.sakura.mobile.link.SecureLink;
import app.sakura.mobile.pairing.PairingCodes;
import app.sakura.mobile.proto.Json;
import mockwebserver3.Dispatcher;
import mockwebserver3.MockResponse;
import mockwebserver3.MockWebServer;
import mockwebserver3.RecordedRequest;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/**
 * Мок сервера Сакуры для JUnit: Noise IK/XXpsk3 поверх OkHttp MockWebServer, ответы по «Контракту
 * телефона» (docs/mobile/CONTRACT.md). Режимы: NORMAL, UNSUPPORTED (сервер v1), NOT_MASTER,
 * SECURE_REQUIRED (приватные классы отклоняются), NOISE_OFF (бинарные кадры → 4400).
 */
public final class MockSakuraServer implements Closeable {

    public enum Mode { NORMAL, UNSUPPORTED, NOT_MASTER, SECURE_REQUIRED, NOISE_OFF }

    public final byte[] serverPriv;
    public final byte[] serverPub;
    private final Set<String> knownClients = ConcurrentHashMap.newKeySet();
    private final MockWebServer web = new MockWebServer();
    private final ScheduledExecutorService timers = Executors.newSingleThreadScheduledExecutor();
    private final List<Session> sessions = new CopyOnWriteArrayList<>();
    /** Всё, что прислали клиенты (JSON приложения), по порядку. */
    public final BlockingQueue<JSONObject> received = new LinkedBlockingQueue<>();
    public final BlockingQueue<Integer> closes = new LinkedBlockingQueue<>();

    public volatile Mode mode = Mode.NORMAL;
    public volatile String pairingWords;
    public volatile long handshakeFailDelayMs = 300;
    public volatile int rekeyMessages = 10000;
    /** Трек ПК в devices: null — без трека. */
    public volatile JSONObject pcTrack = Json.obj("title", "Numb", "artist", "Linkin Park", "status", "играет",
            "cover_url", JSONObject.NULL, "ts", 1791900000.0);

    public MockSakuraServer() throws IOException {
        byte[][] kp = Primitives.generateKeypair();
        serverPriv = kp[0];
        serverPub = kp[1];
        web.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                Session s = new Session();
                sessions.add(s);
                return new MockResponse.Builder().webSocketUpgrade(s).build();
            }
        });
        web.start();
    }

    public String url() {
        return "ws://" + web.getHostName() + ":" + web.getPort() + "/";
    }

    public void allowClient(byte[] pub) {
        knownClients.add(PairingCodes.b64url(pub));
    }

    public void revokeAll() {
        knownClients.clear();
    }

    /** Ждать сообщение клиента, удовлетворяющее условию (остальные пропускаются). */
    public JSONObject await(Predicate<JSONObject> p, long timeoutMs) throws InterruptedException {
        long end = System.currentTimeMillis() + timeoutMs;
        while (true) {
            long left = end - System.currentTimeMillis();
            if (left <= 0) {
                return null;
            }
            JSONObject m = received.poll(left, TimeUnit.MILLISECONDS);
            if (m == null) {
                return null;
            }
            if (p.test(m)) {
                return m;
            }
        }
    }

    public JSONObject awaitType(String type, long timeoutMs) throws InterruptedException {
        return await(m -> type.equals(m.optString("type")), timeoutMs);
    }

    /** Пуш всем открытым сеансам. */
    public void push(JSONObject msg) {
        for (Session s : sessions) {
            s.sendJson(msg);
        }
    }

    /** Команда телефону по контракту. */
    public void sendCommand(String id, String action, Object arg) {
        push(Json.obj("type", "command", "id", id, "action", action, "arg", arg));
    }

    /** Разорвать все соединения (имитация обрыва). */
    public void dropAll() {
        for (Session s : sessions) {
            if (s.ws != null) {
                try {
                    s.ws.close(1011, null);   // cancel() у серверного сокета MockWebServer недоступен
                } catch (RuntimeException ignored) {
                    // уже закрыт
                }
            }
        }
        sessions.clear();
    }

    public int openSessions() {
        int n = 0;
        for (Session s : sessions) {
            if (s.channel != null && !s.closed) {
                n++;
            }
        }
        return n;
    }

    @Override
    public void close() throws IOException {
        dropAll();
        timers.shutdownNow();
        web.close();
    }

    private static boolean isPrivate(String type) {
        return type.startsWith("chat_") || type.startsWith("history_") || type.startsWith("memory_")
                || type.startsWith("profile_") || type.startsWith("secure_") || "vision_request".equals(type);
    }

    private static boolean isV2(String type) {
        return isPrivate(type) || type.endsWith("_request") || type.startsWith("scenario")
                || "action_run".equals(type) || "secure_devices".equals(type);
    }

    final class Session extends WebSocketListener {
        WebSocket ws;
        HandshakeState hs;
        SecureChannel channel;
        boolean pairing;
        boolean failing;
        volatile boolean closed;
        String deviceId = "phone";

        @Override
        public void onOpen(WebSocket webSocket, Response response) {
            ws = webSocket;
        }

        @Override
        public synchronized void onMessage(WebSocket webSocket, ByteString bytes) {
            if (failing) {
                return;
            }
            byte[] data = bytes.toByteArray();
            try {
                if (mode == Mode.NOISE_OFF) {
                    webSocket.close(CloseCodes.PROTOCOL_ERROR, null);
                    return;
                }
                if (channel == null) {
                    handshake(FrameCodec.decodeFrame(data));
                    return;
                }
                for (SecureChannel.Received r : channel.open(data)) {
                    if (r.inner == FrameCodec.DATA) {
                        onJson(new JSONObject(new String(r.data, StandardCharsets.UTF_8)));
                    } else if (r.inner == FrameCodec.CLOSE) {
                        webSocket.close(1000, null);
                    }
                }
            } catch (Exception e) {
                failHandshake(channel == null ? CloseCodes.HANDSHAKE_FAILED : CloseCodes.INTEGRITY);
            }
        }

        @Override
        public void onMessage(WebSocket webSocket, String text) {
            webSocket.close(CloseCodes.SECURE_REQUIRED, null);
        }

        @Override
        public void onClosing(WebSocket webSocket, int code, String reason) {
            closed = true;
            closes.add(code);
            webSocket.close(code, null);
        }

        @Override
        public void onFailure(WebSocket webSocket, Throwable t, Response response) {
            closed = true;
        }

        /** Как сервер: любая неудача — молчание и 4408 в момент дедлайна. */
        private void failHandshake(int code) {
            failing = true;
            WebSocket w = ws;
            timers.schedule(() -> w.close(code, null), code == CloseCodes.HANDSHAKE_FAILED
                    ? handshakeFailDelayMs : 0, TimeUnit.MILLISECONDS);
        }

        private void handshake(FrameCodec.Frame f) throws Exception {
            if (f.type == FrameCodec.IK_INIT && hs == null) {
                hs = new HandshakeState(HandshakeState.Pattern.IK, false, SecureLink.PROLOGUE_SESSION,
                        serverPriv, null, null, null);
                byte[] p1 = hs.readMessage(f.body);
                String client = PairingCodes.b64url(hs.remoteStatic());
                if (!knownClients.contains(client)) {
                    failHandshake(CloseCodes.HANDSHAKE_FAILED);
                    return;
                }
                deviceId = new JSONObject(new String(p1, StandardCharsets.UTF_8)).optString("device_id", "phone");
                JSONObject p2 = Json.obj("v", 1, "session", "0123456789abcdef", "rekey_messages", rekeyMessages,
                        "rekey_seconds", 3600, "server_time", System.currentTimeMillis() / 1000.0);
                byte[] m2 = hs.writeMessage(p2.toString().getBytes(StandardCharsets.UTF_8));
                ws.send(ByteString.of(FrameCodec.encodeFrame(FrameCodec.IK_RESP, m2)));
                split();
            } else if (f.type == FrameCodec.XX_1 && hs == null) {
                if (pairingWords == null) {
                    failHandshake(CloseCodes.HANDSHAKE_FAILED);
                    return;
                }
                pairing = true;
                hs = new HandshakeState(HandshakeState.Pattern.XXPSK3, false, SecureLink.PROLOGUE_PAIR,
                        serverPriv, null, PairingCodes.wordsToPsk(pairingWords), null);
                hs.readMessage(f.body);
                ws.send(ByteString.of(FrameCodec.encodeFrame(FrameCodec.XX_2, hs.writeMessage(new byte[0]))));
            } else if (f.type == FrameCodec.XX_3 && pairing && hs.step() == 2) {
                hs.readMessage(f.body);   // неверный PSK → исключение → молчание и 4408
                byte[] client = hs.remoteStatic();
                split();
                allowClient(client);
                pairingWords = null;      // код одноразовый
                JSONObject paired = Json.obj("device_id", "phone", "server_pub", PairingCodes.b64url(serverPub),
                        "server_fp", PairingCodes.fingerprint(serverPub));
                for (byte[] fr : channel.control(FrameCodec.PAIRED, paired.toString().getBytes(StandardCharsets.UTF_8))) {
                    ws.send(ByteString.of(fr));
                }
                ws.close(1000, null);
            } else {
                failHandshake(CloseCodes.HANDSHAKE_FAILED);
            }
        }

        private void split() throws NoiseException {
            CipherState[] cs = hs.split();
            channel = new SecureChannel(cs[0], cs[1], rekeyMessages, 3600, System::currentTimeMillis);
        }

        synchronized void sendJson(JSONObject msg) {
            if (channel == null || closed || ws == null) {
                return;
            }
            try {
                for (byte[] f : channel.seal(msg.toString())) {
                    ws.send(ByteString.of(f));
                }
            } catch (Exception ignored) {
                // сеанс уже закрыт
            }
        }

        private void error(String rid, String code, String message) {
            sendJson(Json.obj("type", "error", "request_id", rid, "code", code, "message", message));
        }

        private void onJson(JSONObject m) throws Exception {
            received.add(m);
            String type = m.optString("type");
            String rid = m.optString("request_id", null);
            if ("register".equals(type)) {
                if (mode != Mode.UNSUPPORTED) {
                    sendJson(Json.obj("type", "registered", "device_id", deviceId, "proto", 2,
                            "master", mode != Mode.NOT_MASTER));
                }
                return;
            }
            if (rid != null && isV2(type)) {
                if (mode == Mode.UNSUPPORTED) {
                    error(rid, "unsupported", type + ": сервер не поддерживает proto 2");
                    return;
                }
                if (mode == Mode.NOT_MASTER) {
                    error(rid, "not_master", type + ": только для master-устройств");
                    return;
                }
                if (mode == Mode.SECURE_REQUIRED && isPrivate(type)) {
                    sendJson(Json.obj("type", "error", "request_id", rid, "code", "secure_channel_required",
                            "message", "нужен защищённый канал",
                            "hint", "подключитесь через защищённый канал (Noise) или VPN"));
                    return;
                }
            }
            switch (type) {
                case "voice_command":
                    answer(m.optString("text"), m.optString("channel", "voice"), m.optBoolean("speak", true));
                    break;
                case "chat_send":
                    sendJson(Json.obj("type", "chat_ack", "request_id", rid,
                            "client_msg_id", m.optString("client_msg_id"), "id", "41"));
                    sendJson(Json.obj("type", "chat_message", "message", message("41", "user", m.optString("text"),
                            "text")));
                    answer(m.optString("text"), "text", m.optBoolean("speak", true));
                    break;
                case "history_request":
                    JSONArray msgs = new JSONArray();
                    msgs.put(message("1", "user", "Привет", "voice"));
                    msgs.put(message("2", "assistant", "Привет, Мастер", "voice"));
                    sendJson(Json.obj("type", "history", "request_id", rid, "messages", msgs, "has_more", false));
                    break;
                case "devices_request":
                    sendJson(Json.obj("type", "devices", "request_id", rid, "devices", devices()));
                    break;
                case "status_request":
                    sendJson(Json.obj("type", "status", "request_id", rid, "tone", "calm", "mode", "обычный",
                            "context", "", "quote", "Тишина — тоже ответ."));
                    break;
                case "action_run":
                    actionRun(m, rid);
                    break;
                default:
                    if (rid != null) {
                        error(rid, "unsupported", type + ": пока не поддерживается");
                    }
            }
        }

        private void actionRun(JSONObject m, String rid) {
            String action = m.optString("action", "");
            if (action.isEmpty()) {
                error(rid, "bad_request", "action: обязательное поле");
                return;
            }
            if (action.startsWith("nope.")) {
                error(rid, "not_found", "нет такого действия");
                return;
            }
            sendJson(Json.obj("type", "action_started", "request_id", rid, "action", action, "id", "a1"));
            if (action.startsWith("system.") || action.startsWith("power.")) {
                sendJson(Json.obj("type", "reply", "kind", "confirm", "text", "Выключить игровой компьютер? Да или нет?",
                        "turn_id", "t-confirm"));
            }
        }

        private void answer(String text, String channel, boolean speak) {
            boolean yes = text.trim().equalsIgnoreCase("да");
            String reply = yes ? "Выключаю игровой компьютер." : "Слышу: " + text;
            sendJson(Json.obj("type", "reply", "text", reply, "kind", "llm", "turn_id", "t1"));
            if (speak) {
                byte[] pcm = new byte[480];
                sendJson(Json.obj("type", "tts_chunk", "turn_id", "t1", "sample_rate", 24000,
                        "data", Base64.getEncoder().encodeToString(pcm)));
                sendJson(Json.obj("type", "tts_end", "turn_id", "t1"));
            }
            sendJson(Json.obj("type", "chat_message", "message", message("42", "assistant", reply, channel)));
        }

        private JSONObject message(String id, String role, String text, String channel) {
            return Json.obj("id", id, "ts", 1791900000.0 + Integer.parseInt(id), "role", role, "text", text,
                    "channel", channel, "device", "phone");
        }

        private JSONArray devices() {
            JSONArray a = new JSONArray();
            a.put(Json.obj("id", "pc", "name", "Игровой", "kind", "pc", "online", true, "active", true,
                    "last_seen", 1791900000.0, "track", pcTrack == null ? JSONObject.NULL : pcTrack,
                    "stats", Json.obj("cpu", 12, "ram", 40, "gpu", 3, "battery", JSONObject.NULL)));
            a.put(Json.obj("id", "phone", "name", "Телефон", "kind", "phone", "online", true, "active", false,
                    "last_seen", 1791900000.0, "track", JSONObject.NULL,
                    "stats", Json.obj("battery", 78, "charging", false, "wifi", "wifi", "signal", 3)));
            return a;
        }
    }
}
