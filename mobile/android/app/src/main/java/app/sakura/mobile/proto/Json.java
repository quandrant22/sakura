package app.sakura.mobile.proto;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Короткие помощники org.json без проверяемых исключений. */
public final class Json {
    private Json() {
    }

    /** obj("type", "ping", "n", 1) — пары ключ/значение; null-значения пропускаются. */
    public static JSONObject obj(Object... kv) {
        JSONObject o = new JSONObject();
        for (int i = 0; i + 1 < kv.length; i += 2) {
            put(o, (String) kv[i], kv[i + 1]);
        }
        return o;
    }

    public static JSONObject put(JSONObject o, String key, Object value) {
        if (value == null) {
            return o;
        }
        try {
            o.put(key, value);
        } catch (JSONException e) {
            throw new IllegalArgumentException(key);
        }
        return o;
    }

    public static JSONObject parse(String text) {
        try {
            return new JSONObject(text);
        } catch (JSONException e) {
            return null;
        }
    }

    public static JSONArray arr(Object... items) {
        JSONArray a = new JSONArray();
        for (Object x : items) {
            a.put(x);
        }
        return a;
    }

    /** null или JSONObject.NULL → null. */
    public static JSONObject optObj(JSONObject o, String key) {
        Object v = o.opt(key);
        return v instanceof JSONObject ? (JSONObject) v : null;
    }

    public static JSONArray optArr(JSONObject o, String key) {
        Object v = o.opt(key);
        return v instanceof JSONArray ? (JSONArray) v : new JSONArray();
    }

    /** Строка или null (JSON null, отсутствие). */
    public static String optStr(JSONObject o, String key) {
        Object v = o.opt(key);
        return v instanceof String ? (String) v : null;
    }

    public static JSONObject at(JSONArray a, int i) {
        Object v = a.opt(i);
        return v instanceof JSONObject ? (JSONObject) v : null;
    }
}
