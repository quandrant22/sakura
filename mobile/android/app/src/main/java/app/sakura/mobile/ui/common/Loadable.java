package app.sakura.mobile.ui.common;

import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;

/** Состояние данных экрана: загрузка (скелетон), готово, пусто, ошибка (с «Повторить»), офлайн. */
public final class Loadable<T> {
    public enum Status { LOADING, READY, EMPTY, ERROR, OFFLINE }

    public final Status status;
    public final T data;
    public final ApiError error;

    private Loadable(Status status, T data, ApiError error) {
        this.status = status;
        this.data = data;
        this.error = error;
    }

    public static <T> Loadable<T> loading() {
        return new Loadable<>(Status.LOADING, null, null);
    }

    public static <T> Loadable<T> ready(T data) {
        return new Loadable<>(Status.READY, data, null);
    }

    public static <T> Loadable<T> empty() {
        return new Loadable<>(Status.EMPTY, null, null);
    }

    /** Ошибка запроса: offline отдельно (экран «Нет связи»), остальное — текст и «Повторить». */
    public static <T> Loadable<T> failed(ApiError e) {
        return new Loadable<>(ErrorText.kind(e) == ErrorText.Kind.OFFLINE ? Status.OFFLINE : Status.ERROR, null, e);
    }

    public static <T> Loadable<T> offline() {
        return new Loadable<>(Status.OFFLINE, null, new ApiError(ApiError.OFFLINE, ""));
    }

    /** Текст ошибки для экрана; section — название раздела для «Сервер ещё не поддерживает …». */
    public String errorText(String section) {
        return error == null ? ErrorText.OFFLINE : ErrorText.text(error, section);
    }

    public boolean retryable() {
        return error == null || ErrorText.retryable(error);
    }
}
