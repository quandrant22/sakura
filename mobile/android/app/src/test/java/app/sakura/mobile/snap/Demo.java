package app.sakura.mobile.snap;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.Models;
import app.sakura.mobile.ui.summary.SummaryScreen;

/** Демо-данные снимков (без связи). */
final class Demo {
    enum Kind { NORMAL, EMPTY, OFFLINE, ERROR }

    static final double T = 1791900000.0;

    private Demo() {
    }

    static <T> Loadable<T> of(Kind k, T data) {
        switch (k) {
            case EMPTY:
                return Loadable.empty();
            case OFFLINE:
                return Loadable.offline();
            case ERROR:
                return Loadable.failed(new ApiError(ApiError.TIMEOUT, ""));
            default:
                return Loadable.ready(data);
        }
    }

    static List<Models.Message> messages() {
        return Arrays.asList(
                new Models.Message("1", T, "user", "Сакура, что у меня сегодня?", "voice", "phone", false),
                new Models.Message("2", T + 3, "assistant", "Созвон в 11:00 и спортзал вечером. Напомнить за час?",
                        "voice", "phone", false),
                new Models.Message("3", T + 20, "user", "Да, и включи музыку на компе", "text", "phone", false),
                new Models.Message("4", T + 22, "assistant", "Включаю «Мою волну» на игровом.", "text", "pc", false),
                new Models.Message("5", T + 60, "user", "Сделай потише", "telegram", "telegram", true));
    }

    static List<Models.Device> devices() {
        JSONObject track = Json.obj("title", "Numb", "artist", "Linkin Park", "status", "играет",
                "cover_url", JSONObject.NULL, "ts", T);
        return Arrays.asList(
                Models.Device.of(Json.obj("id", "pc", "name", "Игровой", "kind", "pc", "online", true, "active", true,
                        "track", track, "stats", Json.obj("cpu", 23, "ram", 61, "gpu", 47))),
                Models.Device.of(Json.obj("id", "mostech", "name", "Рабочий ноутбук", "kind", "laptop", "online", true,
                        "active", false, "stats", Json.obj("cpu", 8, "ram", 44))),
                Models.Device.of(Json.obj("id", "laptop", "name", "Ноутбук", "kind", "laptop", "online", false)),
                Models.Device.of(Json.obj("id", "phone", "name", "Телефон", "kind", "phone", "online", true,
                        "stats", Json.obj("battery", 78, "charging", true, "wifi", "wifi", "signal", 3))));
    }

    static SummaryScreen.Data summary() {
        SummaryScreen.Data d = new SummaryScreen.Data();
        d.status = new SummaryScreen.Status("обычный", "спокойный", "Тишина — тоже ответ.");
        d.devices = new ArrayList<>(devices());
        d.events = new ArrayList<>(Arrays.asList("готово: Режим сна", "шаг 2: Не беспокоить на телефоне"));
        d.replies = new ArrayList<>(Arrays.asList(messages().get(3), messages().get(1)));
        return d;
    }

    static List<Models.Scenario> scenarios() {
        return Arrays.asList(
                new Models.Scenario("sleep", "Режим сна", true, false,
                        Arrays.asList(new Models.Step("time", "22:00-07:00")),
                        Arrays.asList(new Models.Step("action", "phone.dnd_on"), new Models.Step("action", "system.lock"))),
                new Models.Scenario("focus", "Фокус", true, true,
                        Arrays.asList(new Models.Step("phrase", "режим фокуса")),
                        Arrays.asList(new Models.Step("action", "game_mode.off"), new Models.Step("notify", "Работаем"))));
    }

    static List<Models.MemoryItem> memory() {
        return Arrays.asList(
                new Models.MemoryItem("k1", "preferences", "Любит «Мою волну» по вечерам"),
                new Models.MemoryItem("k2", "facts", "Работает на ноутбуке mostech"),
                new Models.MemoryItem("k3", "bookmarks", "Статья про Noise IK"));
    }

    static Map<String, Integer> counts() {
        Map<String, Integer> m = new LinkedHashMap<>();
        m.put("preferences", 12);
        m.put("facts", 30);
        m.put("bookmarks", 4);
        return m;
    }

    static JSONObject profile() {
        return Json.obj("name", "Мастер", "address_as", "ты", "quiet_hours", "23:00-07:00", "voice", "Leda",
                "tone", "calm", "notifications", Json.obj("telegram", true, "sound", false));
    }

    static List<Models.SecureDevice> secureDevices() {
        return Arrays.asList(
                Models.SecureDevice.of(Json.obj("device_id", "phone", "name", "Телефон", "fingerprint", "3f9a1c0277de0b41",
                        "online", true, "secure_now", true, "revoked", false, "current", true)),
                Models.SecureDevice.of(Json.obj("device_id", "mostech", "name", "Рабочий ноутбук",
                        "fingerprint", "9b01aa4e6c3d2f10", "online", false, "secure_now", false, "revoked", false,
                        "current", false)));
    }
}
