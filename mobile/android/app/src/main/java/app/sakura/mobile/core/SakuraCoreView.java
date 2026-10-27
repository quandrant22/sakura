package app.sakura.mobile.core;

import android.content.Context;
import android.content.res.TypedArray;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RuntimeShader;
import android.util.AttributeSet;
import android.util.TypedValue;
import android.view.Choreographer;
import android.view.View;

import app.sakura.mobile.R;

/**
 * Ядро Сакуры. На аппаратном холсте — AGSL {@link CoreShading#AGSL}; на программном (снимки, превью)
 * — растр той же формулой. Кадры через Choreographer: idle 30, активные 60, offline 10 fps;
 * переход между состояниями — интерполяция 250 мс; «Убрать анимации» — один статичный кадр.
 * В onDraw нет аллокаций.
 */
public class SakuraCoreView extends View implements Choreographer.FrameCallback {
    public static final long TRANSITION_MS = 250;
    private static final int SOFT_RASTER = 160;

    private CoreFrame.State state = CoreFrame.State.IDLE;
    private CoreFrame.Mobility mobility = CoreFrame.Mobility.NORMAL;
    private CoreFrame.MergePreset preset = CoreFrame.MergePreset.SOFT;
    private boolean reduceMotion;
    private boolean staticFrame;
    private volatile float level;
    private float shownLevel;

    private final CoreFrame.Out target = new CoreFrame.Out();
    private final CoreFrame.Out from = new CoreFrame.Out();
    private final CoreFrame.Out drawn = new CoreFrame.Out();
    private final float[] circles = new float[CoreShading.CIRCLES * 3];
    private final Paint shaderPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint ringPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint bitmapPaint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Rect dst = new Rect();
    private RuntimeShader shader;
    private Bitmap softBitmap;
    private int[] softPixels;

    private final int accent;
    private final int deep;
    private final int soft;

    private long startNanos = -1;
    private long lastFrameNanos;
    private long transitionStart = -1;
    private boolean running;
    private long drawNanosAvg;

    public SakuraCoreView(Context context) {
        this(context, null);
    }

    public SakuraCoreView(Context context, AttributeSet attrs) {
        super(context, attrs);
        accent = themeColor(context, R.attr.sakuraAccent);
        deep = themeColor(context, R.attr.sakuraAccentDeep);
        soft = themeColor(context, R.attr.sakuraAccentSoft);
        if (attrs != null) {
            TypedArray a = context.obtainStyledAttributes(attrs, R.styleable.SakuraCoreView);
            staticFrame = a.getBoolean(R.styleable.SakuraCoreView_coreStatic, false);
            a.recycle();
        }
        ringPaint.setStyle(Paint.Style.STROKE);
        ringPaint.setStrokeWidth(getResources().getDimension(R.dimen.ring_stroke));
        ringPaint.setColor(accent);
        try {
            shader = new RuntimeShader(CoreShading.AGSL);
            shader.setColorUniform("uA", accent);
            shader.setColorUniform("uB", deep);
            shader.setColorUniform("uSoft", soft);
            shaderPaint.setShader(shader);
        } catch (RuntimeException e) {
            shader = null;   // среда без AGSL (превью) — программный растр
        }
        CoreFrame.compute(0, state, 0, mobility, target);
        drawn.copyFrom(target);
        setContentDescription("Ядро Сакуры");
    }

    private static int themeColor(Context c, int attr) {
        TypedValue v = new TypedValue();
        if (c.getTheme().resolveAttribute(attr, v, true)) {
            return v.data;
        }
        return 0xFFFF6AE3;
    }

    // ── параметры ──

    public void setState(CoreFrame.State s) {
        if (s == state) {
            return;
        }
        from.copyFrom(drawn);
        state = s;
        transitionStart = System.nanoTime();
        restart();
        setContentDescription("Ядро: " + s.name().toLowerCase(java.util.Locale.ROOT));
    }

    public CoreFrame.State state() {
        return state;
    }

    /** Уровень звука 0..1 (onRmsChanged или RMS чанков озвучки); читается каждый кадр. */
    public void setLevel(float l) {
        level = Float.isNaN(l) ? 0 : Math.max(0, Math.min(1, l));
    }

    public void setMobility(CoreFrame.Mobility m) {
        mobility = m;
        restart();
    }

    public void setPreset(CoreFrame.MergePreset p) {
        preset = p;
        invalidate();
    }

    public void setReduceMotion(boolean on) {
        reduceMotion = on;
        restart();
    }

    public void setStaticFrame(boolean on) {
        staticFrame = on;
        restart();
    }

    private static volatile long lastAvg;

    /** Среднее время onDraw, нс (диагностика: бюджет 4 мс). */
    public long drawNanosAverage() {
        return drawNanosAvg;
    }

    /** Последнее среднее любого ядра на экране — для «Диагностики». */
    public static long lastDrawNanos() {
        return lastAvg;
    }

    // ── цикл кадров ──

    private boolean animated() {
        return !reduceMotion && !staticFrame && isAttachedToWindow() && getVisibility() == VISIBLE
                && getWindowVisibility() == VISIBLE;
    }

