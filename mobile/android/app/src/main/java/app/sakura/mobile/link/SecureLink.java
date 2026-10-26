package app.sakura.mobile.link;

import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Random;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;

import app.sakura.mobile.crypto.noise.CipherState;
import app.sakura.mobile.crypto.noise.HandshakeState;
import app.sakura.mobile.crypto.noise.NoiseException;
import app.sakura.mobile.keys.DeviceKeyStore;
import app.sakura.mobile.pairing.PairingCodes;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/**
 * Сеанс securechannel/1 (IK) на OkHttp WebSocket с переподключением 1→30 с.
 * Наружу — только JSON-сообщения приложения; ключи и содержимое не журналируются.
 */
public final class SecureLink {
    public static final byte[] PROLOGUE_SESSION = prologue("session");
    public static final byte[] PROLOGUE_PAIR = prologue("pair");
    /** Сервер молчит при неудаче до 5 с; ждём с запасом. */
    static final long HANDSHAKE_TIMEOUT_MS = 8000;

    public enum State { UNPAIRED, CONNECTING, OPEN, WAITING, STOPPED }

    public interface Listener {
        void onState(State state, int lastCloseCode);

        void onMessage(String json);
    }

    static byte[] prologue(String purpose) {
        byte[] base = "sakura-securechannel/1\u0000".getBytes(StandardCharsets.US_ASCII);
        byte[] p = purpose.getBytes(StandardCharsets.US_ASCII);
        byte[] out = new byte[base.length + p.length];
        System.arraycopy(base, 0, out, 0, base.length);
        System.arraycopy(p, 0, out, base.length, p.length);
        return out;
    }

    private final OkHttpClient http;
    private final DeviceKeyStore keys;
    private final Listener listener;
    private final ScheduledExecutorService scheduler;
    private final LongSupplier clockMillis;
    private final Backoff backoff;

    private boolean running;
    private WebSocket ws;
    private HandshakeState hs;
    private SecureChannel channel;
    private String deviceId;
    private ScheduledFuture<?> pending;
    private int lastCloseCode;
    private State state = State.STOPPED;
    private long generation;

    public SecureLink(OkHttpClient http, DeviceKeyStore keys, Listener listener,
                      ScheduledExecutorService scheduler, LongSupplier clockMillis, Random random) {
        this.http = http;
        this.keys = keys;
        this.listener = listener;
        this.scheduler = scheduler;
        this.clockMillis = clockMillis;
        this.backoff = new Backoff(random);
    }

    public synchronized State state() {
        return state;
    }

    public synchronized int lastCloseCode() {
        return lastCloseCode;
    }

    public synchronized String deviceId() {
        return deviceId;
    }

    private void setState(State s) {
        state = s;
        State snapshot = s;
        int code = lastCloseCode;
        scheduler.execute(() -> listener.onState(snapshot, code));
    }

    public synchronized void start() {
        if (running) {
            return;
        }
        running = true;
        connectLocked();
    }

    /** Немедленная попытка (после смены сети или по кнопке). */
    public synchronized void reconnectNow() {
        if (!running || state == State.OPEN || state == State.CONNECTING) {
            return;
        }
        if (pending != null) {
            pending.cancel(false);
        }
        backoff.reset();
        connectLocked();
    }

    private void connectLocked() {
        DeviceKeyStore.Server server = keys.server();
        if (server == null) {
            setState(State.UNPAIRED);
            return;
        }
        byte[] priv;
        try {
            priv = keys.devicePrivate();
        } catch (Exception e) {
            setState(State.UNPAIRED);
            return;
        }
        deviceId = server.deviceId;
        hs = HandshakeState.ikInitiator(PROLOGUE_SESSION, priv, server.pub);
        java.util.Arrays.fill(priv, (byte) 0);
        channel = null;
        final long gen = ++generation;
        setState(State.CONNECTING);
        Request req = new Request.Builder().url(server.url).build();
        ws = http.newWebSocket(req, new Socket(gen));
        pending = scheduler.schedule(() -> handshakeTimeout(gen), HANDSHAKE_TIMEOUT_MS, TimeUnit.MILLISECONDS);
    }

    private synchronized void handshakeTimeout(long gen) {
        if (gen == generation && channel == null && ws != null) {
            ws.cancel();
            onDown(gen, CloseCodes.HANDSHAKE_FAILED);
        }
    }

    /** Отправка сообщения приложения; false — канал не открыт. */
    public synchronized boolean send(String json) {
        if (channel == null || ws == null) {
            return false;
        }
        try {
            for (byte[] f : channel.seal(json)) {
                if (!ws.send(ByteString.of(f))) {
                    return false;
                }
            }
            return true;
        } catch (FrameCodec.TooLargeException e) {
            return false;
        } catch (NoiseException | FrameCodec.FrameException e) {
            failLocked(CloseCodes.PROTOCOL_ERROR);
            return false;
        }
    }

    public synchronized void stop() {
        running = false;
        generation++;
        if (pending != null) {
            pending.cancel(false);
        }
        if (ws != null) {
            if (channel != null) {
                try {
                    ws.send(ByteString.of(channel.closeFrame(CloseCodes.NORMAL, "bye")));
                } catch (NoiseException | FrameCodec.FrameException ignored) {
                    // закрываем без вежливого кадра
                }
            }
            ws.close(CloseCodes.NORMAL, "bye");
        }
        dropSession();
        setState(State.STOPPED);
    }

    private void dropSession() {
        if (channel != null) {
            channel.destroy();
        }
        channel = null;
        hs = null;
        ws = null;
    }

