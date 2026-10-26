package app.sakura.mobile.keys;

import java.security.GeneralSecurityException;
import java.util.Arrays;

import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** AES-256-GCM обёртка над заданным ключом; IV генерирует провайдер (Keystore запрещает свой IV). */
public abstract class AesGcmWrapper implements KeyWrapper {
    static final byte FORMAT = 0x01;
    static final int IV = 12;
    static final int TAG_BITS = 128;

    protected abstract SecretKey key(boolean create) throws GeneralSecurityException;

    @Override
    public byte[] wrap(byte[] plain) throws GeneralSecurityException {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key(true));
        byte[] iv = c.getIV();
        if (iv == null || iv.length != IV) {
            throw new GeneralSecurityException("неожиданный IV");
        }
        c.updateAAD(new byte[]{FORMAT});
        byte[] ct = c.doFinal(plain);
        byte[] out = new byte[1 + IV + ct.length];
        out[0] = FORMAT;
        System.arraycopy(iv, 0, out, 1, IV);
        System.arraycopy(ct, 0, out, 1 + IV, ct.length);
        return out;
    }

    @Override
    public byte[] unwrap(byte[] blob) throws GeneralSecurityException {
        if (blob == null || blob.length < 1 + IV + 16 || blob[0] != FORMAT) {
            throw new GeneralSecurityException("неизвестный формат ключа");
        }
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(TAG_BITS, Arrays.copyOfRange(blob, 1, 1 + IV)));
        c.updateAAD(new byte[]{FORMAT});
        return c.doFinal(blob, 1 + IV, blob.length - 1 - IV);
    }
}
