package app.sakura.mobile.overlay;

/** Геометрия плавающего ядра (без Android): прилипание к ближнему краю, попадание в зону «×». */
public final class Snap {
    private Snap() {
    }

    /** x после отпускания: к левому или правому краю (с отступом margin). */
    public static int edgeX(int x, int size, int screenW, int margin) {
        int center = x + size / 2;
        return center < screenW / 2 ? margin : screenW - size - margin;
    }

    /** y в пределах экрана. */
    public static int clampY(int y, int size, int screenH, int margin) {
        return Math.max(margin, Math.min(screenH - size - margin, y));
    }

    /** Центр ядра над зоной «×» (круг радиуса r вокруг (cx, cy)). */
    public static boolean overClose(int x, int y, int size, int cx, int cy, int r) {
        int dx = x + size / 2 - cx;
        int dy = y + size / 2 - cy;
        return dx * dx + dy * dy <= r * r;
    }
}
