package app.sakura.mobile.crypto.noise;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** SymmetricState Noise: ck, h и текущий CipherState. */
public final class SymmetricState {
    private byte[] ck;
    private byte[] h;
    private CipherState cipher = new CipherState();

    public SymmetricState(String protocolName) {
        byte[] name = protocolName.getBytes(StandardCharsets.US_ASCII);
        h = name.length <= Primitives.HASHLEN ? Arrays.copyOf(name, Primitives.HASHLEN) : Primitives.hash(name);
        ck = h.clone();
    }

    public byte[] handshakeHash() {
        return h.clone();
    }

    CipherState cipher() {
        return cipher;
    }

    public void mixKey(byte[] ikm) {
        byte[][] o = Primitives.hkdf(ck, ikm, 2);
        ck = o[0];
        cipher = new CipherState(o[1]);
    }

    public void mixHash(byte[] data) {
        h = Primitives.hash(h, data);
    }

    public void mixKeyAndHash(byte[] ikm) {
        byte[][] o = Primitives.hkdf(ck, ikm, 3);
        ck = o[0];
        mixHash(o[1]);
        cipher = new CipherState(o[2]);
    }

    public byte[] encryptAndHash(byte[] plaintext) throws NoiseException {
        byte[] c = cipher.encryptWithAd(h, plaintext);
        mixHash(c);
        return c;
    }

    public byte[] decryptAndHash(byte[] ciphertext) throws NoiseException {
        byte[] p = cipher.decryptWithAd(h, ciphertext);
        mixHash(ciphertext);
        return p;
    }

    /** Два CipherState: [0] — инициатор→ответчик, [1] — обратно. */
    public CipherState[] split() {
        byte[][] o = Primitives.hkdf(ck, new byte[0], 2);
        CipherState[] out = {new CipherState(o[0]), new CipherState(o[1])};
        Arrays.fill(ck, (byte) 0);
        return out;
    }
}
