package app.sakura.mobile.ui.common;

import android.content.Context;
import android.util.AttributeSet;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.TextView;

import app.sakura.mobile.R;
import app.sakura.mobile.proto.ErrorText;

/**
 * Обёртка содержимого экрана: скелетон при загрузке, пустое состояние, ошибка с «Повторить»,
 * офлайн («Нет связи с сервером»). Содержимое — первый дочерний элемент из разметки.
 */
public class StateView extends FrameLayout {
    private View content;
    private final View skeleton;
    private final View message;
    private final TextView messageText;
    private final View retry;
    private String emptyText = "Пока пусто";
    private String section;

    public StateView(Context context, AttributeSet attrs) {
        super(context, attrs);
        View overlay = LayoutInflater.from(context).inflate(R.layout.view_state, this, false);
        skeleton = overlay.findViewById(R.id.state_skeleton);
        message = overlay.findViewById(R.id.state_message);
        messageText = overlay.findViewById(R.id.state_text);
        retry = overlay.findViewById(R.id.state_retry);
        addView(overlay);
    }

    @Override
    protected void onFinishInflate() {
        super.onFinishInflate();
        // overlay добавлен в конструкторе первым; содержимое из XML идёт следом
        if (getChildCount() > 1) {
            content = getChildAt(1);
        }
    }

    public void setEmptyText(String text) {
        emptyText = text;
    }

    /** Название раздела для «Сервер ещё не поддерживает …». */
    public void setSection(String s) {
        section = s;
    }

    public void show(Loadable<?> l, Runnable onRetry) {
        boolean ready = l.status == Loadable.Status.READY;
        if (content != null) {
            content.setVisibility(ready ? VISIBLE : GONE);
        }
        skeleton.setVisibility(l.status == Loadable.Status.LOADING ? VISIBLE : GONE);
        boolean msg = !ready && l.status != Loadable.Status.LOADING;
        message.setVisibility(msg ? VISIBLE : GONE);
        switch (l.status) {
            case EMPTY:
                messageText.setText(emptyText);
                retry.setVisibility(GONE);
                break;
            case OFFLINE:
                messageText.setText(ErrorText.OFFLINE);
                retry.setVisibility(onRetry != null ? VISIBLE : GONE);
                break;
            case ERROR:
                messageText.setText(l.errorText(section));
                retry.setVisibility(onRetry != null && l.retryable() ? VISIBLE : GONE);
                break;
            default:
                retry.setVisibility(GONE);
        }
        retry.setOnClickListener(onRetry == null ? null : v -> onRetry.run());
    }
}
