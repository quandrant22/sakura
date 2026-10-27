package app.sakura.mobile.exec;

import java.util.List;
import java.util.Locale;

/** Нечёткий поиск приложения по названию (open_app): точное → начало → вхождение → расстояние правки. */
public final class AppMatcher {
    private AppMatcher() {
    }

    static String norm(String s) {
        return s == null ? "" : s.toLowerCase(Locale.ROOT).replace('ё', 'е').replaceAll("[^\\p{L}\\p{N}]+", " ").trim();
    }

    /** Расстояние Левенштейна. */
    static int distance(String a, String b) {
        int[] prev = new int[b.length() + 1];
        int[] cur = new int[b.length() + 1];
        for (int j = 0; j <= b.length(); j++) {
            prev[j] = j;
        }
        for (int i = 1; i <= a.length(); i++) {
            cur[0] = i;
            for (int j = 1; j <= b.length(); j++) {
                int c = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                cur[j] = Math.min(Math.min(cur[j - 1] + 1, prev[j] + 1), prev[j - 1] + c);
            }
            int[] t = prev;
            prev = cur;
            cur = t;
        }
        return prev[b.length()];
    }

    /** Чем меньше, тем лучше; Integer.MAX_VALUE — не подходит. */
    static int score(String query, String label) {
        String q = norm(query);
        String l = norm(label);
        if (q.isEmpty() || l.isEmpty()) {
            return Integer.MAX_VALUE;
        }
        if (q.equals(l)) {
            return 0;
        }
        if (l.startsWith(q)) {
            return 1;
        }
        if ((" " + l + " ").contains(" " + q + " ")) {
            return 2;
        }
        if (l.contains(q)) {
            return 3;
        }
        int d = distance(q, l.length() > q.length() + 2 ? l.substring(0, q.length()) : l);
        int limit = Math.max(1, q.length() / 4);
        return d <= limit ? 10 + d : Integer.MAX_VALUE;
    }

    public static PhoneApis.App best(String query, List<PhoneApis.App> apps) {
        PhoneApis.App best = null;
        int bestScore = Integer.MAX_VALUE;
        for (PhoneApis.App a : apps) {
            int s = score(query, a.label);
            if (s < bestScore || (s == bestScore && best != null && a.label.length() < best.label.length())) {
                best = a;
                bestScore = s;
            }
        }
        return bestScore == Integer.MAX_VALUE ? null : best;
    }
}
