package app.sakura.mobile.crypto.noise;

import java.io.ByteArrayOutputStream;
import java.util.Arrays;

/**
 * HandshakeState Noise rev 34 для двух шаблонов securechannel/1:
 * IK (сеанс) и XXpsk3 (спаривание), набор 25519_ChaChaPoly_BLAKE2s.
 * write/read строго поочерёдно, затем split().
 */
public final class HandshakeState {

    public enum Pattern {
        IK("IK", new String[]{"s"}, new String[][]{{"e", "es", "s", "ss"}, {"e", "ee", "se"}}),
        XXPSK3("XXpsk3", new String[0], new String[][]{{"e"}, {"e", "ee", "s", "es"}, {"s", "se", "psk"}});

        final String noiseName;
        final String[] responderPre;
        final String[][] messages;

        Pattern(String noiseName, String[] responderPre, String[][] messages) {
            this.noiseName = noiseName;
            this.responderPre = responderPre;
            this.messages = messages;
        }

        public String protocolName() {
            return "Noise_" + noiseName + "_25519_ChaChaPoly_BLAKE2s";
        }
    }

    public static final int MAX_MESSAGE = 65535;

    private final Pattern pattern;
    private final boolean initiator;
    private final boolean pskMode;
    private final byte[] psk;
    private final SymmetricState ss;
    private final byte[] sPriv;
    private final byte[] sPub;
    private final byte[] fixedE;
    private byte[] ePriv;
    private byte[] ePub;
    private byte[] rs;
    private byte[] re;
    private int step;

    /**
     * @param sPriv  свой статический ключ
     * @param rs     открытый ключ ответчика (IK-инициатор), иначе null
     * @param psk    32 байта для XXpsk3, иначе null
     * @param fixedE фиксированный эфемерный ключ — только для векторов и транскриптов
     */
    public HandshakeState(Pattern pattern, boolean initiator, byte[] prologue, byte[] sPriv,
                          byte[] rs, byte[] psk, byte[] fixedE) {
        this.pattern = pattern;
        this.initiator = initiator;
        this.pskMode = pattern == Pattern.XXPSK3;
        if (pskMode && (psk == null || psk.length != 32)) {
            throw new IllegalArgumentException("нужен psk 32 байта");
        }
        this.psk = psk == null ? null : psk.clone();
        this.sPriv = sPriv == null ? null : sPriv.clone();
        this.sPub = sPriv == null ? null : Primitives.publicFromPrivate(sPriv);
        this.fixedE = fixedE == null ? null : fixedE.clone();
        this.rs = rs == null ? null : rs.clone();
        this.ss = new SymmetricState(pattern.protocolName());
        ss.mixHash(prologue);
        for (String tok : pattern.responderPre) {
            if ("s".equals(tok)) {
                byte[] key = initiator ? this.rs : sPub;
                if (key == null) {
                    throw new IllegalArgumentException("IK: инициатору нужен открытый ключ ответчика");
                }
                ss.mixHash(key);
            }
        }
    }

    public static HandshakeState ikInitiator(byte[] prologue, byte[] sPriv, byte[] serverPub) {
        return new HandshakeState(Pattern.IK, true, prologue, sPriv, serverPub, null, null);
    }

    public static HandshakeState xxInitiator(byte[] prologue, byte[] sPriv, byte[] psk) {
        return new HandshakeState(Pattern.XXPSK3, true, prologue, sPriv, null, psk, null);
    }

    public boolean isComplete() {
        return step >= pattern.messages.length;
    }

    public byte[] handshakeHash() {
        return ss.handshakeHash();
    }

    /** Открытый статический ключ собеседника (после токена «s» или из пред-сообщения). */
    public byte[] remoteStatic() {
        return rs == null ? null : rs.clone();
    }

    /** Номер следующего сообщения рукопожатия (0, 1, 2). */
    public int step() {
        return step;
    }

    private boolean myTurn() {
        return (step % 2 == 0) == initiator;
    }

    private byte[] dhFor(String tok) throws NoiseException {
        switch (tok) {
            case "ee":
                return Primitives.dh(ePriv, re);
            case "ss":
                return Primitives.dh(sPriv, rs);
            case "es":
                return initiator ? Primitives.dh(ePriv, rs) : Primitives.dh(sPriv, re);
            case "se":
                return initiator ? Primitives.dh(sPriv, re) : Primitives.dh(ePriv, rs);
            default:
                throw new IllegalStateException(tok);
        }
    }

    public byte[] writeMessage(byte[] payload) throws NoiseException {
        if (isComplete() || !myTurn()) {
            throw new NoiseException("не наша очередь писать");
        }
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        for (String tok : pattern.messages[step]) {
            switch (tok) {
                case "e":
                    if (fixedE != null) {
                        ePriv = fixedE.clone();
                        ePub = Primitives.publicFromPrivate(ePriv);
                    } else {
                        byte[][] kp = Primitives.generateKeypair();
                        ePriv = kp[0];
                        ePub = kp[1];
                    }
                    buf.writeBytes(ePub);
                    ss.mixHash(ePub);
                    if (pskMode) {
                        ss.mixKey(ePub);
                    }
                    break;
                case "s":
                    if (sPub == null) {
                        throw new NoiseException("нет статического ключа");
                    }
                    buf.writeBytes(ss.encryptAndHash(sPub));
                    break;
                case "psk":
                    ss.mixKeyAndHash(psk);
                    break;
                default:
                    ss.mixKey(dhFor(tok));
            }
        }
        buf.writeBytes(ss.encryptAndHash(payload == null ? new byte[0] : payload));
        if (buf.size() > MAX_MESSAGE) {
            throw new NoiseException("сообщение рукопожатия слишком велико");
        }
        step++;
        return buf.toByteArray();
    }

    public byte[] readMessage(byte[] message) throws NoiseException {
        if (isComplete() || myTurn()) {
            throw new NoiseException("не наша очередь читать");
        }
        int pos = 0;
        for (String tok : pattern.messages[step]) {
            switch (tok) {
                case "e":
                    if (message.length - pos < Primitives.DHLEN) {
                        throw new NoiseException("короткое сообщение");
                    }
                    re = Arrays.copyOfRange(message, pos, pos + Primitives.DHLEN);
                    pos += Primitives.DHLEN;
                    ss.mixHash(re);
                    if (pskMode) {
                        ss.mixKey(re);
                    }
                    break;
                case "s": {
                    int n = Primitives.DHLEN + (ss.cipher().hasKey() ? 16 : 0);
                    if (message.length - pos < n) {
                        throw new NoiseException("короткое сообщение");
                    }
                    rs = ss.decryptAndHash(Arrays.copyOfRange(message, pos, pos + n));
                    pos += n;
                    break;
                }
                case "psk":
                    ss.mixKeyAndHash(psk);
                    break;
                default:
                    ss.mixKey(dhFor(tok));
            }
        }
        byte[] payload = ss.decryptAndHash(Arrays.copyOfRange(message, pos, message.length));
        step++;
        return payload;
    }

    /** [0] — отправка, [1] — приём для своей стороны. */
    public CipherState[] split() throws NoiseException {
        if (!isComplete()) {
            throw new NoiseException("рукопожатие не завершено");
        }
        CipherState[] c = ss.split();
        if (ePriv != null) {
            Arrays.fill(ePriv, (byte) 0);
        }
        return initiator ? new CipherState[]{c[0], c[1]} : new CipherState[]{c[1], c[0]};
    }
}
