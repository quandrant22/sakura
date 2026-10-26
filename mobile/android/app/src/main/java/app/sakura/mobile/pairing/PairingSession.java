package app.sakura.mobile.pairing;

import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import app.sakura.mobile.crypto.noise.CipherState;
import app.sakura.mobile.crypto.noise.HandshakeState;
import app.sakura.mobile.crypto.noise.NoiseException;
import app.sakura.mobile.keys.DeviceKeyStore;
import app.sakura.mobile.link.CloseCodes;
import app.sakura.mobile.link.FrameCodec;
import app.sakura.mobile.link.SecureChannel;
import app.sakura.mobile.link.SecureLink;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/**
 * Спаривание Noise_XXpsk3 (PROTOCOL.md §3.3). Сервер считается подлинным только после того, как
 * расшифрован кадр PAIRED; при QR ключ из XX_2 сверяется с k до отправки XX_3.
 */
public final class PairingSession {
    static final long STEP_TIMEOUT_MS = 8000;

    public interface Callback {
        void onPaired(DeviceKeyStore.Server server, String fingerprint);

        void onFailed(String message);
    }

    private final OkHttpClient http;
    private final DeviceKeyStore keys;
    private final ScheduledExecutorService scheduler;
    private final Callback callback;

    private String url;
    private byte[] expectedKey;
    private HandshakeState hs;
    private SecureChannel channel;
    private WebSocket ws;
    private ScheduledFuture<?> timeout;
    private boolean done;

    public PairingSession(OkHttpClient http, DeviceKeyStore keys, ScheduledExecutorService scheduler,
                          Callback callback) {
        this.http = http;
        this.keys = keys;
        this.scheduler = scheduler;
        this.callback = callback;
    }

    /** По QR: адрес, ключ и слова из кода. */
    public void startFromQr(PairingCodes.QrPayload qr) {
        start(qr.url, qr.words, qr.serverPub);
    }

    /** Ручной ввод: адрес и 8 слов, ключ сервера сверяется глазами по отпечатку. */
    public void startManual(String serverUrl, String words) {
        start(serverUrl, words, null);
    }

    private synchronized void start(String serverUrl, String words, byte[] serverKey) {
        byte[] psk;
        byte[] priv;
        try {
            psk = PairingCodes.wordsToPsk(words);
            priv = keys.devicePrivate();
        } catch (PairingCodes.PairingException e) {
            fail(e.getMessage());
            return;
        } catch (Exception e) {
            fail("не удалось создать ключ устройства");
            return;
        }
        if (!(serverUrl.startsWith("ws://") || serverUrl.startsWith("wss://"))) {
            fail("адрес сервера должен начинаться с ws:// или wss://");
            return;
        }
        url = serverUrl;
        expectedKey = serverKey;
        hs = HandshakeState.xxInitiator(SecureLink.PROLOGUE_PAIR, priv, psk);
        Arrays.fill(priv, (byte) 0);
        Arrays.fill(psk, (byte) 0);
        ws = http.newWebSocket(new Request.Builder().url(serverUrl).build(), new Listener());
        armTimeout();
    }

    private void armTimeout() {
        if (timeout != null) {
            timeout.cancel(false);
        }
        timeout = scheduler.schedule(() -> {
            synchronized (this) {
                fail("сервер не ответил: неверные слова, истёк срок или код уже использован");
            }
        }, STEP_TIMEOUT_MS, TimeUnit.MILLISECONDS);
    }

    public synchronized void cancel() {
        fail("спаривание отменено");
    }

    private void fail(String message) {
        if (done) {
            return;
        }
        done = true;
        if (timeout != null) {
            timeout.cancel(false);
        }
        if (ws != null) {
            ws.cancel();
        }
        if (channel != null) {
            channel.destroy();
        }
        scheduler.execute(() -> callback.onFailed(message));
    }

    private synchronized void onOpen(WebSocket socket) {
        if (done) {
            return;
        }
        try {
            socket.send(ByteString.of(FrameCodec.encodeFrame(FrameCodec.XX_1, hs.writeMessage(new byte[0]))));
        } catch (NoiseException | FrameCodec.FrameException e) {
            fail("ошибка протокола спаривания");
        }
    }

    private synchronized void onBinary(byte[] data) {
        if (done) {
            return;
        }
        try {
            if (channel == null) {
                FrameCodec.Frame f = FrameCodec.decodeFrame(data);
                if (f.type != FrameCodec.XX_2 || hs.step() != 1) {
                    fail("ошибка протокола спаривания");
                    return;
                }
                hs.readMessage(f.body);
                byte[] rs = hs.remoteStatic();
                if (expectedKey != null && !MessageDigest.isEqual(rs, expectedKey)) {
                    fail("ключ сервера не совпал с QR — спаривание прервано");
                    return;
                }
                JSONObject p = new JSONObject()
                        .put("v", 1)
                        .put("name", "Телефон")
                        .put("kind", "phone")
                        .put("device_id_hint", "phone");
                byte[] m3 = hs.writeMessage(p.toString().getBytes(StandardCharsets.UTF_8));
                ws.send(ByteString.of(FrameCodec.encodeFrame(FrameCodec.XX_3, m3)));
                CipherState[] cs = hs.split();
                channel = new SecureChannel(cs[0], cs[1], 10000, 3600, System::currentTimeMillis);
                armTimeout();
                return;
            }
            List<SecureChannel.Received> got = channel.open(data);
            for (SecureChannel.Received r : got) {
                if (r.inner != FrameCodec.PAIRED) {
                    continue;
                }
                JSONObject o = new JSONObject(new String(r.data, StandardCharsets.UTF_8));
                byte[] rs = hs.remoteStatic();
                byte[] announced = PairingCodes.unb64url(o.getString("server_pub"));
                if (!MessageDigest.isEqual(rs, announced)) {
                    fail("сервер прислал чужой ключ — спаривание прервано");
                    return;
                }
                DeviceKeyStore.Server server = new DeviceKeyStore.Server(url, rs, o.getString("device_id"),
                        System.currentTimeMillis() / 1000.0);
                keys.saveServer(server);
                done = true;
                timeout.cancel(false);
                ws.close(CloseCodes.NORMAL, null);
                channel.destroy();
                String fp = PairingCodes.fingerprint(rs);
                scheduler.execute(() -> callback.onPaired(server, fp));
                return;
            }
        } catch (NoiseException | FrameCodec.FrameException | SecureChannel.IntegrityException
                 | JSONException | IllegalArgumentException e) {
            fail("ошибка протокола спаривания");
        } catch (java.io.IOException e) {
            fail("не удалось сохранить ключ сервера");
        }
    }

    private final class Listener extends WebSocketListener {
        @Override
        public void onOpen(WebSocket webSocket, Response response) {
            PairingSession.this.onOpen(webSocket);
        }

        @Override
        public void onMessage(WebSocket webSocket, ByteString bytes) {
            onBinary(bytes.toByteArray());
        }

        @Override
        public void onMessage(WebSocket webSocket, String text) {
            synchronized (PairingSession.this) {
                fail("сервер без защищённого канала");
            }
        }

        @Override
        public void onClosing(WebSocket webSocket, int code, String reason) {
            synchronized (PairingSession.this) {
                fail(code == CloseCodes.HANDSHAKE_FAILED
                        ? "сервер отклонил код: неверные слова, истёк срок или код уже использован"
                        : CloseCodes.describe(code));
            }
        }

        @Override
        public void onFailure(WebSocket webSocket, Throwable t, Response response) {
            synchronized (PairingSession.this) {
                fail("нет связи с сервером");
            }
        }
    }
}
