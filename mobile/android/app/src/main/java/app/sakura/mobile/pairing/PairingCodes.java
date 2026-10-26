package app.sakura.mobile.pairing;

import java.io.UnsupportedEncodingException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

import app.sakura.mobile.crypto.noise.Primitives;

/**
 * Спаривание (PROTOCOL.md §3.4–3.5, §8.1): 8 слов → PSK, QR sakura-pair://1, отпечаток ключа.
 * Нормализация совпадает с серверной (securechannel/pairing.py): нижний регистр, ё → е,
 * всё, кроме [a-zа-я], — разделитель, слова через один пробел.
 */
public final class PairingCodes {
    public static final int WORDS = 8;
    private static final byte[] PSK_CONTEXT = "sakura-pair/1\u0000".getBytes(StandardCharsets.US_ASCII);

    public static final class PairingException extends Exception {
        public PairingException(String message) {
            super(message);
        }
    }

    /** Разобранный QR. Слова — уже нормализованные. */
    public static final class QrPayload {
        public final String url;
        public final byte[] serverPub;
        public final String words;
        public final long expires;

        QrPayload(String url, byte[] serverPub, String words, long expires) {
            this.url = url;
            this.serverPub = serverPub;
            this.words = words;
            this.expires = expires;
        }
    }

    private PairingCodes() {
    }

    private static boolean isWordChar(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'а' && c <= 'я');
    }

    public static String normalizeWords(String text) {
        String t = (text == null ? "" : text).toLowerCase(Locale.ROOT).replace('ё', 'е');
        StringBuilder out = new StringBuilder(t.length());
        boolean inWord = false;
        for (int i = 0; i < t.length(); i++) {
            char c = t.charAt(i);
            if (isWordChar(c)) {
                if (!inWord && out.length() > 0) {
                    out.append(' ');
                }
                out.append(c);
                inWord = true;
            } else {
                inWord = false;
            }
        }
        return out.toString();
    }

    public static int wordCount(String normalized) {
        return normalized.isEmpty() ? 0 : normalized.split(" ").length;
    }

    public static byte[] wordsToPsk(String words) throws PairingException {
        String norm = normalizeWords(words);
        if (wordCount(norm) != WORDS) {
            throw new PairingException("нужно ровно 8 слов");
        }
        return Primitives.blake2s(32, PSK_CONTEXT, norm.getBytes(StandardCharsets.UTF_8));
    }

    /** fingerprint(pub) = BLAKE2s(pub)[:8] hex группами по 4. */
    public static String fingerprint(byte[] pub) {
        byte[] h = Primitives.blake2s(32, pub);
        StringBuilder sb = new StringBuilder(19);
        for (int i = 0; i < 8; i++) {
            if (i > 0 && i % 2 == 0) {
                sb.append(' ');
            }
            sb.append(String.format(Locale.ROOT, "%02x", h[i] & 0xFF));
        }
        return sb.toString();
    }

    public static String b64url(byte[] data) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(data);
    }

    public static byte[] unb64url(String text) {
        return Base64.getUrlDecoder().decode(text.trim());
    }

    /** Разбор QR; nowSeconds — текущее время (unix) для проверки срока. */
    public static QrPayload parseQrUri(String uri, long nowSeconds) throws PairingException {
        String s = uri == null ? "" : uri.trim();
        String prefix = "sakura-pair://1?";
        if (!s.startsWith(prefix)) {
            throw new PairingException("это не QR спаривания Сакуры");
        }
        Map<String, String> q = new HashMap<>();
        for (String part : s.substring(prefix.length()).split("&")) {
            int eq = part.indexOf('=');
            if (eq <= 0) {
                throw new PairingException("в QR не хватает данных");
            }
            String k = part.substring(0, eq);
            if (!q.containsKey(k)) {
                q.put(k, decode(part.substring(eq + 1)));
            }
        }
        String u = q.get("u");
        String k = q.get("k");
        String w = q.get("w");
        String e = q.get("e");
        if (u == null || k == null || w == null || e == null || u.isEmpty()) {
            throw new PairingException("в QR не хватает данных");
        }
        if (!(u.startsWith("ws://") || u.startsWith("wss://"))) {
            throw new PairingException("в QR неверный адрес сервера");
        }
        byte[] key;
        long expires;
        try {
            key = unb64url(k);
            expires = (long) Double.parseDouble(e);
        } catch (IllegalArgumentException ex) {
            throw new PairingException("в QR не хватает данных");
        }
        if (key.length != 32) {
            throw new PairingException("в QR неверный ключ сервера");
        }
        String words = normalizeWords(w.replace('-', ' '));
        if (wordCount(words) != WORDS) {
            throw new PairingException("в QR нужно 8 слов");
        }
        if (expires > 0 && nowSeconds > expires) {
            throw new PairingException("срок кода спаривания истёк — получите новый в Telegram (/pair)");
        }
        return new QrPayload(u, key, words, expires);
    }

    private static String decode(String v) throws PairingException {
        try {
            return URLDecoder.decode(v, "UTF-8");
        } catch (UnsupportedEncodingException | IllegalArgumentException e) {
            throw new PairingException("в QR не хватает данных");
        }
    }
}
