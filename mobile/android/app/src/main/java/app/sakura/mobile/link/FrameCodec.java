package app.sakura.mobile.link;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Кадры securechannel/1 (PROTOCOL.md §2, §4.1–4.2): внешний кадр «SK», внутренний заголовок,
 * фрагментация. Длина в заголовке обязана совпадать с реальной.
 */
public final class FrameCodec {
    public static final byte MAGIC_0 = 0x53;
    public static final byte MAGIC_1 = 0x4B;
    public static final int VERSION = 0x01;
    public static final int HEADER = 8;
    public static final int MAX_BODY = 65535;
    public static final int MAX_CHUNK = 65535 - 16 - 2;
    public static final int MAX_MESSAGE = 2 * 1024 * 1024;
    public static final int MAX_FRAGMENTS = 64;
    public static final int FLAG_MORE = 0x01;

    public static final int IK_INIT = 0x01;
    public static final int IK_RESP = 0x02;
    public static final int XX_1 = 0x11;
    public static final int XX_2 = 0x12;
    public static final int XX_3 = 0x13;
    public static final int TRANSPORT = 0x20;

    public static final int DATA = 0x01;
    public static final int REKEY = 0x02;
    public static final int CLOSE = 0x03;
    public static final int PING = 0x04;
    public static final int PONG = 0x05;
    public static final int PAIRED = 0x06;

    /** Нарушение формата (→ 4400). */
    public static class FrameException extends Exception {
        public FrameException(String message) {
            super(message);
        }
    }

    /** Больше 2 МиБ или 64 кусков (→ 4413). */
    public static final class TooLargeException extends FrameException {
        public TooLargeException(String message) {
            super(message);
        }
    }

    public static final class Frame {
        public final int type;
        public final byte[] body;

        Frame(int type, byte[] body) {
            this.type = type;
            this.body = body;
        }
    }

    public static final class Inner {
        public final int type;
        public final int flags;
        public final byte[] data;

        Inner(int type, int flags, byte[] data) {
            this.type = type;
            this.flags = flags;
            this.data = data;
        }
    }

    private FrameCodec() {
    }

    static boolean knownFrameType(int t) {
        return t == IK_INIT || t == IK_RESP || t == XX_1 || t == XX_2 || t == XX_3 || t == TRANSPORT;
    }

    public static byte[] encodeFrame(int type, byte[] body) throws FrameException {
        if (body.length > MAX_BODY) {
            throw new FrameException("тело кадра больше 65535 байт");
        }
        byte[] out = new byte[HEADER + body.length];
        out[0] = MAGIC_0;
        out[1] = MAGIC_1;
        out[2] = VERSION;
        out[3] = (byte) type;
        int n = body.length;
        out[4] = (byte) (n >>> 24);
        out[5] = (byte) (n >>> 16);
        out[6] = (byte) (n >>> 8);
        out[7] = (byte) n;
        System.arraycopy(body, 0, out, HEADER, n);
        return out;
    }

    public static Frame decodeFrame(byte[] data) throws FrameException {
        if (data == null || data.length < HEADER) {
            throw new FrameException("короткий кадр");
        }
        if (data[0] != MAGIC_0 || data[1] != MAGIC_1 || (data[2] & 0xFF) != VERSION) {
            throw new FrameException("не кадр securechannel/1");
        }
        long length = ((long) (data[4] & 0xFF) << 24) | ((data[5] & 0xFF) << 16)
                | ((data[6] & 0xFF) << 8) | (data[7] & 0xFF);
        if (length > MAX_BODY || length != data.length - HEADER) {
            throw new FrameException("длина кадра не совпадает");
        }
        int type = data[3] & 0xFF;
        if (!knownFrameType(type)) {
            throw new FrameException("неизвестный тип кадра");
        }
        return new Frame(type, Arrays.copyOfRange(data, HEADER, data.length));
    }

    public static byte[] encodeInner(int inner, int flags, byte[] data) {
        byte[] out = new byte[2 + data.length];
        out[0] = (byte) inner;
        out[1] = (byte) flags;
        System.arraycopy(data, 0, out, 2, data.length);
        return out;
    }

    public static Inner decodeInner(byte[] plain) throws FrameException {
        if (plain.length < 2) {
            throw new FrameException("короткий внутренний заголовок");
        }
        int inner = plain[0] & 0xFF;
        if (inner < DATA || inner > PAIRED) {
            throw new FrameException("неизвестный внутренний тип");
        }
        int flags = plain[1] & 0xFF;
        if ((flags & ~FLAG_MORE) != 0) {
            throw new FrameException("неизвестные флаги");
        }
        return new Inner(inner, flags, Arrays.copyOfRange(plain, 2, plain.length));
    }

    /** Куски DATA (без шифрования): каждый ≤ MAX_CHUNK, у всех, кроме последнего, флаг MORE. */
    public static List<byte[]> fragment(byte[] message) throws TooLargeException {
        if (message.length > MAX_MESSAGE) {
            throw new TooLargeException("сообщение больше 2 МиБ");
        }
        int count = Math.max(1, (message.length + MAX_CHUNK - 1) / MAX_CHUNK);
        if (count > MAX_FRAGMENTS) {
            throw new TooLargeException("больше 64 кусков");
        }
        List<byte[]> out = new ArrayList<>(count);
        for (int i = 0; i < count; i++) {
            int from = i * MAX_CHUNK;
            int to = Math.min(message.length, from + MAX_CHUNK);
            out.add(encodeInner(DATA, i < count - 1 ? FLAG_MORE : 0, Arrays.copyOfRange(message, from, to)));
        }
        return out;
    }

    /** Сборка DATA-кусков в сообщение; лимиты 2 МиБ и 64 куска. */
    public static final class Reassembler {
        private final ByteArrayOutputStream parts = new ByteArrayOutputStream();
        private int count;

        public byte[] feed(int flags, byte[] data) throws TooLargeException {
            parts.writeBytes(data);
            count++;
            if (parts.size() > MAX_MESSAGE || count > MAX_FRAGMENTS) {
                reset();
                throw new TooLargeException("сообщение больше лимита");
            }
            if ((flags & FLAG_MORE) != 0) {
                return null;
            }
            byte[] out = parts.toByteArray();
            reset();
            return out;
        }

        public boolean inProgress() {
            return count > 0;
        }

        private void reset() {
            parts.reset();
            count = 0;
        }
    }
}
