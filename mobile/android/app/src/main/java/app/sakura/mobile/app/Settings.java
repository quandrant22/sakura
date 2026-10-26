package app.sakura.mobile.app;

import android.content.Context;
import android.content.SharedPreferences;

/** Локальные настройки (SharedPreferences, бэкап запрещён манифестом). */
public final class Settings {
    public static final String ALWAYS_ON = "always_on";
    public static final String TEXT_REPLIES = "text_replies";
    public static final String FOLLOWUP_S = "followup_s";
    public static final String WAKE_WORD = "wake_word";
    public static final String THEME = "theme";
    public static final String MOBILITY = "mobility";
    public static final String MERGE_PRESET = "merge_preset";
    public static final String REDUCE_MOTION = "reduce_motion";
    public static final String FLOATING_CORE = "floating_core";
    public static final String WIDGET_ACTIONS = "widget_actions";

    public static final String THEME_NIGHT = "night";
    public static final String THEME_SKETCH = "sketch";

    private final SharedPreferences prefs;

    public Settings(Context context) {
        prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE);
    }

    public SharedPreferences prefs() {
        return prefs;
    }

    public boolean alwaysOn() {
        return prefs.getBoolean(ALWAYS_ON, false);
    }

    public void setAlwaysOn(boolean on) {
        prefs.edit().putBoolean(ALWAYS_ON, on).apply();
    }

    public boolean textReplies() {
        return prefs.getBoolean(TEXT_REPLIES, false);
    }

    public void setTextReplies(boolean on) {
        prefs.edit().putBoolean(TEXT_REPLIES, on).apply();
    }

    /** Окно дослушивания, 0–15 с (по умолчанию 6). */
    public int followupSeconds() {
        return Math.max(0, Math.min(15, prefs.getInt(FOLLOWUP_S, 6)));
    }

    public void setFollowupSeconds(int s) {
        prefs.edit().putInt(FOLLOWUP_S, Math.max(0, Math.min(15, s))).apply();
    }

    public boolean wakeWord() {
        return prefs.getBoolean(WAKE_WORD, false);
    }

    public void setWakeWord(boolean on) {
        prefs.edit().putBoolean(WAKE_WORD, on).apply();
    }

    public String theme() {
        return prefs.getString(THEME, THEME_NIGHT);
    }

    public void setTheme(String theme) {
        prefs.edit().putString(THEME, theme).apply();
    }

    public String mobility() {
        return prefs.getString(MOBILITY, "normal");
    }

    public void setMobility(String m) {
        prefs.edit().putString(MOBILITY, m).apply();
    }

    public String mergePreset() {
        return prefs.getString(MERGE_PRESET, "normal");
    }

    public void setMergePreset(String p) {
        prefs.edit().putString(MERGE_PRESET, p).apply();
    }

    public boolean reduceMotion() {
        return prefs.getBoolean(REDUCE_MOTION, false);
    }

    public void setReduceMotion(boolean on) {
        prefs.edit().putBoolean(REDUCE_MOTION, on).apply();
    }

    public boolean floatingCore() {
        return prefs.getBoolean(FLOATING_CORE, false);
    }

    public void setFloatingCore(boolean on) {
        prefs.edit().putBoolean(FLOATING_CORE, on).apply();
    }

    /** Три действия виджета через запятую (action_run). */
    public String widgetActions() {
        return prefs.getString(WIDGET_ACTIONS, "music.play_pause,music.next,kettle.on");
    }

    public void setWidgetActions(String csv) {
        prefs.edit().putString(WIDGET_ACTIONS, csv).apply();
    }

    public void clear() {
        prefs.edit().clear().apply();
    }
}
