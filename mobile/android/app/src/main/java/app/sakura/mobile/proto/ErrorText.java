package app.sakura.mobile.proto;

/**
 * Тексты ошибок для пользователя — дословно из desktop/docs/SERVER_FEATURES.md.
 */
public final class ErrorText {
    public static final String UNSUPPORTED = "Сервер ещё не поддерживает";
    public static final String SECURE_REQUIRED =
            "Нужен защищённый канал: включи VPN или подключи устройство (Настройки → Безопасность)";
    public static final String TIMEOUT = "Сервер не отвечает";
    public static final String OFFLINE = "Нет связи с сервером";
    public static final String NOT_FOUND = "запись не найдена";

    public enum Kind { UNSUPPORTED, SECURE_REQUIRED, TIMEOUT, OFFLINE, OTHER }

    private ErrorText() {
    }

    public static Kind kind(ApiError e) {
        switch (e.code) {
            case ApiError.UNSUPPORTED:
            case "unknown_type":
            case "unknown_command":
                return Kind.UNSUPPORTED;
            case ApiError.SECURE_REQUIRED:
                return Kind.SECURE_REQUIRED;
            case ApiError.TIMEOUT:
                return Kind.TIMEOUT;
            case ApiError.OFFLINE:
            case "core_offline":
                return Kind.OFFLINE;
            default:
                return Kind.OTHER;
        }
    }

    /** Текст без названия раздела. */
    public static String text(ApiError e) {
        return text(e, null);
    }

    /** «Сервер ещё не поддерживает» на экране — с названием раздела (section, в родительном/описательном виде). */
    public static String text(ApiError e, String section) {
        switch (kind(e)) {
            case UNSUPPORTED:
                return section == null || section.isEmpty() ? UNSUPPORTED : UNSUPPORTED + " " + section;
            case SECURE_REQUIRED:
                return SECURE_REQUIRED;
            case TIMEOUT:
                return TIMEOUT;
            case OFFLINE:
                return OFFLINE;
            default:
                if (ApiError.NOT_FOUND.equals(e.code)) {
                    return e.message.isEmpty() ? NOT_FOUND : e.message;
                }
                return e.message.isEmpty() ? e.code : e.message;
        }
    }

    /** Можно ли повторить запрос кнопкой «Повторить» (имеет смысл). */
    public static boolean retryable(ApiError e) {
        Kind k = kind(e);
        return k == Kind.TIMEOUT || k == Kind.OFFLINE || k == Kind.OTHER;
    }
}
