package app.sakura.mobile.pairing;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

import app.sakura.mobile.testutil.Hex;

public class PairingCodesTest {
    private static final String WORDS = "лес кот мост река гора снег дом сад";

    @Test
    public void normalization() {
        assertEquals(WORDS, PairingCodes.normalizeWords("  ЛЕС, кот—мост\nрека 1 гора_снег; дом!!сад "));
        assertEquals("еж елка", PairingCodes.normalizeWords("Ёж ЁЛКА"));
        assertEquals("abc где", PairingCodes.normalizeWords("abc9где"));
        assertEquals("", PairingCodes.normalizeWords(null));
    }

    @Test
    public void pskMatchesServerTranscript() throws Exception {
        String expected = Hex.resourceJson("sc_transcripts.json").getJSONArray("transcripts")
                .getJSONObject(2).getString("psk");
        assertEquals(expected, Hex.encode(PairingCodes.wordsToPsk(WORDS)));
        assertEquals(expected, Hex.encode(PairingCodes.wordsToPsk("Лес-Кот-Мост-Река-Гора-Снег-Дом-Сад")));
    }

    @Test
    public void wordCountEnforced() {
        assertThrows(PairingCodes.PairingException.class, () -> PairingCodes.wordsToPsk("лес кот"));
    }

    @Test
    public void fingerprintFormat() throws Exception {
        org.json.JSONObject t = Hex.resourceJson("sc_transcripts.json").getJSONArray("transcripts").getJSONObject(0);
        assertEquals(t.getString("server_fp"), PairingCodes.fingerprint(Hex.decode(t.getString("server_pub"))));
        assertEquals(19, t.getString("server_fp").length());
    }

    private static String uri(String u, byte[] key, String w, long e) {
        return "sakura-pair://1?u=" + URLEncoder.encode(u, StandardCharsets.UTF_8) + "&k=" + PairingCodes.b64url(key)
                + "&w=" + URLEncoder.encode(w, StandardCharsets.UTF_8) + "&e=" + e;
    }

    @Test
    public void qrParse() throws Exception {
        byte[] key = new byte[32];
        key[5] = 9;
        PairingCodes.QrPayload q = PairingCodes.parseQrUri(
                uri("ws://31.76.80.5:8765", key, "лес-кот-мост-река-гора-снег-дом-сад", 2000), 1000);
        assertEquals("ws://31.76.80.5:8765", q.url);
        assertArrayEquals(key, q.serverPub);
        assertEquals(WORDS, q.words);
        assertEquals(2000, q.expires);
    }

    @Test
    public void qrRejects() {
        byte[] key = new byte[32];
        String w = "лес-кот-мост-река-гора-снег-дом-сад";
        assertThrows(PairingCodes.PairingException.class,
                () -> PairingCodes.parseQrUri(uri("ws://h:1", key, w, 1000), 1001));          // срок
        assertThrows(PairingCodes.PairingException.class,
                () -> PairingCodes.parseQrUri(uri("ws://h:1", new byte[31], w, 2000), 1000)); // ключ
        assertThrows(PairingCodes.PairingException.class,
                () -> PairingCodes.parseQrUri(uri("ws://h:1", key, "лес-кот", 2000), 1000));  // слова
        assertThrows(PairingCodes.PairingException.class,
                () -> PairingCodes.parseQrUri(uri("http://h:1", key, w, 2000), 1000));       // схема url
        assertThrows(PairingCodes.PairingException.class,
                () -> PairingCodes.parseQrUri("https://example.com", 0));
        assertThrows(PairingCodes.PairingException.class,
                () -> PairingCodes.parseQrUri("sakura-pair://1?u=ws%3A%2F%2Fh&w=x", 0));
    }
}
