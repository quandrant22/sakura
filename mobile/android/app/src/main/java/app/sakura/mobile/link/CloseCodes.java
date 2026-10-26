package app.sakura.mobile.link;

/** Коды закрытия WebSocket (PROTOCOL.md §4.5). */
public final class CloseCodes {
    public static final int NORMAL = 1000;
    public static final int PROTOCOL_ERROR = 4400;
    public static final int UNAUTHORIZED = 4401;
    public static final int HANDSHAKE_FAILED = 4408;
    public static final int INTEGRITY = 4409;
    public static final int SECURE_REQUIRED = 4412;
    public static final int TOO_LARGE = 4413;
    public static final int RATE_LIMITED = 4429;

    private CloseCodes() {
    }

    /** Есть ли смысл переподключаться сразу (по расписанию backoff). */
    public static boolean retryable(int code) {
        return code != UNAUTHORIZED && code != SECURE_REQUIRED;
    }

    /** Понятный текст для экрана состояния (без подробностей о ключах). */
    public static String describe(int code) {
        switch (code) {
            case NORMAL:
                return "соединение закрыто";
            case PROTOCOL_ERROR:
                return "ошибка протокола (сервер без защищённого канала?)";
            case UNAUTHORIZED:
                return "сервер не принял устройство";
            case HANDSHAKE_FAILED:
                return "сервер не узнал устройство — спарьте заново (/pair)";
            case INTEGRITY:
                return "нарушена целостность канала";
            case SECURE_REQUIRED:
                return "сервер требует защищённый канал";
            case TOO_LARGE:
                return "слишком большое сообщение";
            case RATE_LIMITED:
                return "слишком много попыток, подождите";
            default:
                return "связь прервана (" + code + ")";
        }
    }
}
