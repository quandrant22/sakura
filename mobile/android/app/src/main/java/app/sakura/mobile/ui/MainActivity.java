package app.sakura.mobile.ui;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.voice.VoiceController;

public class MainActivity extends AppCompatActivity {
    /** Открыть приложение и сразу слушать (уведомление, плитка, виджет). */
    public static final String ACTION_LISTEN = "app.sakura.mobile.LISTEN";
    private static final long PTT_HOLD_MS = 600;

    private VoiceController voice;
    private SakuraCoreView core;
    private boolean pttActive;
    private Runnable afterPermission;
    private final Runnable levelPump = new Runnable() {
        @Override
        public void run() {
            core.setLevel(voice.level());
            core.postOnAnimation(this);
        }
    };
    private final ActivityResultLauncher<String> micPermission = registerForActivityResult(
            new ActivityResultContracts.RequestPermission(), granted -> {
                Runnable r = afterPermission;
                afterPermission = null;
                if (granted && r != null) {
                    r.run();
                }
            });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        SakuraApp app = SakuraApp.get();
        voice = app.voice();
        core = findViewById(R.id.core);
        core.setReduceMotion(app.settings().reduceMotion());
        core.setMobility(CoreFrame.Mobility.of(app.settings().mobility()));
        core.setPreset(CoreFrame.MergePreset.of(app.settings().mergePreset()));
        TextView status = findViewById(R.id.core_status);
        TextView transcript = findViewById(R.id.transcript);
        voice.state().observe(this, s -> {
            core.setState(s);
            status.setText(statusText(s));
        });
        voice.transcript().observe(this, transcript::setText);
        bindCore();
        handleIntent(getIntent());
    }

    static String statusText(CoreFrame.State s) {
        switch (s) {
            case LISTENING:
                return "Слушаю";
            case THINKING:
                return "Думаю";
            case SPEAKING:
                return "Говорю";
            case OFFLINE:
                return "Нет связи";
            case IDLE:
            default:
                return "Онлайн";
        }
    }

    /** Тап — говорить/перебить; удержание 600 мс — PTT с вибрацией. */
    @SuppressLint("ClickableViewAccessibility")
    private void bindCore() {
        Runnable startPtt = () -> withMic(() -> {
            pttActive = true;
            Motion.pttStart(core);
            voice.pttDown();
        });
        core.setOnTouchListener((v, e) -> {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    SakuraApp.get().input().touch();
                    v.postDelayed(startPtt, PTT_HOLD_MS);
                    return true;
                case MotionEvent.ACTION_UP:
                    v.removeCallbacks(startPtt);
                    if (pttActive) {
                        pttActive = false;
                        Motion.pttEnd(core);
                        voice.pttUp();
                    } else {
                        v.performClick();
                    }
                    return true;
                case MotionEvent.ACTION_CANCEL:
                    v.removeCallbacks(startPtt);
                    if (pttActive) {
                        pttActive = false;
                        voice.pttUp();
                    }
                    return true;
                default:
                    return false;
            }
        });
        core.setOnClickListener(v -> withMic(voice::tap));
    }

    private void withMic(Runnable r) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            r.run();
        } else {
            afterPermission = r;
            micPermission.launch(Manifest.permission.RECORD_AUDIO);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent != null && ACTION_LISTEN.equals(intent.getAction())) {
            intent.setAction(null);
            core.post(() -> withMic(voice::tap));
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        voice.setForeground(true);
        core.postOnAnimation(levelPump);
    }

    @Override
    protected void onStop() {
        core.removeCallbacks(levelPump);
        voice.setForeground(false);
        super.onStop();
    }

    /** Кнопка гарнитуры, пока приложение на экране. */
    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_HEADSETHOOK || keyCode == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE) {
            if (event.getRepeatCount() == 0) {
                withMic(voice::tap);
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent ev) {
        if (ev.getActionMasked() == MotionEvent.ACTION_DOWN) {
            SakuraApp.get().input().touch();
        }
        return super.dispatchTouchEvent(ev);
    }
}
