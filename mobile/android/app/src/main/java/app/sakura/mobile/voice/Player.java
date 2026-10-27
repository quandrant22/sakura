package app.sakura.mobile.voice;

import android.content.Context;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Process;
import android.os.SystemClock;
import android.util.Base64;

/** Озвучка на потоке «sakura-audio»: декод base64, PlaybackController, тик 50 мс. */
public final class Player {
    private static final long TICK_MS = 50;

    private final Handler handler;
    private final PlaybackController controller;
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            controller.tick(SystemClock.elapsedRealtime());
            if (controller.active()) {
                handler.postDelayed(this, TICK_MS);
            }
        }
    };

    public Player(Context context, PlaybackController.Listener listener) {
        HandlerThread t = new HandlerThread("sakura-audio", Process.THREAD_PRIORITY_AUDIO);
        t.start();
        handler = new Handler(t.getLooper());
        controller = new PlaybackController(new AudioTrackSink(context.getApplicationContext()), listener);
    }

    public void chunk(String turnId, String audioB64, int sampleRate) {
        handler.post(() -> {
            byte[] pcm;
            try {
                pcm = Base64.decode(audioB64, Base64.DEFAULT);
            } catch (IllegalArgumentException e) {
                return;
            }
            boolean was = controller.active();
            controller.onChunk(turnId, pcm, sampleRate, SystemClock.elapsedRealtime());
            if (!was && controller.active()) {
                handler.removeCallbacks(tick);
                handler.postDelayed(tick, TICK_MS);
            }
        });
    }

    public void end(String turnId, boolean listen) {
        handler.post(() -> controller.onEnd(turnId, listen, SystemClock.elapsedRealtime()));
    }

    public void interrupt() {
        handler.post(controller::interrupt);
    }

    public boolean active() {
        return controller.active();
    }

    public int gaps() {
        return controller.gaps();
    }
}