    private void restart() {
        stopLoop();
        if (animated()) {
            running = true;
            Choreographer.getInstance().postFrameCallback(this);
        } else {
            CoreFrame.compute(0, state, 0, mobility, target);
            drawn.copyFrom(target);
            transitionStart = -1;
            invalidate();
        }
    }

    private void stopLoop() {
        if (running) {
            Choreographer.getInstance().removeFrameCallback(this);
            running = false;
        }
    }

    @Override
    public void doFrame(long frameTimeNanos) {
        if (!running) {
            return;
        }
        Choreographer.getInstance().postFrameCallback(this);
        long interval = 1_000_000_000L / CoreFrame.fps(state);
        // допуск 2 мс, чтобы 60 fps не проседали до 30 из-за дрожания vsync
        if (frameTimeNanos - lastFrameNanos < interval - 2_000_000L) {
            return;
        }
        lastFrameNanos = frameTimeNanos;
        if (startNanos < 0) {
            startNanos = frameTimeNanos;
        }
        shownLevel += (level - shownLevel) * 0.35f;
        double t = (frameTimeNanos - startNanos) / 1e9;
        CoreFrame.compute(t, state, shownLevel, mobility, target);
        if (transitionStart > 0) {
            double k = (System.nanoTime() - transitionStart) / (TRANSITION_MS * 1e6);
            if (k >= 1) {
                transitionStart = -1;
                drawn.copyFrom(target);
            } else {
                double e = k * k * (3 - 2 * k);
                drawn.mix(from, target, e);
            }
        } else {
            drawn.copyFrom(target);
        }
        invalidate();
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        restart();
    }

    @Override
    protected void onDetachedFromWindow() {
        stopLoop();
        super.onDetachedFromWindow();
    }

    @Override
    public void onVisibilityAggregated(boolean isVisible) {
        super.onVisibilityAggregated(isVisible);
        if (isVisible) {
            restart();
        } else {
            stopLoop();
        }
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        super.onSizeChanged(w, h, oldw, oldh);
        int s = Math.max(1, Math.min(SOFT_RASTER, Math.min(w, h)));
        if (softBitmap == null || softBitmap.getWidth() != s) {
            softBitmap = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888);
            softPixels = new int[s * s];
        }
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int def = getResources().getDimensionPixelSize(R.dimen.core_size);
        int w = resolveSize(def, widthMeasureSpec);
        int h = resolveSize(def, heightMeasureSpec);
        int s = Math.min(w, h);
        setMeasuredDimension(s, s);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        long t0 = System.nanoTime();
        float size = Math.min(getWidth(), getHeight());
        float scale = (float) (size / CoreFrame.VIEWBOX_W);
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        for (int i = 0; i < drawn.ringCount; i++) {
            ringPaint.setAlpha((int) (255 * Math.max(0, Math.min(1, drawn.ringOpacity[i]))));
            canvas.drawCircle(cx, cy, (float) drawn.ringR[i] * scale, ringPaint);
        }
        if (shader != null && canvas.isHardwareAccelerated()) {
            CoreShading.pack(drawn, circles);
            shader.setFloatUniform("uC", circles);
            shader.setFloatUniform("uSigma", (float) preset.blur);
            shader.setFloatUniform("uMat", (float) preset.alphaMul, (float) preset.alphaAdd);
            shader.setFloatUniform("uGc", (float) CoreFrame.GRADIENT_CX, (float) CoreFrame.GRADIENT_CY);
            shader.setFloatUniform("uGr", (float) CoreFrame.GRADIENT_R);
            shader.setFloatUniform("uScale", scale);
            shader.setFloatUniform("uOrigin", cx, cy);
            shader.setFloatUniform("uOpacity", (float) drawn.opacity);
            canvas.drawRect(0, 0, getWidth(), getHeight(), shaderPaint);
        } else if (softBitmap != null) {
            int s = softBitmap.getWidth();
            CoreShading.raster(drawn, preset, accent, deep, soft, s, circles, softPixels);
            softBitmap.setPixels(softPixels, 0, s, 0, 0, s, s);
            int left = (int) (cx - size / 2);
            int top = (int) (cy - size / 2);
            dst.set(left, top, left + (int) size, top + (int) size);
            canvas.drawBitmap(softBitmap, null, dst, bitmapPaint);
        }
        long dt = System.nanoTime() - t0;
        drawNanosAvg = drawNanosAvg == 0 ? dt : (drawNanosAvg * 15 + dt) / 16;
        lastAvg = drawNanosAvg;
    }

    /** Статичный кадр в битмап (виджет, плитка). Аллоцирует — не для onDraw. */
    public static Bitmap renderStatic(Context context, CoreFrame.State state, int sizePx) {
        CoreFrame.Out f = new CoreFrame.Out();
        CoreFrame.compute(0, state, 0, CoreFrame.Mobility.NORMAL, f);
        int[] px = new int[sizePx * sizePx];
        // акцентные токены одинаковы в обеих темах — берём из ресурсов (контекст виджета без темы)
        CoreShading.raster(f, CoreFrame.MergePreset.SOFT, context.getColor(R.color.accent),
                context.getColor(R.color.accent_deep), context.getColor(R.color.accent_soft),
                sizePx, new float[CoreShading.CIRCLES * 3], px);
        return Bitmap.createBitmap(px, sizePx, sizePx, Bitmap.Config.ARGB_8888);
    }
}
