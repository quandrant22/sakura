package app.sakura.mobile.ui;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentManager;
import androidx.fragment.app.FragmentTransaction;

import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import org.json.JSONObject;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.app.Settings;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.control.ControlFragment;
import app.sakura.mobile.ui.dialog.ChatFragment;
import app.sakura.mobile.ui.more.MoreFragment;
import app.sakura.mobile.ui.more.SecurityFragment;
import app.sakura.mobile.ui.scenarios.ScenariosFragment;
import app.sakura.mobile.ui.summary.SummaryFragment;
import app.sakura.mobile.voice.VoiceController;

/**
 * Пять вкладок (Диалог, Пульт, Сводка, Сценарии, Ещё), подэкраны поверх вкладки со стеком «Назад»
 * (predictive back), переходы 150 мс, общий диалог подтверждения reply kind:"confirm".
 */
public class MainActivity extends AppCompatActivity {
    /** Открыть приложение и сразу слушать (уведомление, плитка, виджет, ассистент). */
    public static final String ACTION_LISTEN = "app.sakura.mobile.LISTEN";
    /** Из уведомления «нет разрешения: …» — сразу экран «Разрешения». */
    public static final String ACTION_PERMISSIONS = "app.sakura.mobile.PERMISSIONS";
    private static final long PTT_HOLD_MS = 600;
    private static final int[] TABS = {R.id.tab_dialog, R.id.tab_control, R.id.tab_summary, R.id.tab_scenarios,
            R.id.tab_more};

    private VoiceController voice;
    private boolean pttActive;
    private Runnable afterPermission;
    private AlertDialog confirmDialog;
    private Runnable unsubscribeConfirm;
    private Runnable unsubscribeStatus;
    private TextView banner;
    private final ActivityResultLauncher<String> micPermission = registerForActivityResult(
            new ActivityResultContracts.RequestPermission(), granted -> {
                Runnable r = afterPermission;
                afterPermission = null;
                if (granted && r != null) {
                    r.run();
                }
            });

