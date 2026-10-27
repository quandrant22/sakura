package app.sakura.mobile.ui.scenarios;

import java.util.List;

import app.sakura.mobile.ui.model.Models;

/** Типы условий и действий конструктора — как desktop/ui/src/components/ScenarioBuilder.tsx. */
public final class ScenarioTypes {
    public static final String[] CONDITION_IDS = {"phrase", "time", "device_connected", "device_disconnected", "app_started"};
    public static final String[] CONDITION_LABELS = {"Скажу фразу", "Время", "Устройство подключилось",
            "Устройство отключилось", "Запущено приложение"};
    public static final String[] ACTION_IDS = {"action", "pause", "telegram", "notify"};
    public static final String[] ACTION_LABELS = {"Действие", "Пауза", "Сообщение в Telegram", "Уведомление"};

    private ScenarioTypes() {
    }

    static String label(String[] ids, String[] labels, String id) {
        for (int i = 0; i < ids.length; i++) {
            if (ids[i].equals(id)) {
                return labels[i];
            }
        }
        return id;
    }

    public static String conditionLabel(String id) {
        return label(CONDITION_IDS, CONDITION_LABELS, id);
    }

    public static String actionLabel(String id) {
        return label(ACTION_IDS, ACTION_LABELS, id);
    }

    static int index(String[] ids, String id) {
        for (int i = 0; i < ids.length; i++) {
            if (ids[i].equals(id)) {
                return i;
            }
        }
        return 0;
    }

    /** «Если время: 22:00–07:00 → Действие: phone.dnd_on». */
    public static String summary(Models.Scenario s) {
        StringBuilder sb = new StringBuilder();
        append(sb, s.conditions, true);
        sb.append(" → ");
        append(sb, s.actions, false);
        return sb.toString();
    }

    private static void append(StringBuilder sb, List<Models.Step> steps, boolean cond) {
        for (int i = 0; i < steps.size(); i++) {
            Models.Step st = steps.get(i);
            if (i > 0) {
                sb.append(cond ? " и " : ", ");
            }
            String l = cond ? conditionLabel(st.type) : actionLabel(st.type);
            sb.append(cond && i == 0 ? "Если " + l.toLowerCase(java.util.Locale.ROOT) : l);
            if (!st.value.isEmpty()) {
                sb.append(": ").append(st.value);
            }
        }
        if (steps.isEmpty()) {
            sb.append(cond ? "без условий" : "без действий");
        }
    }
}
