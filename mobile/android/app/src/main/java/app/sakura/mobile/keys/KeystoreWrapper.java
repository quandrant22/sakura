package app.sakura.mobile.keys;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.KeyStore;

import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;

/** Ключ обёртки `sakura_wrap` в Android Keystore (AES-256-GCM, не извлекаемый). */
public final class KeystoreWrapper extends AesGcmWrapper {
    public static final String ALIAS = "sakura_wrap";
    private static final String PROVIDER = "AndroidKeyStore";

    private KeyStore keyStore() throws GeneralSecurityException {
        KeyStore ks = KeyStore.getInstance(PROVIDER);
        try {
            ks.load(null);
        } catch (IOException e) {
            throw new GeneralSecurityException("Keystore недоступен");
        }
        return ks;
    }

    @Override
    protected SecretKey key(boolean create) throws GeneralSecurityException {
        KeyStore ks = keyStore();
        KeyStore.Entry e = ks.getEntry(ALIAS, null);
        if (e instanceof KeyStore.SecretKeyEntry) {
            return ((KeyStore.SecretKeyEntry) e).getSecretKey();
        }
        if (!create) {
            throw new GeneralSecurityException("нет ключа обёртки");
        }
        KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER);
        g.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build());
        return g.generateKey();
    }

    @Override
    public void destroy() {
        try {
            keyStore().deleteEntry(ALIAS);
        } catch (GeneralSecurityException ignored) {
            // ключа нет — нечего удалять
        }
    }
}
