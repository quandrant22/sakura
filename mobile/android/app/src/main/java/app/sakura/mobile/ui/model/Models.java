package app.sakura.mobile.ui.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

import app.sakura.mobile.proto.Json;

/** Типы протокола v2 (desktop/docs/PROTOCOL.md §1.5 + контракт телефона) и их разбор. */
public final class Models {
    private Models() {
    }

    public static final class Message {
        public final String id;
        public final double ts;
        public final String role;
        public final String text;
        public final String channel;
        public final String device;
        public final boolean pending;

        public Message(String id, double ts, String role, String text, String channel, String device, boolean pending) {
            this.id = id;
            this.ts = ts;
            this.role = role;
            this.text = text;
            this.channel = channel;
            this.device = device;
            this.pending = pending;
        }

        public static Message of(JSONObject o) {
            return new Message(o.optString("id"), o.optDouble("ts", 0), o.optString("role", "assistant"),
                    o.optString("text"), o.optString("channel", "text"), o.optString("device", ""), false);
        }

        public boolean fromMaster() {
            return "user".equals(role);
        }

        /** Метка «канал · устройство». */
        public String label() {
            String ch;
            switch (channel) {
                case "voice":
                    ch = "голос";
                    break;
                case "telegram":
                    ch = "Telegram";
                    break;
                default:
                    ch = "текст";
            }
            String dev = deviceName(device);
            return dev.isEmpty() || dev.equalsIgnoreCase(ch) ? ch : ch + " · " + dev;
        }
    }

    public static final class Track {
        public final String title;
        public final String artist;
        public final String status;
        public final String coverUrl;

        Track(String title, String artist, String status, String coverUrl) {
            this.title = title;
            this.artist = artist;
            this.status = status;
            this.coverUrl = coverUrl;
        }

        public boolean playing() {
            return "играет".equals(status) || "playing".equals(status);
        }

        static Track of(JSONObject o) {
            if (o == null) {
                return null;
            }
            return new Track(o.optString("title"), o.optString("artist"), o.optString("status"), Json.optStr(o, "cover_url"));
        }
    }

    public static final class Device {
        public final String id;
        public final String name;
        public final String kind;
        public final boolean online;
        public final boolean active;
        public final double lastSeen;
        public final Integer cpu;
        public final Integer ram;
        public final Integer gpu;
        public final Integer battery;
        public final boolean charging;
        public final Track track;

        Device(JSONObject o) {
            id = o.optString("id", o.optString("device_id"));
            name = o.optString("name", deviceName(id));
            kind = o.optString("kind", "other");
            online = o.optBoolean("online", false);
            active = o.optBoolean("active", false);
            lastSeen = o.optDouble("last_seen", 0);
            JSONObject s = Json.optObj(o, "stats");
            cpu = num(s, "cpu");
            ram = num(s, "ram");
            gpu = num(s, "gpu");
            battery = num(s, "battery");
            charging = s != null && s.optBoolean("charging", false);
            track = Track.of(Json.optObj(o, "track"));
        }

        public boolean isPc() {
            return "pc".equals(kind) || "laptop".equals(kind);
        }

        public static Device of(JSONObject o) {
            return new Device(o);
        }
    }

    private static Integer num(JSONObject o, String k) {
        if (o == null || o.isNull(k) || !o.has(k)) {
            return null;
        }
        double v = o.optDouble(k, Double.NaN);
        return Double.isNaN(v) ? null : (int) Math.round(v);
    }

    public static final class Step {
        public final String type;
        public final String value;

        public Step(String type, String value) {
            this.type = type;
            this.value = value;
        }

        JSONObject json() {
            return Json.obj("type", type, "value", value);
        }
    }

    public static final class Scenario {
        public final String id;
        public final String name;
        public final boolean enabled;
        public final boolean builtin;
        public final List<Step> conditions;
        public final List<Step> actions;

        public Scenario(String id, String name, boolean enabled, boolean builtin, List<Step> conditions, List<Step> actions) {
            this.id = id;
            this.name = name;
            this.enabled = enabled;
            this.builtin = builtin;
            this.conditions = conditions;
            this.actions = actions;
        }

        public static Scenario of(JSONObject o) {
            return new Scenario(Json.optStr(o, "id"), o.optString("name"), o.optBoolean("enabled", true),
                    o.optBoolean("builtin", false), steps(Json.optArr(o, "conditions")), steps(Json.optArr(o, "actions")));
        }

        public JSONObject json() {
            JSONArray c = new JSONArray();
            for (Step s : conditions) {
                c.put(s.json());
            }
            JSONArray a = new JSONArray();
            for (Step s : actions) {
                a.put(s.json());
            }
            JSONObject o = Json.obj("name", name, "enabled", enabled, "conditions", c, "actions", a);
            return id == null ? o : Json.put(o, "id", id);
        }
    }

    static List<Step> steps(JSONArray a) {
        List<Step> out = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = Json.at(a, i);
            if (o != null) {
                out.add(new Step(o.optString("type"), o.optString("value")));
            }
        }
        return out;
    }

    public static final class MemoryItem {
        public final String id;
        public final String category;
        public final String text;

        public MemoryItem(String id, String category, String text) {
            this.id = id;
            this.category = category;
            this.text = text;
        }

        public static MemoryItem of(JSONObject o) {
            return new MemoryItem(o.optString("id"), o.optString("category", "facts"), o.optString("text"));
        }
    }

    public static final class SecureDevice {
        public final String id;
        public final String name;
        public final String fingerprint;
        public final boolean online;
        public final boolean secureNow;
        public final boolean revoked;
        public final boolean current;

        SecureDevice(JSONObject o) {
            id = o.optString("device_id");
            name = o.optString("name", id);
            fingerprint = o.optString("fingerprint");
            online = o.optBoolean("online");
            secureNow = o.optBoolean("secure_now");
            revoked = o.optBoolean("revoked");
            current = o.optBoolean("current");
        }

        public static SecureDevice of(JSONObject o) {
            return new SecureDevice(o);
        }
    }

    public interface Parser<T> {
        T parse(JSONObject o);
    }

    public static <T> List<T> list(JSONArray a, Parser<T> p) {
        List<T> out = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = Json.at(a, i);
            if (o != null) {
                out.add(p.parse(o));
            }
        }
        return out;
    }

    /** Имя устройства для метки (KNOWN_DEVICES сервера; неизвестное — как есть). */
    public static String deviceName(String id) {
        if (id == null) {
            return "";
        }
        switch (id) {
            case "pc":
                return "игровой";
            case "laptop":
                return "ноутбук";
            case "mostech":
                return "рабочий";
            case "phone":
                return "телефон";
            case "telegram":
                return "Telegram";
            default:
                return id;
        }
    }

    public static String time(double ts) {
        return new SimpleDateFormat("HH:mm", Locale.ROOT).format(new Date((long) (ts * 1000)));
    }

    public static String dateTime(double ts) {
        return new SimpleDateFormat("dd.MM.yyyy HH:mm", Locale.ROOT).format(new Date((long) (ts * 1000)));
    }

    /** Текст переписки для экспорта через Share sheet (как экспорт десктопа). */
    public static String export(List<Message> messages) {
        StringBuilder sb = new StringBuilder();
        for (Message m : messages) {
            sb.append('[').append(dateTime(m.ts)).append("] ")
                    .append(m.fromMaster() ? "Вы" : "system".equals(m.role) ? "Система" : "Sakura")
                    .append(": ").append(m.text).append('\n');
        }
        return sb.toString();
    }
}
