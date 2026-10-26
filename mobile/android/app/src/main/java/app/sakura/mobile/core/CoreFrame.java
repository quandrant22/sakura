package app.sakura.mobile.core;

/**
 * Чистая функция кадра ядра — порт desktop/ui/src/core-gfx/coreFrame.ts один в один:
 * (время, состояние, уровень звука, подвижность) → круги относительно центра капли (viewBox).
 * Без Android-зависимостей и без аллокаций: результат пишется в переданный {@link Out}.
 */
public final class CoreFrame {

    public enum State { IDLE, LISTENING, THINKING, SPEAKING, OFFLINE }

    public enum Mobility {
        LOW(0.5), NORMAL(1), HIGH(1.3);

        public final double k;

        Mobility(double k) {
            this.k = k;
        }

        public static Mobility of(String name) {
            if ("low".equals(name)) {
                return LOW;
            }
            return "high".equals(name) ? HIGH : NORMAL;
        }
    }

    /** Пресеты слияния: размытие и матрица альфы (alpha·a + b), как feColorMatrix десктопа. */
    public enum MergePreset {
        SOFT(6, 22, -10), TIGHT(4, 18, -7), LIQUID(8, 26, -12);

        public final double blur;
        public final double alphaMul;
        public final double alphaAdd;

        MergePreset(double blur, double alphaMul, double alphaAdd) {
            this.blur = blur;
            this.alphaMul = alphaMul;
            this.alphaAdd = alphaAdd;
        }

        public static MergePreset of(String name) {
            if ("tight".equals(name)) {
                return TIGHT;
            }
            return "liquid".equals(name) ? LIQUID : SOFT;
        }
    }

    public static final double DROP_R = 45.5;
    /** Спутники (dx, dy, r) при полном раскрытии. */
    public static final double[][] SATELLITES = {
            {33.7, -61.1, 33.7},
            {-61.1, -37.6, 26.6},
            {-28.2, -87.6, 15.9},
            {55, 25, 12},
            {-48, 30, 9},
    };
    /** Фаза, скорость «бульканья» и направление орбиты каждого спутника. */
    static final double[][] WOBBLE = {
            {0, 1, 1}, {1.9, 1.27, -1}, {3.7, 0.83, 1}, {5.1, 1.51, -1}, {2.6, 1.13, 1},
    };
    /** Угловая скорость орбиты в состоянии «думает», рад/с. */
    static final double ORBIT_SPEED = 0.6;
    /** viewBox: центр капли в (0,0), квадрат 260. */
    public static final double VIEWBOX_X = -130;
    public static final double VIEWBOX_Y = -130;
    public static final double VIEWBOX_W = 260;
    public static final double VIEWBOX_H = 260;
    public static final double MAX_RING_R = 84;
    /** Центр и радиус градиента капли во viewBox. */
    public static final double GRADIENT_CX = -21.5;
    public static final double GRADIENT_CY = -17;
    public static final double GRADIENT_R = 71.4;
    public static final int SATS = 5;
    public static final int RINGS = 2;

    /** Кадр: капля, 5 спутников, до 2 колец, общая прозрачность. */
    public static final class Out {
        public double dropR;
        public final double[] satCx = new double[SATS];
        public final double[] satCy = new double[SATS];
        public final double[] satR = new double[SATS];
        public int ringCount;
        public final double[] ringR = new double[RINGS];
        public final double[] ringOpacity = new double[RINGS];
        public double opacity;

