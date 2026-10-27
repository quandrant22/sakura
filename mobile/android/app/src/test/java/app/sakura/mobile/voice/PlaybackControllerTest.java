package app.sakura.mobile.voice;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.ArrayList;
import java.util.List;

public class PlaybackControllerTest {

    static final class FakeSink implements PlaybackController.Sink {
        int opened;
        int rate;
        long written;
        long played;
        boolean playing;
        int stops;
        int underruns;

        @Override
        public void open(int r) {
            opened++;
            rate = r;
            written = 0;
            played = 0;
            playing = false;
        }

        @Override
        public void write(byte[] pcm) {
            written += pcm.length / 2;
        }

        @Override
        public void play() {
            playing = true;
        }

        @Override
        public void stop() {
            stops++;
            playing = false;
            written = 0;
            played = 0;
        }

        @Override
        public long pendingFrames() {
            return written - played;
        }

        @Override
        public int underruns() {
            return underruns;
        }

        @Override
        public void release() {
        }
    }

    static final class Events implements PlaybackController.Listener {
        final List<String> log = new ArrayList<>();

        @Override
        public void onSpeaking(boolean speaking) {
            log.add("speaking=" + speaking);
        }

        @Override
        public void onLevel(float level) {
        }

        @Override
        public void onFinished(String turnId, boolean listen, boolean stalled) {
            log.add("finished " + turnId + " listen=" + listen + " stalled=" + stalled);
        }
    }

    /** n мс PCM16 24 кГц. */
    static byte[] ms(int n) {
        return new byte[24 * n * 2];
    }

    @Test
    public void prerollThenPlay() {
        FakeSink s = new FakeSink();
        Events e = new Events();
        PlaybackController p = new PlaybackController(s, e);
        p.onChunk("t1", ms(100), 24000, 0);
        assertFalse("меньше 150 мс — ждём", s.playing);
        assertEquals(24000, s.rate);
        p.onChunk("t1", ms(60), 24000, 100);
        assertTrue(s.playing);
        assertEquals("speaking=true", e.log.get(0));
    }

    @Test
    public void foreignTurnDropped() {
        FakeSink s = new FakeSink();
        PlaybackController p = new PlaybackController(s, new Events());
        p.onChunk("t1", ms(200), 24000, 0);
        p.onChunk("t2", ms(200), 24000, 10);
        assertEquals(24 * 200, s.written);
        assertEquals(1, p.droppedForeign());
        p.onEnd("t2", false, 20);   // чужой tts_end ход не закрывает
        assertTrue(p.active());
    }

    @Test
    public void endWaitsForDrain() {
        FakeSink s = new FakeSink();
        Events e = new Events();
        PlaybackController p = new PlaybackController(s, e);
        p.onChunk("t1", ms(200), 24000, 0);
        p.onEnd("t1", true, 50);
        assertTrue("ещё звучит", p.active());
        s.played = s.written;
        p.tick(400);
        assertFalse(p.active());
        assertEquals("finished t1 listen=true stalled=false", e.log.get(e.log.size() - 1));
    }

    @Test
    public void shortReplyBelowPrerollStillPlays() {
        FakeSink s = new FakeSink();
        PlaybackController p = new PlaybackController(s, new Events());
        p.onChunk("t1", ms(40), 24000, 0);
        p.onEnd("t1", false, 10);
        assertTrue(s.playing);
    }

    @Test
    public void stallGoesIdleAfter3s() {
        FakeSink s = new FakeSink();
        Events e = new Events();
        PlaybackController p = new PlaybackController(s, e);
        p.onChunk("t1", ms(200), 24000, 1000);
        p.tick(3999);
        assertTrue(p.active());
        p.tick(4000);
        assertFalse(p.active());
        assertEquals(1, s.stops);
        assertTrue(e.log.get(e.log.size() - 1).endsWith("stalled=true"));
    }

    @Test
    public void interruptDropsTailOfTurn() {
        FakeSink s = new FakeSink();
        Events e = new Events();
        PlaybackController p = new PlaybackController(s, e);
        p.onChunk("t1", ms(200), 24000, 0);
        p.interrupt();
        assertFalse(p.active());
        p.onChunk("t1", ms(200), 24000, 50);
        assertFalse("хвост перебитого хода не звучит", p.active());
        p.onChunk("t2", ms(200), 24000, 60);
        assertTrue("новый ход звучит", p.active());
    }

    @Test
    public void gapsCounted() {
        FakeSink s = new FakeSink();
        PlaybackController p = new PlaybackController(s, new Events());
        p.onChunk("t1", ms(200), 24000, 0);
        s.underruns = 2;
        p.onEnd("t1", false, 10);
        s.played = s.written;
        p.tick(20);
        assertEquals(2, p.gaps());
    }

    @Test
    public void endWithoutAudioFinishesImmediately() {
        Events e = new Events();
        PlaybackController p = new PlaybackController(new FakeSink(), e);
        p.onEnd("t9", true, 0);
        assertEquals("finished t9 listen=true stalled=false", e.log.get(0));
    }

    @Test
    public void rms() {
        assertEquals(0f, PlaybackController.rms(new byte[100]), 0);
        byte[] loud = new byte[200];
        for (int i = 0; i < 100; i++) {
            loud[2 * i] = (byte) 0xFF;
            loud[2 * i + 1] = 0x3F;   // ~16383
        }
        assertEquals(1f, PlaybackController.rms(loud), 0.01);
    }

    @Test
    public void followUp() {
        assertTrue(FollowUp.isQuestion("confirm", "Выключить?"));
        assertTrue(FollowUp.isQuestion("llm", "Какой компьютер: игровой, ноутбук?"));
        assertTrue(FollowUp.isQuestion("llm", "Включить «Мою волну?»"));
        assertFalse(FollowUp.isQuestion("llm", "Готово."));
        assertEquals(6000, FollowUp.windowMs(6));
        assertEquals(15000, FollowUp.windowMs(40));
        assertEquals(0, FollowUp.windowMs(-1));
        assertEquals("да", FollowUp.confirmWord(true));
    }

    @Test
    public void wakeWordMatch() {
        assertTrue(WakeWord.hasWord("{\"partial\" : \"сакура\"}"));
        assertTrue(WakeWord.hasWord("{\"text\" : \"[unk] сакура\"}"));
        assertFalse(WakeWord.hasWord("{\"text\" : \"[unk]\"}"));
        assertFalse(WakeWord.hasWord(null));
    }
}
