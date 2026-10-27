package app.sakura.mobile.share;

import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.ImageDecoder;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONObject;

import java.io.IOException;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.vision.Vision;

/**
 * Share-target. Текст → chat_send «Мастер поделился: …» (без связи — в outbox на 2 минуты);
 * изображение → vision_request source:"camera" (JPEG 1280 / q70, в памяти). Окно-диалог с результатом.
 */
public class ShareActivity extends AppCompatActivity {
    public static final String PREFIX = "Мастер поделился: ";
    private static final long WAIT_ONLINE_MS = 10_000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_share);
        status = findViewById(R.id.share_status);
        findViewById(R.id.share_close).setOnClickListener(v -> finish());
        handle(getIntent());
    }

    static String textMessage(String shared) {
        String t = shared == null ? "" : shared.trim();
        return t.isEmpty() ? null : PREFIX + t;
    }

    private void handle(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) {
            finish();
            return;
        }
        String type = intent.getType() == null ? "" : intent.getType();
        if (type.startsWith("text/")) {
            String msg = textMessage(intent.getStringExtra(Intent.EXTRA_TEXT));
            if (msg == null) {
                finish();
                return;
            }
            status.setText("Отправляю Сакуре…");
            SakuraApp app = SakuraApp.get();
            app.client().chatSend(msg, app.voice().speakReplies(), new RequestClient.Callback() {
                @Override
                public void onResult(JSONObject result) {
                    main.post(() -> status.setText("Отправлено Сакуре"));
                }

                @Override
                public void onError(ApiError error) {
                    main.post(() -> status.setText(ApiError.OFFLINE.equals(error.code)
                            ? "Нет связи — отправлю, когда связь появится (до 2 минут)" : ErrorText.text(error)));
                }
            });
            return;
        }
        if (type.startsWith("image/")) {
            Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri.class);
            if (uri == null) {
                finish();
                return;
            }
            status.setText("Смотрю на картинку…");
            new Thread(() -> {
                String b64;
                try {
                    Bitmap bm = ImageDecoder.decodeBitmap(ImageDecoder.createSource(getContentResolver(), uri),
                            (decoder, info, src) -> {
                                int[] s = Vision.fit(info.getSize().getWidth(), info.getSize().getHeight());
                                decoder.setTargetSize(s[0], s[1]);
                                decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE);
                            });
                    b64 = Vision.encode(bm);
                    bm.recycle();
                } catch (IOException | RuntimeException e) {
                    main.post(() -> status.setText("Не удалось открыть картинку"));
                    return;
                }
                whenOnline(() -> Vision.ask(b64, null, text -> main.post(() -> status.setText(text))));
            }, "sakura-share").start();
            return;
        }
        finish();
    }

    /** Дождаться связи (приложение только что открылось). */
    private void whenOnline(Runnable r) {
        long end = System.currentTimeMillis() + WAIT_ONLINE_MS;
        Runnable[] check = new Runnable[1];
        check[0] = () -> {
            if (SakuraApp.get().client().status().conn == SakuraClient.Conn.ONLINE
                    || System.currentTimeMillis() > end) {
                r.run();
            } else {
                main.postDelayed(check[0], 200);
            }
        };
        main.post(check[0]);
    }
}
