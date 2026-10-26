package app.sakura.mobile.core;

/**
 * Математика заливки ядра — общая для AGSL-шейдера ({@link #AGSL}) и программного растра
 * ({@link #pixel}): метаболы «слипшегося» размытия как feGaussianBlur + feColorMatrix десктопа.
 * Размытый диск аппроксимируется логистой (σ пресета), объединение — 1 − Π(1 − aᵢ),
 * альфа = clamp(A·mul + add). Цвет — радиальный градиент accent → accent_deep без размытия.
 * Снаружи — свечение accent_soft по полю A. Координаты — во viewBox (центр капли (0,0)).
 */
public final class CoreShading {
    public static final int CIRCLES = 1 + CoreFrame.SATS;

    public static final String AGSL =
            "uniform float3 uC[6];\n"
            + "uniform float uSigma;\n"
            + "uniform float2 uMat;\n"
            + "uniform float2 uGc;\n"
            + "uniform float uGr;\n"
            + "uniform float uScale;\n"
            + "uniform float2 uOrigin;\n"
            + "uniform half4 uA;\n"
            + "uniform half4 uB;\n"
            + "uniform half4 uSoft;\n"
            + "uniform float uOpacity;\n"
            + "half4 main(float2 frag) {\n"
            + "  float2 p = (frag - uOrigin) / uScale;\n"
            + "  float q = 1.0;\n"
            + "  for (int i = 0; i < 6; i++) {\n"
            + "    float d = length(p - uC[i].xy) - uC[i].z;\n"
            + "    float a = 1.0 / (1.0 + exp(clamp(1.702 * d / uSigma, -30.0, 30.0)));\n"
            + "    q *= (1.0 - a);\n"
            + "  }\n"
            + "  float A = 1.0 - q;\n"
            + "  float alpha = clamp(A * uMat.x + uMat.y, 0.0, 1.0);\n"
            + "  float t = clamp(length(p - uGc) / uGr, 0.0, 1.0);\n"
            + "  half3 col = mix(uA.rgb, uB.rgb, t);\n"
            + "  float glow = uSoft.a * clamp(A * 2.0, 0.0, 1.0) * (1.0 - alpha);\n"
            + "  half3 rgb = col * alpha + uSoft.rgb * glow;\n"
            + "  float outA = alpha + glow;\n"
            + "  return half4(rgb * uOpacity, outA * uOpacity);\n"
            + "}\n";

    private CoreShading() {
    }

    /** Упаковка кадра в uC: [x, y, r] капли и 5 спутников. */
    public static void pack(CoreFrame.Out f, float[] out) {
        out[0] = 0;
        out[1] = 0;
        out[2] = (float) f.dropR;
        for (int i = 0; i < CoreFrame.SATS; i++) {
            out[3 + 3 * i] = (float) f.satCx[i];
            out[4 + 3 * i] = (float) f.satCy[i];
            out[5 + 3 * i] = (float) f.satR[i];
        }
    }

    /**
     * Один пиксель (координаты во viewBox) → ARGB (не premultiplied). Та же формула, что в AGSL.
     * accent/deep/soft — ARGB-цвета.
     */
    public static int pixel(float px, float py, float[] circles, CoreFrame.MergePreset preset,
                            int accent, int deep, int soft, double opacity) {
        double q = 1;
        for (int i = 0; i < CIRCLES; i++) {
            double dx = px - circles[3 * i];
            double dy = py - circles[3 * i + 1];
            double d = Math.sqrt(dx * dx + dy * dy) - circles[3 * i + 2];
            double z = Math.max(-30, Math.min(30, 1.702 * d / preset.blur));
            q *= 1 - 1 / (1 + Math.exp(z));
        }
        double a = 1 - q;
        double alpha = Math.max(0, Math.min(1, a * preset.alphaMul + preset.alphaAdd));
        double gx = px - CoreFrame.GRADIENT_CX;
        double gy = py - CoreFrame.GRADIENT_CY;
        double t = Math.max(0, Math.min(1, Math.sqrt(gx * gx + gy * gy) / CoreFrame.GRADIENT_R));
        double softA = ((soft >>> 24) & 0xFF) / 255.0;
        double glow = softA * Math.max(0, Math.min(1, a * 2)) * (1 - alpha);
        double outA = (alpha + glow) * opacity;
        if (outA <= 0.001) {
            return 0;
        }
        double r = (lerp(ch(accent, 16), ch(deep, 16), t) * alpha + ch(soft, 16) * glow) * opacity / outA;
        double g = (lerp(ch(accent, 8), ch(deep, 8), t) * alpha + ch(soft, 8) * glow) * opacity / outA;
        double b = (lerp(ch(accent, 0), ch(deep, 0), t) * alpha + ch(soft, 0) * glow) * opacity / outA;
        return (to8(outA) << 24) | (to8(r) << 16) | (to8(g) << 8) | to8(b);
    }

    private static double ch(int argb, int shift) {
        return ((argb >>> shift) & 0xFF) / 255.0;
    }

    private static double lerp(double a, double b, double t) {
        return a + (b - a) * t;
    }

    private static int to8(double v) {
        return (int) Math.round(Math.max(0, Math.min(1, v)) * 255);
    }

    /**
     * Растр кадра size×size (viewBox целиком) в pixels (ARGB). Без аллокаций: буферы передаёт вызывающий.
     */
    public static void raster(CoreFrame.Out f, CoreFrame.MergePreset preset, int accent, int deep, int soft,
                              int size, float[] circles, int[] pixels) {
        pack(f, circles);
        double scale = CoreFrame.VIEWBOX_W / size;
        for (int y = 0; y < size; y++) {
            float vy = (float) (CoreFrame.VIEWBOX_Y + (y + 0.5) * scale);
            for (int x = 0; x < size; x++) {
                float vx = (float) (CoreFrame.VIEWBOX_X + (x + 0.5) * scale);
                pixels[y * size + x] = pixel(vx, vy, circles, preset, accent, deep, soft, f.opacity);
            }
        }
    }
}
