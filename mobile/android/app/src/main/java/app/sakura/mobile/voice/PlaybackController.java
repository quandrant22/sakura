package app.sakura.mobile.voice;

/**
 * Логика проигрывания озвучки (без Android): ход по turn_id, преролл 150 мс, счётчик разрывов,
 * stall → idle через 3 с, перебивание. Вывод — через {@link Sink} (AudioTrack MODE_STREAM).
 * Вызывается из одного аудиопотока.
 */
public final class PlaybackController {
    public static final int DEFAULT_RATE = 24000;
    public static final long PREROLL_MS = 150;
    public static final long STALL_MS = 3000;

    /** Вывод PCM16 mono. */
    public interface Sink {
        /** Подготовить вывод на частоту rate (пересоздать при смене). */
        void open(int rate);

        void write(byte[] pcm);

        void play();

        /** Сбросить буфер и остановить. */
        void stop();

        /** Сколько кадров ещё не проиграно. */
        long pendingFrames();

        /** Счётчик недогрузок буфера (разрывов) с момента open. */
        int underruns();

        void release();
    }

    public interface Listener {
        void onSpeaking(boolean speaking);

        void onLevel(float level);

        /** Ход закончен: listen — сервер просит дослушать (tts_end.listen), stalled — поток оборвался. */
        void onFinished(String turnId, boolean listen, boolean stalled);
    }

    private enum Phase { IDLE, BUFFERING, PLAYING }

    private final Sink sink;
    private final Listener listener;

    private Phase phase = Phase.IDLE;
    private String turn;
    private String interruptedTurn;
    private int rate = DEFAULT_RATE;
    private long buffered;
    private long lastChunkAt;
    private boolean ended;
    private boolean listen;
    private int underrunsAtStart;
    private int gaps;
    private long droppedForeign;

    public PlaybackController(Sink sink, Listener listener) {
        this.sink = sink;
        this.listener = listener;
    }

    public boolean active() {
        return phase != Phase.IDLE;
    }

    public String turn() {
        return turn;
    }

    /** Разрывы за всё время (диагностика). */
    public int gaps() {
        return gaps;
    }

    public long droppedForeign() {
        return droppedForeign;
    }

    private static boolean same(String a, String b) {
        return a == null ? b == null : a.equals(b);
    }

    /** Кусок озвучки. turnId может быть null (сервер без turn_id). */
    public void onChunk(String turnId, byte[] pcm, int sampleRate, long now) {
        if (turnId != null && same(turnId, interruptedTurn)) {
            droppedForeign++;
            return;   // хвост перебитого хода
        }
        if (phase == Phase.IDLE) {
            turn = turnId;
            ended = false;
            listen = false;
            buffered = 0;
            rate = sampleRate > 0 ? sampleRate : DEFAULT_RATE;
            sink.open(rate);   // каждый ход — чистый поток (пересоздаётся только при смене частоты)
            underrunsAtStart = sink.underruns();
            phase = Phase.BUFFERING;
            listener.onSpeaking(true);
        } else if (turnId != null && turn != null && !turnId.equals(turn)) {
            droppedForeign++;
            return;   // чужой ход посреди текущего
        }
        lastChunkAt = now;
        sink.write(pcm);
        buffered += pcm.length / 2;
        listener.onLevel(rms(pcm));
        if (phase == Phase.BUFFERING && buffered * 1000 >= PREROLL_MS * rate) {
            sink.play();
            phase = Phase.PLAYING;
        }
    }

    /** tts_end. Чужой ход игнорируется. */
    public void onEnd(String turnId, boolean listenAfter, long now) {
        if (phase == Phase.IDLE) {
            if (turnId == null || !same(turnId, interruptedTurn)) {
                listener.onFinished(turnId, listenAfter, false);   // ход без озвучки
            }
            return;
        }
        if (turnId != null && turn != null && !turnId.equals(turn)) {
            return;
        }
        ended = true;
        listen = listenAfter;
        if (phase == Phase.BUFFERING) {
            sink.play();   // короткий ответ меньше преролла
            phase = Phase.PLAYING;
        }
        tick(now);
    }

    /** Периодически (~50–100 мс): конец проигрывания, stall, учёт разрывов. */
    public void tick(long now) {
        if (phase == Phase.IDLE) {
            return;
        }
        if (ended && phase == Phase.PLAYING && sink.pendingFrames() <= 0) {
            finish(false);
            return;
        }
        if (!ended && now - lastChunkAt >= STALL_MS) {
            sink.stop();
            finish(true);
        }
    }

    /** Перебивание: тап по ядру, кнопка гарнитуры, «Сакура». */
    public void interrupt() {
        if (phase == Phase.IDLE) {
            return;
        }
        interruptedTurn = turn;
        sink.stop();
        String t = turn;
        reset();
        listener.onLevel(0);
        listener.onSpeaking(false);
        listener.onFinished(t, false, false);
    }

    private void finish(boolean stalled) {
        String t = turn;
        boolean l = listen && !stalled;
        reset();
        listener.onLevel(0);
        listener.onSpeaking(false);
        listener.onFinished(t, l, stalled);
    }

    private void reset() {
        gaps += Math.max(0, sink.underruns() - underrunsAtStart);
        phase = Phase.IDLE;
        turn = null;
        buffered = 0;
        ended = false;
        listen = false;
    }

    /** Громкость куска 0..1 (RMS PCM16, 0 дБFS ≈ 1). */
    public static float rms(byte[] pcm) {
        int n = pcm.length / 2;
        if (n == 0) {
            return 0;
        }
        double sum = 0;
        for (int i = 0; i < n; i++) {
            int s = (short) ((pcm[2 * i] & 0xFF) | (pcm[2 * i + 1] << 8));
            sum += (double) s * s;
        }
        double r = Math.sqrt(sum / n) / 32768.0;
        return (float) Math.min(1, r * 4);
    }
}
