package app.sakura.mobile.keys;

import java.security.GeneralSecurityException;

/** Шифрование секрета для хранения на диске (AES-GCM). Формат: 0x01 ‖ iv(12) ‖ шифртекст+тег. */
public interface KeyWrapper {
    byte[] wrap(byte[] plain) throws GeneralSecurityException;

    byte[] unwrap(byte[] blob) throws GeneralSecurityException;

    /** Удалить ключ обёртки (после «Забыть сервер»). */
    void destroy();
}
