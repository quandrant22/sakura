package app.sakura.mobile.voice;

/**
 * Дослушивание: после вопроса Сакуры (reply kind:"confirm", текст на «?» или tts_end.listen)
 * микрофон открывается на окно 0–15 с (по умолчанию 6) без слова «Сакура».
 */
public final class FollowUp {
    public static final int DEFAULT_S = 6;
    public static final int MAX_S = 15;

    private FollowUp() {
    }

    public static boolean isQuestion(String kind, String text) {
        if ("confirm".equals(kind)) {
            return true;
        }
        if (text == null) {
            return false;
        }
        String t = text.trim();
        while (!t.isEmpty() && (t.endsWith("»") || t.endsWith("\"") || t.endsWith(")"))) {
            t = t.substring(0, t.length() - 1).trim();
        }
        return t.endsWith("?");
    }

    /** Окно в мс; 0 — дослушивание выключено. */
    public static long windowMs(int seconds) {
        return Math.max(0, Math.min(MAX_S, seconds)) * 1000L;
    }

    /** «Да»/«нет» для вопроса kind:"confirm" — шлётся с channel:"text" (контракт). */
    public static String confirmWord(boolean yes) {
        return yes ? "да" : "нет";
    }
}
