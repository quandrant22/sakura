package app.sakura.mobile.link;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.function.LongSupplier;

import app.sakura.mobile.crypto.noise.CipherState;
import app.sakura.mobile.crypto.noise.NoiseException;

/**
 * Канал после рукопожатия (PROTOCOL.md §4): seal/open кадров TRANSPORT, rekey §4.4, ping, close.
 * Получатель расшифровывает строго следующим nonce: любое расхождение → IntegrityException (4409).
 * Не потокобезопасен: отправка и приём синхронизируются снаружи (SecureLink).
 */
public final class SecureChannel {

    /** Кадр не расшифровался или нарушен порядок (→ 4409). */
    public static final class IntegrityException extends Exception {
        public IntegrityException(String message) {
            super(message);
        }
    }

    /** Результат open(): внутренний тип и данные (DATA — целое сообщение). */
    public static final class Received {
        public final int inner;
        public final byte[] data;

        Received(int inner, byte[] data) {
            this.inner = inner;
            this.data = data;
        }
    }

    private final CipherState send;
    private final CipherState recv;
    private final long rekeyMessages;
    private final long rekeyMillis;
    private final LongSupplier clockMillis;
    private final FrameCodec.Reassembler asm = new FrameCodec.Reassembler();
    private long sentSince;
    private long rekeyAt;
    private int rekeysOut;
    private int rekeysIn;

    public SecureChannel(CipherState send, CipherState recv, long rekeyMessages, double rekeySeconds,
                         LongSupplier clockMillis) {
        this.send = send;
        this.recv = recv;
        this.rekeyMessages = rekeyMessages > 0 ? rekeyMessages : 10000;
        this.rekeyMillis = rekeySeconds > 0 ? (long) (rekeySeconds * 1000) : 3_600_000L;
        this.clockMillis = clockMillis;
        this.rekeyAt = clockMillis.getAsLong();
    }

    /** Как на сервере (securechannel/channel.py): в счётчик rekey идёт каждый отправленный кадр. */
    private byte[] sealInner(byte[] innerPlain) throws NoiseException, FrameCodec.FrameException {
        byte[] frame = FrameCodec.encodeFrame(FrameCodec.TRANSPORT, send.encryptWithAd(new byte[0], innerPlain));
        sentSince++;
        return frame;
    }

    private void maybeRekey(List<byte[]> out) throws NoiseException, FrameCodec.FrameException {
        boolean due = sentSince >= rekeyMessages || clockMillis.getAsLong() - rekeyAt >= rekeyMillis;
        if (!due) {
            return;
        }
        out.add(sealInner(FrameCodec.encodeInner(FrameCodec.REKEY, 0, new byte[0])));  // на старом ключе
        send.rekey();
        sentSince = 0;
        rekeyAt = clockMillis.getAsLong();
        rekeysOut++;
    }

    /** Сообщение приложения → кадры TRANSPORT (фрагментация и rekey по лимитам). */
    public List<byte[]> seal(String message) throws NoiseException, FrameCodec.FrameException {
        return seal(message.getBytes(StandardCharsets.UTF_8));
    }

    public List<byte[]> seal(byte[] data) throws NoiseException, FrameCodec.FrameException {
        List<byte[]> out = new ArrayList<>();
        for (byte[] chunk : FrameCodec.fragment(data)) {
            maybeRekey(out);
            out.add(sealInner(chunk));
        }
        return out;
    }

    /** Служебный кадр (PING/PONG), перед ним — REKEY, если пора. */
    private List<byte[]> control(int inner, byte[] data) throws NoiseException, FrameCodec.FrameException {
        byte[] d = data.length > 32 ? java.util.Arrays.copyOf(data, 32) : data;
        List<byte[]> out = new ArrayList<>(2);
        maybeRekey(out);
        out.add(sealInner(FrameCodec.encodeInner(inner, 0, d)));
        return out;
    }

    public List<byte[]> ping(byte[] data) throws NoiseException, FrameCodec.FrameException {
        return control(FrameCodec.PING, data);
    }

    public List<byte[]> pong(byte[] echo) throws NoiseException, FrameCodec.FrameException {
        return control(FrameCodec.PONG, echo);
    }

    public byte[] closeFrame(int code, String reason) throws NoiseException, FrameCodec.FrameException {
        byte[] r = reason.getBytes(StandardCharsets.UTF_8);
        int n = Math.min(r.length, 120);
        byte[] body = new byte[2 + n];
        body[0] = (byte) (code >>> 8);
        body[1] = (byte) code;
        System.arraycopy(r, 0, body, 2, n);
        return sealInner(FrameCodec.encodeInner(FrameCodec.CLOSE, 0, body));
    }

    /** Кадр → список полученного (пустой, если кусок сообщения или REKEY). */
    public List<Received> open(byte[] frame) throws IntegrityException, FrameCodec.TooLargeException {
        FrameCodec.Frame f;
        try {
            f = FrameCodec.decodeFrame(frame);
        } catch (FrameCodec.FrameException e) {
            throw new IntegrityException(e.getMessage());
        }
        if (f.type != FrameCodec.TRANSPORT) {
            throw new IntegrityException("после рукопожатия допустимы только кадры TRANSPORT");
        }
        byte[] plain;
        try {
            plain = recv.decryptWithAd(new byte[0], f.body);
        } catch (NoiseException e) {
            throw new IntegrityException("кадр не расшифровался");
        }
        FrameCodec.Inner in;
        try {
            in = FrameCodec.decodeInner(plain);
        } catch (FrameCodec.FrameException e) {
            throw new IntegrityException(e.getMessage());
        }
        if (in.type == FrameCodec.REKEY) {
            try {
                recv.rekey();
            } catch (NoiseException e) {
                throw new IntegrityException("rekey не удался");
            }
            rekeysIn++;
            return Collections.emptyList();
        }
        if (asm.inProgress() && in.type != FrameCodec.DATA && in.type != FrameCodec.PING
                && in.type != FrameCodec.PONG) {
            throw new IntegrityException("посторонний кадр посреди сообщения");
        }
        if (in.type == FrameCodec.DATA) {
            byte[] msg = asm.feed(in.flags, in.data);
            return msg == null ? Collections.emptyList()
                    : Collections.singletonList(new Received(FrameCodec.DATA, msg));
        }
        return Collections.singletonList(new Received(in.type, in.data));
    }

    public int rekeysOut() {
        return rekeysOut;
    }

    public int rekeysIn() {
        return rekeysIn;
    }

    public void destroy() {
        send.destroy();
        recv.destroy();
    }
}