        /** Линейная смесь двух кадров (переход между состояниями). */
        public void mix(Out a, Out b, double k) {
            dropR = a.dropR + (b.dropR - a.dropR) * k;
            for (int i = 0; i < SATS; i++) {
                satCx[i] = a.satCx[i] + (b.satCx[i] - a.satCx[i]) * k;
                satCy[i] = a.satCy[i] + (b.satCy[i] - a.satCy[i]) * k;
                satR[i] = a.satR[i] + (b.satR[i] - a.satR[i]) * k;
            }
            ringCount = RINGS;
            for (int i = 0; i < RINGS; i++) {
                double ra = i < a.ringCount ? a.ringR[i] : DROP_R;
                double rb = i < b.ringCount ? b.ringR[i] : DROP_R;
                double oa = i < a.ringCount ? a.ringOpacity[i] : 0;
                double ob = i < b.ringCount ? b.ringOpacity[i] : 0;
                ringR[i] = ra + (rb - ra) * k;
                ringOpacity[i] = oa + (ob - oa) * k;
            }
            opacity = a.opacity + (b.opacity - a.opacity) * k;
        }

        public void copyFrom(Out o) {
            mix(o, o, 0);
            ringCount = o.ringCount;
        }
    }

    private CoreFrame() {
    }

    private static double clamp(double v, double lo, double hi) {
        return Math.min(hi, Math.max(lo, v));
    }

    private static double finite(double v) {
        return Double.isNaN(v) || Double.isInfinite(v) ? 0 : v;
    }

    /** Кадр в момент t (секунды). level — уровень звука 0..1. */
    public static void compute(double t, State state, double level, Mobility mobility, Out out) {
        t = finite(t);
        level = clamp(finite(level), 0, 1);
        double base;
        double amp;
        double omega;
        switch (state) {
            case LISTENING:
                base = 0.5;
                amp = 0.3;
                omega = 1.6;
                break;
            case THINKING:
                base = 0.7;
                amp = 0.25;
                omega = 1.4;
                break;
            case SPEAKING:
                base = 0.4 + 0.5 * level;
                amp = 0.08 + 0.25 * level;
                omega = 4;
                break;
            case OFFLINE:
                base = 0.3;
                amp = 0.02;
                omega = 0.3;
                break;
            case IDLE:
            default:
                base = 0.55;
                amp = 0.35;
                omega = 1.1;
        }
        // Нижняя граница раскрытия (base − amp) не меняется, амплитуда умножается на подвижность.
        double k = mobility.k;
        double mBase = base - amp * (1 - k);
        double mAmp = amp * k;
        double orbit = state == State.THINKING ? ORBIT_SPEED * t : 0;

        double breathe = state == State.OFFLINE ? 1 : 1 + 0.025 * Math.sin(t * 0.8);
        out.dropR = DROP_R * breathe;

        for (int i = 0; i < SATS; i++) {
            double dx = SATELLITES[i][0];
            double dy = SATELLITES[i][1];
            double r = SATELLITES[i][2];
            double phase = WOBBLE[i][0];
            double speed = WOBBLE[i][1];
            double dir = WOBBLE[i][2];
            double e = clamp(mBase + mAmp * Math.sin(t * omega * speed + phase), 0, 1);
            double a = orbit * dir;
            double cos = Math.cos(a);
            double sin = Math.sin(a);
            out.satCx[i] = (dx * cos - dy * sin) * e;
            out.satCy[i] = (dx * sin + dy * cos) * e;
            out.satR[i] = r * (0.6 + 0.4 * e);
        }

        out.ringCount = 0;
        if (state == State.LISTENING) {
            double reach = 12 + 26 * level;
            for (int j = 0; j < RINGS; j++) {
                double p = (((t * 0.7 + j / 2.0) % 1) + 1) % 1;
                out.ringR[j] = Math.min(MAX_RING_R, DROP_R + reach * p);
                out.ringOpacity[j] = (1 - p) * (0.35 + 0.5 * level);
            }
            out.ringCount = RINGS;
        } else {
            for (int j = 0; j < RINGS; j++) {
                out.ringR[j] = 0;
                out.ringOpacity[j] = 0;
            }
        }
        out.opacity = state == State.OFFLINE ? 0.45 : 1;
    }

    /** Частота кадров по состоянию: idle 30, активные 60, offline 10. */
    public static int fps(State state) {
        switch (state) {
            case OFFLINE:
                return 10;
            case IDLE:
                return 30;
            default:
                return 60;
        }
    }
}
