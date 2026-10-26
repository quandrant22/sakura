package app.sakura.mobile.crypto.noise;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import app.sakura.mobile.testutil.Hex;

/** Официальные векторы (cacophony, копия securechannel/vectors/noise_vectors.json). */
public class NoiseVectorsTest {

    private static byte[] opt(JSONObject v, String k) throws Exception {
        return v.has(k) ? Hex.decode(v.getString(k)) : null;
    }

    private void runVector(JSONObject v) throws Exception {
        String name = v.getString("protocol_name");
        HandshakeState.Pattern p = name.contains("XXpsk3") ? HandshakeState.Pattern.XXPSK3 : HandshakeState.Pattern.IK;
        assertEquals(name, p.protocolName());
        byte[] ipsk = v.has("init_psks") ? Hex.decode(v.getJSONArray("init_psks").getString(0)) : null;
        byte[] rpsk = v.has("resp_psks") ? Hex.decode(v.getJSONArray("resp_psks").getString(0)) : null;
        HandshakeState init = new HandshakeState(p, true, Hex.decode(v.getString("init_prologue")),
                opt(v, "init_static"), opt(v, "init_remote_static"), ipsk, opt(v, "init_ephemeral"));
        HandshakeState resp = new HandshakeState(p, false, Hex.decode(v.getString("resp_prologue")),
                opt(v, "resp_static"), null, rpsk, opt(v, "resp_ephemeral"));
        JSONArray msgs = v.getJSONArray("messages");
        int hsCount = p == HandshakeState.Pattern.IK ? 2 : 3;
        CipherState[] ic = null;
        CipherState[] rc = null;
        for (int i = 0; i < msgs.length(); i++) {
            byte[] payload = Hex.decode(msgs.getJSONObject(i).getString("payload"));
            byte[] expected = Hex.decode(msgs.getJSONObject(i).getString("ciphertext"));
            boolean fromInit = i % 2 == 0;
            if (i < hsCount) {
                HandshakeState w = fromInit ? init : resp;
                HandshakeState r = fromInit ? resp : init;
                byte[] ct = w.writeMessage(payload);
                assertArrayEquals(name + " msg " + i, expected, ct);
                assertArrayEquals(payload, r.readMessage(ct));
                if (i == hsCount - 1) {
                    assertTrue(init.isComplete() && resp.isComplete());
                    assertArrayEquals(Hex.decode(v.getString("handshake_hash")), init.handshakeHash());
                    assertArrayEquals(init.handshakeHash(), resp.handshakeHash());
                    ic = init.split();
                    rc = resp.split();
                }
            } else {
                CipherState send = fromInit ? ic[0] : rc[0];
                CipherState recv = fromInit ? rc[1] : ic[1];
                byte[] ct = send.encryptWithAd(new byte[0], payload);
                assertArrayEquals(name + " transport " + i, expected, ct);
                assertArrayEquals(payload, recv.decryptWithAd(new byte[0], ct));
            }
        }
    }

    @Test
    public void officialVectors() throws Exception {
        JSONArray vs = Hex.resourceJson("noise_vectors.json").getJSONArray("vectors");
        assertEquals(2, vs.length());
        for (int i = 0; i < vs.length(); i++) {
            runVector(vs.getJSONObject(i));
        }
    }

    @Test
    public void tamperedCiphertextFails() throws Exception {
        CipherState a = new CipherState(new byte[32]);
        CipherState b = new CipherState(new byte[32]);
        byte[] ct = a.encryptWithAd(new byte[0], "x".getBytes());
        ct[0] ^= 1;
        assertThrows(NoiseException.class, () -> b.decryptWithAd(new byte[0], ct));
    }

    @Test
    public void nonceExhausted() {
        CipherState a = new CipherState(new byte[32]);
        a.setNonce(CipherState.MAX_NONCE);
        assertThrows(NoiseException.class, () -> a.encryptWithAd(new byte[0], new byte[1]));
    }

    @Test
    public void rekeyBothSidesStayInSync() throws Exception {
        CipherState a = new CipherState(Hex.decode("01".repeat(32)));
        CipherState b = new CipherState(Hex.decode("01".repeat(32)));
        a.rekey();
        b.rekey();
        byte[] ct = a.encryptWithAd(new byte[0], "после rekey".getBytes());
        assertArrayEquals("после rekey".getBytes(), b.decryptWithAd(new byte[0], ct));
    }

    @Test
    public void lowOrderPointRejected() {
        byte[][] kp = Primitives.generateKeypair();
        assertThrows(NoiseException.class, () -> Primitives.dh(kp[0], new byte[32]));
    }

    @Test
    public void wrongTurnRejected() {
        HandshakeState hs = HandshakeState.ikInitiator(new byte[1], Primitives.generateKeypair()[0],
                Primitives.generateKeypair()[1]);
        assertThrows(NoiseException.class, () -> hs.readMessage(new byte[48]));
    }
}