    static int themeRes(String theme) {
        return Settings.THEME_SKETCH.equals(theme) ? R.style.Theme_Sakura_Sketch : R.style.Theme_Sakura_Night;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        SakuraApp app = SakuraApp.get();
        setTheme(themeRes(app.settings().theme()));
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsetsCompat.CONSUMED;
        });
        voice = app.voice();
        banner = findViewById(R.id.banner);
        BottomNavigationView nav = findViewById(R.id.nav);
        nav.setOnItemSelectedListener(item -> {
            showTab(item.getItemId());
            return true;
        });
        nav.setOnItemReselectedListener(item -> getSupportFragmentManager()
                .popBackStack(null, FragmentManager.POP_BACK_STACK_INCLUSIVE));
        if (savedInstanceState == null) {
            showTab(R.id.tab_dialog);
        }
        unsubscribeConfirm = app.client().bus().subscribe("reply", m -> {
            if ("confirm".equals(m.optString("kind"))) {
                runOnUiThread(() -> showConfirm(m));
            }
        });
        unsubscribeStatus = app.client().onStatus(s -> runOnUiThread(() -> renderBanner(s)));
        handleIntent(getIntent());
    }

    private static String tag(int tab) {
        return "tab" + tab;
    }

    private void showTab(int id) {
        FragmentManager fm = getSupportFragmentManager();
        fm.popBackStackImmediate(null, FragmentManager.POP_BACK_STACK_INCLUSIVE);
        FragmentTransaction tx = fm.beginTransaction().setReorderingAllowed(true);
        if (!Motion.reduced()) {
            tx.setCustomAnimations(R.anim.screen_in, R.anim.screen_out);
        }
        for (int t : TABS) {
            Fragment f = fm.findFragmentByTag(tag(t));
            if (t == id) {
                if (f == null) {
                    tx.add(R.id.content, create(t), tag(t));
                } else {
                    tx.show(f);
                }
            } else if (f != null) {
                tx.hide(f);
            }
        }
        tx.commit();
    }

    private static Fragment create(int tab) {
        if (tab == R.id.tab_control) {
            return new ControlFragment();
        }
        if (tab == R.id.tab_summary) {
            return new SummaryFragment();
        }
        if (tab == R.id.tab_scenarios) {
            return new ScenariosFragment();
        }
        if (tab == R.id.tab_more) {
            return new MoreFragment();
        }
        return new ChatFragment();
    }

    /** Подэкран поверх текущей вкладки (Назад — вернуться). */
    public void push(Fragment f) {
        FragmentManager fm = getSupportFragmentManager();
        FragmentTransaction tx = fm.beginTransaction().setReorderingAllowed(true);
        if (!Motion.reduced()) {
            tx.setCustomAnimations(R.anim.screen_in, R.anim.screen_out, R.anim.screen_in, R.anim.screen_out);
        }
        for (Fragment x : fm.getFragments()) {
            if (x.isVisible()) {
                tx.hide(x);
            }
        }
        tx.add(R.id.content, f).addToBackStack(null).commit();
    }

    private void renderBanner(SakuraClient.Status s) {
        String text = null;
        View.OnClickListener click = null;
        if (s.conn == SakuraClient.Conn.UNPAIRED) {
            text = "Телефон не спарен с Сакурой — нажмите, чтобы спарить";
            click = v -> {
                ((BottomNavigationView) findViewById(R.id.nav)).setSelectedItemId(R.id.tab_more);
                push(new SecurityFragment());
            };
        } else if (s.conn == SakuraClient.Conn.ONLINE && s.proto < 2) {
            text = "Сервер ещё не поддерживает приложение телефона: доступны только голос и текст";
        } else if (s.conn == SakuraClient.Conn.ONLINE && !s.master) {
            text = "Сервер не выдал телефону прав master: пульт и сценарии недоступны";
        }
        banner.setVisibility(text == null ? View.GONE : View.VISIBLE);
        banner.setText(text);
        banner.setOnClickListener(click);
    }

    /** Вопрос Сакуры «Да или нет?» (питание и др.): ответ voice_command «да»/«нет», channel:"text". */
    private void showConfirm(JSONObject reply) {
        if (confirmDialog != null) {
            confirmDialog.dismiss();
        }
        View root = findViewById(R.id.main);
        confirmDialog = new MaterialAlertDialogBuilder(this)
                .setTitle("Сакура спрашивает")
                .setMessage(reply.optString("text"))
                .setPositiveButton("Да", (d, w) -> {
                    Motion.confirm(root);
                    voice.answerConfirm(true);
                })
                .setNegativeButton("Нет", (d, w) -> {
                    Motion.reject(root);
                    voice.answerConfirm(false);
                })
                .show();
    }

    /** Тап — говорить/перебить; удержание 600 мс — PTT с вибрацией. */
    @SuppressLint("ClickableViewAccessibility")
    public void bindCore(SakuraCoreView core) {
        Settings s = SakuraApp.get().settings();
        core.setReduceMotion(s.reduceMotion());
        core.setMobility(CoreFrame.Mobility.of(s.mobility()));
        core.setPreset(CoreFrame.MergePreset.of(s.mergePreset()));
        Runnable startPtt = () -> withMic(() -> {
            pttActive = true;
            Motion.pttStart(core);
            voice.pttDown();
        });
        core.setOnTouchListener((v, e) -> {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
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

    public void withMic(Runnable r) {
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
        if (intent != null && ACTION_PERMISSIONS.equals(intent.getAction())) {
            intent.setAction(null);
            ((BottomNavigationView) findViewById(R.id.nav)).setSelectedItemId(R.id.tab_more);
            findViewById(R.id.main).post(() -> push(new app.sakura.mobile.ui.more.PermissionsFragment()));
            return;
        }
        if (intent != null && ACTION_LISTEN.equals(intent.getAction())) {
            intent.setAction(null);
            ((BottomNavigationView) findViewById(R.id.nav)).setSelectedItemId(R.id.tab_dialog);
            findViewById(R.id.main).post(() -> withMic(voice::tap));
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        voice.setForeground(true);
    }

    @Override
    protected void onStop() {
        voice.setForeground(false);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        unsubscribeConfirm.run();
        unsubscribeStatus.run();
        if (confirmDialog != null) {
            confirmDialog.dismiss();
        }
        super.onDestroy();
    }

    /** Кнопка гарнитуры, пока приложение на экране (D24). */
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
