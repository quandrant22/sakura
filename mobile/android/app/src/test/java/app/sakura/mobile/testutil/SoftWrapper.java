package app.sakura.mobile.testutil;

import java.security.GeneralSecurityException;
import java.security.SecureRandom;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;

import app.sakura.mobile.keys.AesGcmWrapper;

/** Формат KeystoreWrapper с программным ключом (в JVM нет AndroidKeyStore). */
public final class SoftWrapper extends AesGcmWrapper {
    public SecretKey key;

    @Override
    protected SecretKey key(boolean create) throws GeneralSecurityException {
        if (key == null) {
            if (!create) {
                throw new GeneralSecurityException("нет ключа");
            }
            byte[] k = new byte[32];
            new SecureRandom().nextBytes(k);
            key = new SecretKeySpec(k, "AES");
        }
        return key;
    }

    @Override
    public void destroy() {
        key = null;
    }
}
