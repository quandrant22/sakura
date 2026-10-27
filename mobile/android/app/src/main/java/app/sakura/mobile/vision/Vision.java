package app.sakura.mobile.vision;

import android.graphics.Bitmap;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.util.function.Consumer;

import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;

/**
 * vision_request с source:"camera": JPEG (длинная сторона ≤ 1280, качество 70) в base64, в памяти —
 * на диск кадр не пишется. Лимит — как у кадра окна на сервере (2 000 000 символов base64).
 */
public final class Vision {
    public static final int MAX_SIDE = 1280;
    public static final int QUALITY = 70;
    public static final int MAX_B64 = 2_000_000;
    public static final long VISION_TIMEOUT_MS = 45_000;

    private Vision() {
    }

    /** Размер после уменьшения: длинная сторона ≤ MAX_SIDE, пропорции сохраняются. */
    public static int[] fit(int w, int h) {
        int side = Math.max(w, h);
        if (side <= MAX_SIDE || side <= 0) {
            return new int[]{Math.max(1, w), Math.max(1, h)};
        }
        double k = (double) MAX_SIDE / side;
        return new int[]{Math.max(1, (int) Math.round(w * k)), Math.max(1, (int) Math.round(h * k))};
    }

    /** JPEG в base64; если не влезает в лимит — понижаем качество. null — кадр слишком большой. */
    public static String encode(Bitmap src) {
        int[] s = fit(src.getWidth(), src.getHeight());
        Bitmap b = s[0] == src.getWidth() && s[1] == src.getHeight() ? src
                : Bitmap.createScaledBitmap(src, s[0], s[1], true);
        try {
            for (int q = QUALITY; q >= 30; q -= 15) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                b.compress(Bitmap.CompressFormat.JPEG, q, out);
                String b64 = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP);
                if (b64.length() <= MAX_B64) {
                    return b64;
                }
            }
            return null;
        } finally {
            if (b != src) {
                b.recycle();
            }
        }
    }

    /** Отправить кадр; ответ (reply с тем же request_id) или текст ошибки — в done. */
    public static void ask(String b64, String question, Consumer<String> done) {
        if (b64 == null) {
            done.accept("Кадр слишком большой");
            return;
        }
        JSONObject m = Json.obj("type", "vision_request", "source", "camera", "image", b64);
        if (question != null && !question.isEmpty()) {
            Json.put(m, "question", question);
        }
        SakuraApp.get().voice().markThinking();
        SakuraApp.get().client().request(m, VISION_TIMEOUT_MS, new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject result) {
                done.accept(result.optString("text", ""));
            }

            @Override
            public void onError(ApiError error) {
                done.accept(ErrorText.text(error, "распознавание кадров"));
            }
        });
    }
}
