package app.sakura.mobile.snap;

import android.content.Context;
import android.util.TypedValue;

/** Общие помощники снимков. */
final class Snap {
    private Snap() {
    }

    static int attr(Context c, int attr) {
        TypedValue v = new TypedValue();
        c.getTheme().resolveAttribute(attr, v, true);
        return v.data;
    }

    static String themeTag(String theme) {
        return theme.endsWith("Sketch") ? "sketch" : "night";
    }
}
