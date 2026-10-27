package app.sakura.mobile.ui.common;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import app.sakura.mobile.R;

/** Строки списков (item_row): заголовок, подпись, правый текст, точка «в сети». */
public final class Rows {
    private Rows() {
    }

    public static View add(ViewGroup parent, String title, String sub, String end) {
        View v = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_row, parent, false);
        ((TextView) v.findViewById(R.id.row_title)).setText(title);
        TextView s = v.findViewById(R.id.row_sub);
        if (sub != null && !sub.isEmpty()) {
            s.setText(sub);
            s.setVisibility(View.VISIBLE);
        }
        ((TextView) v.findViewById(R.id.row_end)).setText(end == null ? "" : end);
        parent.addView(v);
        return v;
    }

    public static View addWithDot(ViewGroup parent, String title, String sub, String end, boolean online) {
        View v = add(parent, title, sub, end);
        View dot = v.findViewById(R.id.row_dot);
        dot.setVisibility(View.VISIBLE);
        dot.setBackgroundResource(online ? R.drawable.bg_dot_online : R.drawable.bg_dot_offline);
        return v;
    }

    /** Пустая строка-подсказка внутри секции. */
    public static void hint(ViewGroup parent, String text) {
        TextView t = new TextView(parent.getContext(), null, 0, R.style.Sakura_Dim);
        t.setText(text);
        t.setPadding(0, 8, 0, 8);
        parent.addView(t);
    }
}
