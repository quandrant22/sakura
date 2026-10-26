package app.sakura.mobile.ui;

import android.animation.ValueAnimator;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.view.animation.DecelerateInterpolator;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;

/**
 * Анимации интерфейса: появление пузырей (fade + сдвиг 8dp, 150 мс), смена экранов 150 мс,
 * тактильный отклик. «Убрать анимации» (или системное отключение) — без движения.
 */
public final class Motion {
    public static final long BUBBLE_MS = 150;
    public static final long SCREEN_MS = 150;
    private static final DecelerateInterpolator EASE = new DecelerateInterpolator();

    private Motion() {
    }

    public static boolean reduced() {
        SakuraApp app = SakuraApp.get();
        boolean user = app != null && app.settings().reduceMotion();
        return user || !ValueAnimator.areAnimatorsEnabled();
    }

    public static void bubbleIn(View v) {
        v.animate().cancel();
        if (reduced()) {
            v.setAlpha(1);
            v.setTranslationY(0);
            return;
        }
        v.setAlpha(0);
        v.setTranslationY(v.getResources().getDimension(R.dimen.bubble_shift));
        v.animate().alpha(1).translationY(0).setDuration(BUBBLE_MS).setInterpolator(EASE).start();
    }

    public static void screenIn(View v) {
        v.animate().cancel();
        if (reduced()) {
            v.setAlpha(1);
            return;
        }
        v.setAlpha(0);
        v.animate().alpha(1).setDuration(SCREEN_MS).setInterpolator(EASE).start();
    }

    /** Нажатие PTT (начало удержания). */
    public static void pttStart(View v) {
        v.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);
    }

    public static void pttEnd(View v) {
        v.performHapticFeedback(HapticFeedbackConstants.GESTURE_END);
    }

    /** Подтверждение (Да/Нет, удаление). */
    public static void confirm(View v) {
        v.performHapticFeedback(HapticFeedbackConstants.CONFIRM);
    }

    public static void reject(View v) {
        v.performHapticFeedback(HapticFeedbackConstants.REJECT);
    }
}
