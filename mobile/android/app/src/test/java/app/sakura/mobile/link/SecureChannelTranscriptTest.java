package app.sakura.mobile.link;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.util.ArrayList;
import java.util.List;

import app.sakura.mobile.crypto.noise.CipherState;
import app.sakura.mobile.crypto.noise.HandshakeState;
import app.sakura.mobile.pairing.PairingCodes;
import app.sakura.mobile.testutil.Hex;

/**
 * Побайтная сверка с серверным securechannel (tools/gen_sc_transcripts.py → sc_transcripts.json):
 * рукопожатия IK и XXpsk3, 3 сообщения, фрагмент > 64 КБ, rekey.
 */
public class SecureChannelTranscriptTest {

    private static List<String> hexList(JSONArray a) throws Exception {
        List<String> out = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) {
            out.add(a.getString(i));
        }
        return out;
    }

    private static List<String> hexOf(List<byte[]> frames) {
        List<String> out = new ArrayList<>();
        for (byte[] f : frames) {
            out.add(Hex.encode(f));
        }
        return out;
    }

    private static byte[] body(String frameHex) throws Exception {
        return FrameCodec.decodeFrame(Hex.decode(frameHex)).body;
    }

    /** Транспорт: свои кадры совпадают с эталоном, чужие открываются. */
    private static void checkTransport(JSONArray transport, SecureChannel client, SecureChannel server)
            throws Exception {
        for (int i = 0; i < transport.length(); i++) {
            JSONObject t = transport.getJSONObject(i);
            byte[] msg = Hex.decode(t.getString("message_hex"));
            boolean c2s = "c2s".equals(t.getString("dir"));
            SecureChannel sender = c2s ? client : server;
            SecureChannel receiver = c2s ? server : client;
            List<String> expected = hexList(t.getJSONArray("frames_hex"));
            assertEquals("кадры " + i, expected, hexOf(sender.seal(msg)));
            List<SecureChannel.Received> got = new ArrayList<>();
            for (String f : expected) {
                got.addAll(receiver.open(Hex.decode(f)));
            }
            assertEquals(1, got.size());
            assertEquals(FrameCodec.DATA, got.get(0).inner);
            assertArrayEquals(msg, got.get(0).data);
            if (msg.length > 65536) {
                assertTrue("фрагментация", expected.size() >= 2);
            }
        }
    }

    private void ik(JSONObject t) throws Exception {
        byte[] sPriv = Hex.decode(t.getString("server_static"));
        byte[] sPub = Hex.decode(t.getString("server_pub"));
        assertEquals(t.getString("server_fp"), PairingCodes.fingerprint(sPub));
        HandshakeState init = new HandshakeState(HandshakeState.Pattern.IK, true, SecureLink.PROLOGUE_SESSION,
                Hex.decode(t.getString("client_static")), sPub, null, Hex.decode(t.getString("client_ephemeral")));
        HandshakeState resp = new HandshakeState(HandshakeState.Pattern.IK, false, SecureLink.PROLOGUE_SESSION,
                sPriv, null, null, Hex.decode(t.getString("server_ephemeral")));
        byte[] m1 = init.writeMessage(Hex.decode(t.getString("payload1_hex")));
        assertEquals(t.getString("frame1_hex"), Hex.encode(FrameCodec.encodeFrame(FrameCodec.IK_INIT, m1)));
        resp.readMessage(m1);
        byte[] m2 = resp.writeMessage(Hex.decode(t.getString("payload2_hex")));
        assertEquals(t.getString("frame2_hex"), Hex.encode(FrameCodec.encodeFrame(FrameCodec.IK_RESP, m2)));
        assertArrayEquals(Hex.decode(t.getString("payload2_hex")), init.readMessage(body(t.getString("frame2_hex"))));
        assertEquals(t.getString("handshake_hash"), Hex.encode(init.handshakeHash()));
        CipherState[] c = init.split();
        CipherState[] s = resp.split();
        long rk = t.getLong("rekey_messages");
        SecureChannel client = new SecureChannel(c[0], c[1], rk, 3600, () -> 1000L);
        SecureChannel server = new SecureChannel(s[0], s[1], rk, 3600, () -> 1000L);
        checkTransport(t.getJSONArray("transport"), client, server);
        if (rk == 2) {
            assertTrue("rekey выполнен", client.rekeysOut() > 0 && server.rekeysIn() > 0);
        }
    }

    private void xx(JSONObject t) throws Exception {
        byte[] psk = PairingCodes.wordsToPsk(t.getString("words"));
        assertEquals(t.getString("psk"), Hex.encode(psk));
        HandshakeState init = new HandshakeState(HandshakeState.Pattern.XXPSK3, true, SecureLink.PROLOGUE_PAIR,
                Hex.decode(t.getString("client_static")), null, psk, Hex.decode(t.getString("client_ephemeral")));
        HandshakeState resp = new HandshakeState(HandshakeState.Pattern.XXPSK3, false, SecureLink.PROLOGUE_PAIR,
                Hex.decode(t.getString("server_static")), null, psk, Hex.decode(t.getString("server_ephemeral")));
        byte[] m1 = init.writeMessage(new byte[0]);
        assertEquals(t.getString("frame1_hex"), Hex.encode(FrameCodec.encodeFrame(FrameCodec.XX_1, m1)));
        resp.readMessage(m1);
        byte[] m2 = resp.writeMessage(new byte[0]);
        assertEquals(t.getString("frame2_hex"), Hex.encode(FrameCodec.encodeFrame(FrameCodec.XX_2, m2)));
        init.readMessage(body(t.getString("frame2_hex")));
        assertArrayEquals(Hex.decode(t.getString("server_pub")), init.remoteStatic());
        byte[] m3 = init.writeMessage(Hex.decode(t.getString("payload3_hex")));
        assertEquals(t.getString("frame3_hex"), Hex.encode(FrameCodec.encodeFrame(FrameCodec.XX_3, m3)));
        resp.readMessage(m3);
        assertEquals(t.getString("handshake_hash"), Hex.encode(init.handshakeHash()));
        CipherState[] c = init.split();
        SecureChannel client = new SecureChannel(c[0], c[1], 10000, 3600, () -> 1000L);
        List<SecureChannel.Received> paired = new ArrayList<>();
        for (String f : hexList(t.getJSONArray("paired_frames_hex"))) {
            paired.addAll(client.open(Hex.decode(f)));
        }
        assertEquals(1, paired.size());
        assertEquals(FrameCodec.PAIRED, paired.get(0).inner);
        assertArrayEquals(Hex.decode(t.getString("paired_hex")), paired.get(0).data);
        checkTransportClientOnly(t.getJSONArray("transport"), client);
    }

    /** XX: эталонные кадры сервера уже сдвинуты кадром PAIRED; проверяем клиентскую сторону. */
    private static void checkTransportClientOnly(JSONArray transport, SecureChannel client) throws Exception {
        for (int i = 0; i < transport.length(); i++) {
            JSONObject t = transport.getJSONObject(i);
            byte[] msg = Hex.decode(t.getString("message_hex"));
            List<String> expected = hexList(t.getJSONArray("frames_hex"));
            if ("c2s".equals(t.getString("dir"))) {
                assertEquals("кадры " + i, expected, hexOf(client.seal(msg)));
            } else {
                List<SecureChannel.Received> got = new ArrayList<>();
                for (String f : expected) {
                    got.addAll(client.open(Hex.decode(f)));
                }
                assertArrayEquals(msg, got.get(0).data);
            }
        }
    }

    @Test
    public void transcriptsMatchServerBytes() throws Exception {
        JSONArray ts = Hex.resourceJson("sc_transcripts.json").getJSONArray("transcripts");
        assertEquals(3, ts.length());
        for (int i = 0; i < ts.length(); i++) {
            JSONObject t = ts.getJSONObject(i);
            if ("IK".equals(t.getString("pattern"))) {
                ik(t);
            } else {
                xx(t);
            }
        }
    }
}
