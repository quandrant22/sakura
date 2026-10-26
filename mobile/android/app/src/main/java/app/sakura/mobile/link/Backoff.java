package app.sakura.mobile.link;

import java.util.Random;

/** Переподключение: 1 → 2 → 4 … → 30 с, с джиттером ±20 %; сброс после успешного сеанса. */
public final class Backoff {
    public static final long MIN_MS = 1000;
    public static final long MAX_MS = 30_000;

    private final Random random;
    private int attempt;

    public Backoff(Random random) {
        this.random = random;
    }

    public long nextDelayMs() {
        long base = Math.min(MAX_MS, MIN_MS << Math.min(attempt, 5));
        attempt++;
        double jitter = 0.8 + random.nextDouble() * 0.4;
        return Math.max(MIN_MS, Math.min(MAX_MS, Math.round(base * jitter)));
    }

    public void reset() {
        attempt = 0;
    }

    public int attempts() {
        return attempt;
    }
}
