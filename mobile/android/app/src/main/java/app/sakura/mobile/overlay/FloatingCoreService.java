package app.sakura.mobile.overlay;

import android.annotation.SuppressLint;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.os.IBinder;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.widget.ImageView;

import androidx.lifecycle.Observer;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.ui.MainActivity;
import app.sakura.mobile.ui.Motion;

/**
 * Плавающее ядро поверх приложений (TYPE_APPLICATION_OVERLAY, 56dp): состояния как у ядра,
 * перетаскивание с прилипанием к краю, внизу при перетаскивании — зона «×» (бросить — выключить).
 * Тап — открыть приложение и слушать.
 */
public class FloatingCoreService extends Service {
    private WindowManager wm;
    private SakuraCoreView core;
    private ImageView close;
    private WindowManager.LayoutParams lp;
    private WindowManager.LayoutParams closeLp;
    private final Observer<CoreFrame.State> stateObserver = s -> core.setState(s);
    private final Runnable levelPump = new Runnable() {
        @Override
        public void run() {
            core.setLevel(SakuraApp.get().voice().level());
            core.postOnAnimation(this);
        }
    };

    public static void start(Context c) {
        c.startService(new Intent(c, FloatingCoreService.class));
    }

    public static void stop(Context c) {
        c.stopService(new Intent(c, FloatingCoreService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        if (!android.provider.Settings.canDrawOverlays(this)) {
            stopSelf();
            return;
        }
        wm = getSystemService(WindowManager.class);
        Context themed = new android.view.ContextThemeWrapper(this, R.style.Theme_Sakura_Night);
        int size = getResources().getDimensionPixelSize(R.dimen.core_floating);
        core = new SakuraCoreView(themed);
        core.setReduceMotion(SakuraApp.get().settings().reduceMotion());
        core.setContentDescription("Плавающее ядро Сакуры");
        lp = new WindowManager.LayoutParams(size, size, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        DisplayMetrics dm = getResources().getDisplayMetrics();
        int margin = getResources().getDimensionPixelSize(R.dimen.gap_small);
        lp.x = dm.widthPixels - size - margin;
        lp.y = dm.heightPixels / 3;
        close = new ImageView(themed);
        close.setImageResource(R.drawable.ic_close);
        close.setBackgroundResource(R.drawable.bg_card);
        close.setPadding(size / 4, size / 4, size / 4, size / 4);
        close.setContentDescription("Убрать плавающее ядро");
        closeLp = new WindowManager.LayoutParams(size, size, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                PixelFormat.TRANSLUCENT);
        closeLp.gravity = Gravity.TOP | Gravity.START;
        closeLp.x = (dm.widthPixels - size) / 2;
        closeLp.y = dm.heightPixels - size * 3;
        close.setVisibility(View.GONE);
        wm.addView(close, closeLp);
        wm.addView(core, lp);
        bindTouch(size, margin);
        SakuraApp.get().voice().state().observeForever(stateObserver);
        core.postOnAnimation(levelPump);
    }

    @SuppressLint("ClickableViewAccessibility")
    private void bindTouch(int size, int margin) {
        int slop = ViewConfiguration.get(this).getScaledTouchSlop();
        float[] down = new float[4];
        boolean[] dragging = {false};
        core.setOnTouchListener((v, e) -> {
            DisplayMetrics dm = getResources().getDisplayMetrics();
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    down[0] = e.getRawX();
                    down[1] = e.getRawY();
                    down[2] = lp.x;
                    down[3] = lp.y;
                    dragging[0] = false;
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    float dx = e.getRawX() - down[0];
                    float dy = e.getRawY() - down[1];
                    if (!dragging[0] && Math.hypot(dx, dy) > slop) {
                        dragging[0] = true;
                        close.setVisibility(View.VISIBLE);
                    }
                    if (dragging[0]) {
                        lp.x = (int) (down[2] + dx);
                        lp.y = (int) (down[3] + dy);
                        wm.updateViewLayout(core, lp);
                    }
                    return true;
                }
                case MotionEvent.ACTION_UP:
                    close.setVisibility(View.GONE);
                    if (!dragging[0]) {
                        startActivity(new Intent(this, MainActivity.class).setAction(MainActivity.ACTION_LISTEN)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
                        return true;
                    }
                    if (Snap.overClose(lp.x, lp.y, size, closeLp.x + size / 2, closeLp.y + size / 2, size)) {
                        Motion.confirm(core);
                        SakuraApp.get().settings().setFloatingCore(false);
                        stopSelf();
                        return true;
                    }
                    lp.x = Snap.edgeX(lp.x, size, dm.widthPixels, margin);
                    lp.y = Snap.clampY(lp.y, size, dm.heightPixels, margin);
                    wm.updateViewLayout(core, lp);
                    return true;
                default:
                    return false;
            }
        });
    }

    @Override
    public void onDestroy() {
        if (core != null) {
            core.removeCallbacks(levelPump);
            SakuraApp.get().voice().state().removeObserver(stateObserver);
            wm.removeView(core);
            wm.removeView(close);
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
