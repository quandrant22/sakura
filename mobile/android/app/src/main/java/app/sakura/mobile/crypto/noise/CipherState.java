package app.sakura.mobile.crypto.noise;

import org.bouncycastle.crypto.InvalidCipherTextException;
import org.bouncycastle.crypto.modes.ChaCha20Poly1305;
import org.bouncycastle.crypto.params.AEADParameters;
import org.bouncycastle.crypto.params.KeyParameter;

import java.util.Arrays;

/** CipherState Noise: ключ k и 64-битный счётчик n (nonce = 4 нулевых байта ‖ n little-endian). */
public final class CipherState {
    /** 2^64−1 — зарезервированное значение, используется только в REKEY. */
    static final long MAX_NONCE = -1L;
    private static final int TAG = 16;

    private byte[] k;
    private long n;
    private final ChaCha20Poly1305 aead = new ChaCha20Poly1305();

    public CipherState() {
    }

    public CipherState(byte[] key) {
        this.k = key == null ? null : Arrays.copyOf(key, 32);
    }

    public boolean hasKey() {
        return k != null;
    }

    public long nonce() {
        return n;
    }

    /** Только для тестов nonce-переполнения. */
    void setNonce(long value) {
        n = value;
    }

    private static byte[] nonceBytes(long n) {
        byte[] out = new byte[12];
        for (int i = 0; i < 8; i++) {
            out[4 + i] = (byte) (n >>> (8 * i));
        }
        return out;
    }

    private byte[] run(boolean encrypt, long nonce, byte[] ad, byte[] in) throws NoiseException {
        aead.init(encrypt, new AEADParameters(new KeyParameter(k), TAG * 8, nonceBytes(nonce), ad));
        byte[] out = new byte[aead.getOutputSize(in.length)];
        int len = aead.processBytes(in, 0, in.length, out, 0);
        try {
            len += aead.doFinal(out, len);
        } catch (InvalidCipherTextException e) {
            throw new NoiseException("ошибка целостности");
        }
        return len == out.length ? out : Arrays.copyOf(out, len);
    }

    public byte[] encryptWithAd(byte[] ad, byte[] plaintext) throws NoiseException {
        if (k == null) {
            return plaintext;
        }
        if (n == MAX_NONCE) {
            throw new NoiseException("исчерпан счётчик nonce");
        }
        byte[] out = run(true, n, ad, plaintext);
        n++;
        return out;
    }

    public byte[] decryptWithAd(byte[] ad, byte[] ciphertext) throws NoiseException {
        if (k == null) {
            return ciphertext;
        }
        if (n == MAX_NONCE) {
            throw new NoiseException("исчерпан счётчик nonce");
        }
        if (ciphertext.length < TAG) {
            throw new NoiseException("ошибка целостности");
        }
        byte[] out = run(false, n, ad, ciphertext);
        n++;
        return out;
    }

    /** REKEY(): k = ENCRYPT(k, 2^64−1, ε, 0^32)[:32]; n не сбрасывается. */
    public void rekey() throws NoiseException {
        byte[] next = run(true, MAX_NONCE, new byte[0], new byte[32]);
        Arrays.fill(k, (byte) 0);
        k = Arrays.copyOf(next, 32);
    }

    /** Затирает ключ (конец сеанса). */
    public void destroy() {
        if (k != null) {
            Arrays.fill(k, (byte) 0);
            k = null;
        }
    }
}
