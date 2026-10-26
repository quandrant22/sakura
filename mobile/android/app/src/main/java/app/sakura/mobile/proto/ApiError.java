package app.sakura.mobile.proto;

/**
 * Ошибка запроса: код сервера (`error.code`) или клиентский (`timeout`, `offline`, `unsupported`).
 * Текст для экрана — {@link ErrorText}.
 */
public final class ApiError {
    public static final String UNSUPPORTED = "unsupported";
    public static final String SECURE_REQUIRED = "secure_channel_required";
    public static final String NOT_MASTER = "not_master";
    public static final String TIMEOUT = "timeout";
    public static final String OFFLINE = "offline";
    public static final String BAD_REQUEST = "bad_request";
    public static final String NOT_FOUND = "not_found";

    public final String code;
    public final String message;

    public ApiError(String code, String message) {
        this.code = code == null ? "error" : code;
        this.message = message == null ? "" : message;
    }

    @Override
    public String toString() {
        return code;
    }
}
