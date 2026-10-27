package app.sakura.mobile.ui.model;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import app.sakura.mobile.proto.Json;

/** Действия реестра (assets/phone_triggers.json от tools/gen_phone_triggers.py): id, описание, параметры. */
public final class ActionCatalog {

    public static final class Action {
        public final String id;
        public final String desc;
        public final List<String> params;

        public Action(String id, String desc, List<String> params) {
            this.id = id;
            this.desc = desc;
            this.params = params;
        }

        /** Подпись в списке конструктора. */
        @Override
        public String toString() {
            return desc.isEmpty() ? id : desc + " (" + id + ")";
        }
    }

    public static final class Trigger {
        public final String phrase;
        public final String action;

        public Trigger(String phrase, String action) {
            this.phrase = phrase;
            this.action = action;
        }
    }

    private static volatile ActionCatalog instance;

    public final List<Action> actions;
    /** Триггеры phone.*, самый длинный первым. */
    public final List<Trigger> triggers;

    ActionCatalog(List<Action> actions, List<Trigger> triggers) {
        this.actions = Collections.unmodifiableList(actions);
        this.triggers = Collections.unmodifiableList(triggers);
    }

    public static ActionCatalog parse(String json) {
        JSONObject o = Json.parse(json);
        List<Action> actions = new ArrayList<>();
        List<Trigger> triggers = new ArrayList<>();
        if (o != null) {
            JSONArray a = Json.optArr(o, "actions");
            for (int i = 0; i < a.length(); i++) {
                JSONObject x = Json.at(a, i);
                if (x == null) {
                    continue;
                }
                List<String> params = new ArrayList<>();
                JSONArray p = Json.optArr(x, "params");
                for (int j = 0; j < p.length(); j++) {
                    params.add(p.optString(j));
                }
                actions.add(new Action(x.optString("id"), x.optString("desc"), params));
            }
            JSONArray t = Json.optArr(o, "triggers");
            for (int i = 0; i < t.length(); i++) {
                JSONObject x = Json.at(t, i);
                if (x != null) {
                    triggers.add(new Trigger(x.optString("trigger"), x.optString("action")));
                }
            }
        }
        return new ActionCatalog(actions, triggers);
    }

    public static ActionCatalog get(Context context) {
        if (instance == null) {
            synchronized (ActionCatalog.class) {
                if (instance == null) {
                    String text = "{}";
                    try (InputStream in = context.getAssets().open("phone_triggers.json")) {
                        text = new String(in.readAllBytes(), StandardCharsets.UTF_8);
                    } catch (IOException ignored) {
                        // каталог пуст — конструктор принимает id вручную
                    }
                    instance = parse(text);
                }
            }
        }
        return instance;
    }

    public Action find(String id) {
        for (Action a : actions) {
            if (a.id.equals(id)) {
                return a;
            }
        }
        return null;
    }
}
