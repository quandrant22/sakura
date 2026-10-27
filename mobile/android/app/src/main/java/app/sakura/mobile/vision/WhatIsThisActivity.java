package app.sakura.mobile.vision;

import android.Manifest;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Matrix;
import android.os.Bundle;
import android.view.View;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.ui.Motion;

/**
 * «Что это?»: CameraX, снимок в память (OnImageCapturedCallback — без файла), JPEG 1280 / q70 →
 * vision_request source:"camera". Ядро приходит общим элементом из «Диалога».
 */
public class WhatIsThisActivity extends AppCompatActivity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> new Thread(r, "sakura-vision"));
    private ImageCapture capture;
    private SakuraCoreView core;
    private TextView answer;
    private final ActivityResultLauncher<String> camera = registerForActivityResult(
            new ActivityResultContracts.RequestPermission(), granted -> {
                if (granted) {
                    startCamera();
                } else {
                    show("Нужно разрешение камеры (Ещё → Разрешения)");
                }
            });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        setTheme(app.sakura.mobile.app.Settings.THEME_SKETCH.equals(SakuraApp.get().settings().theme())
                ? R.style.Theme_Sakura_Sketch : R.style.Theme_Sakura_Night);
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_what);
        core = findViewById(R.id.core);
        answer = findViewById(R.id.answer);
        SakuraApp.get().voice().state().observe(this, core::setState);
        findViewById(R.id.shoot).setOnClickListener(v -> shoot(v));
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startCamera();
        } else {
            camera.launch(Manifest.permission.CAMERA);
        }
    }

    private void startCamera() {
        ListenableFuture<ProcessCameraProvider> f = ProcessCameraProvider.getInstance(this);
        f.addListener(() -> {
            try {
                ProcessCameraProvider provider = f.get();
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(((PreviewView) findViewById(R.id.preview)).getSurfaceProvider());
                capture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .build();
                provider.unbindAll();
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture);
            } catch (Exception e) {
                show("Камера недоступна");
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void shoot(View v) {
        if (capture == null) {
            return;
        }
        Motion.confirm(v);
        core.setState(CoreFrame.State.THINKING);
        show("Смотрю…");
        capture.takePicture(worker, new ImageCapture.OnImageCapturedCallback() {
            @Override
            public void onCaptureSuccess(@NonNull ImageProxy image) {
                String b64;
                try {
                    Bitmap raw = image.toBitmap();
                    int rot = image.getImageInfo().getRotationDegrees();
                    Bitmap upright = raw;
                    if (rot != 0) {
                        Matrix m = new Matrix();
                        m.postRotate(rot);
                        upright = Bitmap.createBitmap(raw, 0, 0, raw.getWidth(), raw.getHeight(), m, true);
                        raw.recycle();
                    }
                    b64 = Vision.encode(upright);
                    upright.recycle();
                } finally {
                    image.close();
                }
                Vision.ask(b64, null, text -> runOnUiThread(() -> show(text)));
            }

            @Override
            public void onError(@NonNull ImageCaptureException exception) {
                runOnUiThread(() -> show("Снимок не получился"));
            }
        });
    }

    private void show(String text) {
        answer.setVisibility(View.VISIBLE);
        answer.setText(text);
    }

    @Override
    protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }
}