    private void failLocked(int code) {
        if (ws != null) {
            if (channel != null && code != CloseCodes.INTEGRITY) {
                try {
                    ws.send(ByteString.of(channel.closeFrame(code, "")));
                } catch (NoiseException | FrameCodec.FrameException ignored) {
                    // всё равно закрываем
                }
            }
            ws.close(code, null);
        }
        onDownLocked(code);
    }

    private synchronized void onDown(long gen, int code) {
        if (gen != generation) {
            return;
        }
        onDownLocked(code);
    }

    private void onDownLocked(int code) {
        generation++;
        lastCloseCode = code;
        dropSession();
        if (pending != null) {
            pending.cancel(false);
        }
        if (!running) {
            setState(State.STOPPED);
            return;
        }
        setState(State.WAITING);
        long delay = backoff.nextDelayMs();
        pending = scheduler.schedule(this::retry, delay, TimeUnit.MILLISECONDS);
    }

    private synchronized void retry() {
        if (running && state == State.WAITING) {
            connectLocked();
        }
    }

    private synchronized void onOpen(long gen, WebSocket socket) {
        if (gen != generation) {
            return;
        }
        try {
            JSONObject p = new JSONObject()
                    .put("v", 1)
                    .put("device_id", deviceId)
                    .put("ts", System.currentTimeMillis() / 1000.0);
            byte[] m1 = hs.writeMessage(p.toString().getBytes(StandardCharsets.UTF_8));
            socket.send(ByteString.of(FrameCodec.encodeFrame(FrameCodec.IK_INIT, m1)));
        } catch (JSONException | NoiseException | FrameCodec.FrameException e) {
            failLocked(CloseCodes.PROTOCOL_ERROR);
        }
    }

    private synchronized void onBinary(long gen, byte[] data) {
        if (gen != generation || ws == null) {
            return;
        }
        if (channel == null) {
            handshakeReply(data);
            return;
        }
        List<SecureChannel.Received> got;
        try {
            got = channel.open(data);
        } catch (SecureChannel.IntegrityException e) {
            failLocked(CloseCodes.INTEGRITY);
            return;
        } catch (FrameCodec.TooLargeException e) {
            failLocked(CloseCodes.TOO_LARGE);
            return;
        }
        for (SecureChannel.Received r : got) {
            switch (r.inner) {
                case FrameCodec.DATA:
                    deliver(new String(r.data, StandardCharsets.UTF_8));
                    break;
                case FrameCodec.PING:
                    try {
                        for (byte[] f : channel.pong(r.data)) {
                            ws.send(ByteString.of(f));
                        }
                    } catch (NoiseException | FrameCodec.FrameException e) {
                        failLocked(CloseCodes.PROTOCOL_ERROR);
                        return;
                    }
                    break;
                case FrameCodec.CLOSE: {
                    int code = r.data.length >= 2 ? ((r.data[0] & 0xFF) << 8) | (r.data[1] & 0xFF) : 1000;
                    ws.close(CloseCodes.NORMAL, null);
                    onDownLocked(code);
                    return;
                }
                case FrameCodec.PONG:
                    break;
                default:
                    failLocked(CloseCodes.PROTOCOL_ERROR);
                    return;
            }
        }
    }

    private void handshakeReply(byte[] data) {
        try {
            FrameCodec.Frame f = FrameCodec.decodeFrame(data);
            if (f.type != FrameCodec.IK_RESP) {
                failLocked(CloseCodes.PROTOCOL_ERROR);
                return;
            }
            byte[] payload = hs.readMessage(f.body);
            JSONObject p = new JSONObject(new String(payload, StandardCharsets.UTF_8));
            CipherState[] cs = hs.split();
            channel = new SecureChannel(cs[0], cs[1], p.optLong("rekey_messages", 10000),
                    p.optDouble("rekey_seconds", 3600), clockMillis);
            hs = null;
            if (pending != null) {
                pending.cancel(false);
            }
            backoff.reset();
            lastCloseCode = 0;
            setState(State.OPEN);
        } catch (FrameCodec.FrameException | NoiseException | JSONException e) {
            failLocked(CloseCodes.HANDSHAKE_FAILED);
        }
    }

    private void deliver(String json) {
        if (json.contains("\"secure_server_key\"")) {
            try {
                JSONObject o = new JSONObject(json);
                if ("secure_server_key".equals(o.optString("type"))) {
                    keys.rotateServerKey(PairingCodes.unb64url(o.getString("pub")));
                    return;
                }
            } catch (Exception ignored) {
                // не наш формат — отдаём как есть
            }
        }
        scheduler.execute(() -> listener.onMessage(json));
    }

    private final class Socket extends WebSocketListener {
        private final long gen;

        Socket(long gen) {
            this.gen = gen;
        }

        @Override
        public void onOpen(WebSocket webSocket, Response response) {
            SecureLink.this.onOpen(gen, webSocket);
        }

        @Override
        public void onMessage(WebSocket webSocket, ByteString bytes) {
            onBinary(gen, bytes.toByteArray());
        }

        @Override
        public void onMessage(WebSocket webSocket, String text) {
            synchronized (SecureLink.this) {
                if (gen == generation) {
                    failLocked(CloseCodes.PROTOCOL_ERROR);
                }
            }
        }

        @Override
        public void onClosing(WebSocket webSocket, int code, String reason) {
            webSocket.close(code, null);
            onDown(gen, code);
        }

        @Override
        public void onClosed(WebSocket webSocket, int code, String reason) {
            onDown(gen, code);
        }

        @Override
        public void onFailure(WebSocket webSocket, Throwable t, Response response) {
            onDown(gen, 0);
        }
    }
}
