package app.sakura.mobile.crypto.noise;

import org.bouncycastle.crypto.digests.Blake2sDigest;
import org.bouncycastle.crypto.macs.HMac;
import org.bouncycastle.crypto.params.KeyParameter;
import org.bouncycastle.math.ec.rfc7748.X25519;

import java.security.SecureRandom;

/**
 * Примитивы набора 25519_ChaChaPoly_BLAKE2s. Только BouncyCastle: X25519 (RFC 7748),
 * BLAKE2s, HMAC-BLAKE2s, HKDF по Noise rev 34 §4.3.
 */
public final class Primitives {
    public static final int DHLEN = 32;
    public static final int HASHLEN = 32;

    private static final SecureRandom RANDOM = new SecureRandom();

    private Primitives() {
    }

    /** Новая пара: [0] — закрытый, [1] — открытый ключ. */
    public static byte[][] generateKeypair() {
        byte[] priv = new byte[X25519.SCALAR_SIZE];
        X25519.generatePrivateKey(RANDOM, priv);
        return new byte[][]{priv, publicFromPrivate(priv)};
    }

    public static byte[] publicFromPrivate(byte[] priv) {
        byte[] pub = new byte[X25519.POINT_SIZE];
        X25519.generatePublicKey(priv, 0, pub, 0);
        return pub;
    }

    public static byte[] dh(byte[] priv, byte[] pub) throws NoiseException {
        if (priv == null || pub == null || pub.length != DHLEN) {
            throw new NoiseException("недопустимый открытый ключ");
        }
        byte[] out = new byte[X25519.POINT_SIZE];
        // false — нулевой общий секрет (точка малой подгруппы)
        if (!X25519.calculateAgreement(priv, 0, pub, 0, out, 0)) {
            throw new NoiseException("недопустимый открытый ключ");
        }
        return out;
    }

    public static byte[] hash(byte[]... parts) {
        Blake2sDigest d = new Blake2sDigest(256);
        for (byte[] p : parts) {
            d.update(p, 0, p.length);
        }
        byte[] out = new byte[HASHLEN];
        d.doFinal(out, 0);
        return out;
    }

    /** BLAKE2s с произвольной длиной выхода (отпечаток, PSK). */
    public static byte[] blake2s(int digestBytes, byte[]... parts) {
        Blake2sDigest d = new Blake2sDigest(digestBytes * 8);
        for (byte[] p : parts) {
            d.update(p, 0, p.length);
        }
        byte[] out = new byte[digestBytes];
        d.doFinal(out, 0);
        return out;
    }

    public static byte[] hmac(byte[] key, byte[]... parts) {
        HMac mac = new HMac(new Blake2sDigest(256));
        mac.init(new KeyParameter(key));
        for (byte[] p : parts) {
            mac.update(p, 0, p.length);
        }
        byte[] out = new byte[HASHLEN];
        mac.doFinal(out, 0);
        return out;
    }

    /** HKDF(ck, ikm) → n выходов по 32 байта (n = 2 или 3). */
    public static byte[][] hkdf(byte[] ck, byte[] ikm, int n) {
        byte[] temp = hmac(ck, ikm);
        byte[][] out = new byte[n][];
        byte[] prev = new byte[0];
        for (int i = 1; i <= n; i++) {
            prev = hmac(temp, prev, new byte[]{(byte) i});
            out[i - 1] = prev;
        }
        return out;
    }
}
