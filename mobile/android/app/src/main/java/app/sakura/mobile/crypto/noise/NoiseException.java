package app.sakura.mobile.crypto.noise;

/** Ошибка рукопожатия или расшифровки. Текст никогда не содержит ключей и данных. */
public class NoiseException extends Exception {
    public NoiseException(String message) {
        super(message);
    }
}
