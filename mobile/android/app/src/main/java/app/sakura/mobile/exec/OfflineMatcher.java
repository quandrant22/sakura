package app.sakura.mobile.exec;

import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import app.sakura.mobile.ui.model.ActionCatalog;

/**
 * Офлайн-путь: фраза без связи с сервером, совпавшая с триггером phone.*, выполняется на телефоне.
 * Правила реестра: только по границам слов, выигрывает самый длинный триггер. Аргумент извлекается из
 * фразы; если для действия нужен аргумент, а его нет — совпадения нет (фраза пойдёт серверу позже).
 */
public final class OfflineMatcher {

    public static final class Match {
        public final String action;
        public final Object arg;

        Match(String action, Object arg) {
            this.action = action;
            this.arg = arg;
        }
    }

    private static final Pattern TIME = Pattern.compile("(\\d{1,2})\\s*[:.\\s]\\s*(\\d{2})");
    private static final Pattern HOUR = Pattern.compile("на\\s+(\\d{1,2})(?:\\s*(час|часа|часов|утра|вечера))?");
    private static final Pattern DURATION = Pattern.compile("(\\d+)\\s*(секунд\\w*|сек|минут\\w*|мин|час\\w*)");
    private static final Pattern NUMBER = Pattern.compile("(\\d{1,3})");
    private static final Pattern URL = Pattern.compile("(https?://\\S+)");

    private final List<ActionCatalog.Trigger> triggers;

    public OfflineMatcher(List<ActionCatalog.Trigger> triggers) {
        this.triggers = triggers;
    }

    static String norm(String s) {
        return " " + (s == null ? "" : s).toLowerCase(Locale.ROOT).replace('ё', 'е')
                .replaceAll("[^\\p{L}\\p{N}:./]+", " ").replaceAll("\\s+", " ").trim() + " ";
    }

    public Match match(String phrase) {
        String text = norm(phrase);
        ActionCatalog.Trigger best = null;
        int at = -1;
        for (ActionCatalog.Trigger t : triggers) {
            String needle = " " + norm(t.phrase).trim() + " ";
            int i = text.indexOf(needle);
            if (i >= 0 && (best == null || t.phrase.length() > best.phrase.length())) {
                best = t;
                at = i + needle.length();
            }
        }
        if (best == null) {
            return null;
        }
        String rest = text.substring(Math.min(at, text.length())).trim();
        Object arg = arg(best.action, text, rest);
        if (arg == MISSING) {
            return null;
        }
        return new Match(best.action, arg);
    }

    private static final Object MISSING = new Object();

    static Object arg(String action, String text, String rest) {
        switch (action) {
            case "phone.alarm": {
                Matcher m = TIME.matcher(text);
                if (m.find()) {
                    return String.format(Locale.ROOT, "%02d:%s", Integer.parseInt(m.group(1)), m.group(2));
                }
                Matcher h = HOUR.matcher(text);
                if (h.find()) {
                    int hour = Integer.parseInt(h.group(1));
                    if ("вечера".equals(h.group(2)) && hour < 12) {
                        hour += 12;
                    }
                    return hour < 24 ? String.format(Locale.ROOT, "%02d:00", hour) : MISSING;
                }
                return MISSING;
            }
            case "phone.timer": {
                Matcher m = DURATION.matcher(text);
                if (!m.find()) {
                    return MISSING;
                }
                int n = Integer.parseInt(m.group(1));
                String unit = m.group(2);
                return unit.startsWith("час") ? n * 3600 : unit.startsWith("мин") ? n * 60 : n;
            }
            case "phone.flashlight":
                return text.contains(" выключ") || text.contains(" отключ") ? "off" : "on";
            case "phone.volume": {
                Matcher m = NUMBER.matcher(text);
                if (!m.find()) {
                    return MISSING;
                }
                int v = Integer.parseInt(m.group(1));
                return v <= 100 ? v : MISSING;
            }
            case "phone.open_url": {
                Matcher m = URL.matcher(text);
                return m.find() ? m.group(1) : MISSING;
            }
            case "phone.open_app":
            case "phone.clipboard":
            case "phone.notify":
                return rest.isEmpty() ? MISSING : rest;
            default:
                return null;
        }
    }
}
