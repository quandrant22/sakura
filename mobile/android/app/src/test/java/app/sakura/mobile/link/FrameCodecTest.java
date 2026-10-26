package app.sakura.mobile.link;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

import java.util.List;
import java.util.Random;

import app.sakura.mobile.crypto.noise.CipherState;

public class FrameCodecTest {

    @Test
    public void roundTrip() throws Exception {
        byte[] f = FrameCodec.encodeFrame(FrameCodec.TRANSPORT, new byte[]{1, 2, 3});
        assertArrayEquals(new byte[]{0x53, 0x4B, 1, 0x20, 0, 0, 0, 3, 1, 2, 3}, f);
        FrameCodec.Frame d = FrameCodec.decodeFrame(f);
        assertEquals(FrameCodec.TRANSPORT, d.type);
        assertArrayEquals(new byte[]{1, 2, 3}, d.body);
    }

    @Test
    public void strictLength() throws Exception {
        byte[] f = FrameCodec.encodeFrame(FrameCodec.IK_INIT, new byte[4]);
        byte[] longer = java.util.Arrays.copyOf(f, f.length + 1);
        byte[] shorter = java.util.Arrays.copyOf(f, f.length - 1);
        assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeFrame(longer));
        assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeFrame(shorter));
    }

    @Test
    public void rejectsBadHeader() throws Exception {
        byte[] f = FrameCodec.encodeFrame(FrameCodec.IK_INIT, new byte[0]);
        byte[] magic = f.clone();
        magic[0] = 0x54;
        byte[] ver = f.clone();
        ver[2] = 2;
        byte[] type = f.clone();
        type[3] = 0x7F;
        for (byte[] bad : new byte[][]{magic, ver, type, new byte[5]}) {
            assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeFrame(bad));
        }
    }

    @Test
    public void bodyLimit() {
        assertThrows(FrameCodec.FrameException.class,
                () -> FrameCodec.encodeFrame(FrameCodec.TRANSPORT, new byte[65536]));
    }

    @Test
    public void lengthAbove65535Rejected() throws Exception {
        byte[] f = new byte[8 + 70000];
        f[0] = 0x53;
        f[1] = 0x4B;
        f[2] = 1;
        f[3] = 0x20;
        f[5] = 1;
        f[6] = 0x11;
        f[7] = 0x70;
        assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeFrame(f));
    }

    @Test
    public void innerFlags() {
        assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeInner(new byte[]{1, 2}));
        assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeInner(new byte[]{9, 0}));
        assertThrows(FrameCodec.FrameException.class, () -> FrameCodec.decodeInner(new byte[]{1}));
    }

    @Test
    public void fragmentAndReassemble() throws Exception {
        byte[] msg = new byte[FrameCodec.MAX_CHUNK * 2 + 10];
        new Random(1).nextBytes(msg);
        List<byte[]> parts = FrameCodec.fragment(msg);
        assertEquals(3, parts.size());
        FrameCodec.Reassembler r = new FrameCodec.Reassembler();
        byte[] out = null;
        for (byte[] p : parts) {
            FrameCodec.Inner in = FrameCodec.decodeInner(p);
            out = r.feed(in.flags, in.data);
        }
        assertArrayEquals(msg, out);
        assertEquals(1, FrameCodec.fragment(new byte[0]).size());
    }

    @Test
    public void limits() {
        assertThrows(FrameCodec.TooLargeException.class,
                () -> FrameCodec.fragment(new byte[FrameCodec.MAX_MESSAGE + 1]));
        FrameCodec.Reassembler r = new FrameCodec.Reassembler();
        assertThrows(FrameCodec.TooLargeException.class, () -> {
            for (int i = 0; i < 65; i++) {
                assertNull(r.feed(FrameCodec.FLAG_MORE, new byte[1]));
            }
        });
    }

    private static SecureChannel[] pair() {
        byte[] k1 = new byte[32];
        byte[] k2 = new byte[32];
        k2[0] = 1;
        SecureChannel a = new SecureChannel(new CipherState(k1), new CipherState(k2), 3, 3600, () -> 0L);
        SecureChannel b = new SecureChannel(new CipherState(k2), new CipherState(k1), 3, 3600, () -> 0L);
        return new SecureChannel[]{a, b};
    }

    @Test
    public void replayAndReorderAreIntegrityErrors() throws Exception {
        SecureChannel[] p = pair();
        byte[] f1 = p[0].seal("один").get(0);
        byte[] f2 = p[0].seal("два").get(0);
        assertThrows(SecureChannel.IntegrityException.class, () -> p[1].open(f2));
        SecureChannel[] q = pair();
        byte[] g1 = q[0].seal("один").get(0);
        q[1].open(g1);
        assertThrows(SecureChannel.IntegrityException.class, () -> q[1].open(g1));
        assertEquals(1, f1.length > 0 ? 1 : 0);
    }

    @Test
    public void rekeyByCountKeepsWorking() throws Exception {
        SecureChannel[] p = pair();
        for (int i = 0; i < 10; i++) {
            for (byte[] f : p[0].seal("m" + i)) {
                List<SecureChannel.Received> got = p[1].open(f);
                if (!got.isEmpty()) {
                    assertEquals("m" + i, new String(got.get(0).data));
                }
            }
        }
        assertEquals(p[0].rekeysOut(), p[1].rekeysIn());
        assertEquals(true, p[0].rekeysOut() >= 3);
    }

    @Test
    public void rekeyByTime() throws Exception {
        long[] now = {0};
        CipherState s = new CipherState(new byte[32]);
        CipherState r = new CipherState(new byte[32]);
        SecureChannel a = new SecureChannel(s, new CipherState(new byte[32]), 10000, 1, () -> now[0]);
        SecureChannel b = new SecureChannel(new CipherState(new byte[32]), r, 10000, 1, () -> now[0]);
        now[0] = 1500;
        List<byte[]> frames = a.seal("x");
        assertEquals(2, frames.size());
        b.open(frames.get(0));
        assertEquals("x", new String(b.open(frames.get(1)).get(0).data));
        assertEquals(1, b.rekeysIn());
    }

    @Test
    public void foreignFrameMidMessage() throws Exception {
        SecureChannel[] p = pair();
        List<byte[]> frames = p[0].seal(new byte[FrameCodec.MAX_CHUNK + 5]);
        p[1].open(frames.get(0));
        byte[] close = p[0].closeFrame(1000, "");
        assertThrows(SecureChannel.IntegrityException.class, () -> p[1].open(close));
    }

    @Test
    public void closeFrameCarriesCode() throws Exception {
        SecureChannel[] p = pair();
        List<SecureChannel.Received> got = p[1].open(p[0].closeFrame(4413, "big"));
        assertEquals(FrameCodec.CLOSE, got.get(0).inner);
        assertEquals(0x11, got.get(0).data[0] & 0xFF);
        assertEquals(0x3D, got.get(0).data[1] & 0xFF);
    }

    @Test
    public void backoffGrowsTo30s() {
        Backoff b = new Backoff(new Random(7));
        long first = b.nextDelayMs();
        assertEquals(true, first >= 1000 && first <= 1200);
        long last = 0;
        for (int i = 0; i < 10; i++) {
            last = b.nextDelayMs();
        }
        assertEquals(true, last <= 30_000 && last >= 24_000);
        b.reset();
        assertEquals(true, b.nextDelayMs() <= 1200);
    }
}
