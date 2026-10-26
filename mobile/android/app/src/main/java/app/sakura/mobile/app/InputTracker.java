package app.sakura.mobile.app;

import android.os.SystemClock;

/** Время последнего ввода Мастера в приложении (касание, голос, текст) → input_idle_s. */
public final class InputTracker {
    private volatile long lastInput = SystemClock.elapsedRealtime();

    public void touch() {
        lastInput = SystemClock.elapsedRealtime();
    }

    public double idleSeconds() {
        return (SystemClock.elapsedRealtime() - lastInput) / 1000.0;
    }
}
