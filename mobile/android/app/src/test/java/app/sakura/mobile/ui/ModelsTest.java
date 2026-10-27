package app.sakura.mobile.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.ActionCatalog;
import app.sakura.mobile.ui.model.Models;
import app.sakura.mobile.ui.scenarios.ScenarioTypes;

public class ModelsTest {

    @Test
    public void messageLabels() {
        Models.Message m = Models.Message.of(Json.obj("id", "7", "ts", 1.0, "role", "user", "text", "x",
                "channel", "voice", "device", "pc"));
        assertTrue(m.fromMaster());
        assertEquals("голос · игровой", m.label());
        assertEquals("Telegram", Models.Message.of(Json.obj("channel", "telegram", "device", "telegram")).label());
        assertEquals("текст", Models.Message.of(Json.obj("channel", "text", "device", "")).label());
    }

    @Test
    public void exportFormat() {
        String out = Models.export(Arrays.asList(
                new Models.Message("1", 0, "user", "привет", "text", "phone", false),
                new Models.Message("2", 0, "assistant", "здравствуй", "text", "phone", false)));
        assertTrue(out.contains("] Вы: привет\n"));
        assertTrue(out.contains("] Sakura: здравствуй\n"));
    }

    @Test
    public void deviceWithTrackAndNulls() {
        Models.Device d = Models.Device.of(Json.obj("id", "pc", "kind", "pc", "online", true, "active", true,
                "stats", Json.obj("cpu", 12.4, "ram", JSONObject.NULL),
                "track", Json.obj("title", "Numb", "artist", "LP", "status", "играет", "cover_url", JSONObject.NULL)));
        assertTrue(d.isPc());
        assertEquals(Integer.valueOf(12), d.cpu);
        assertNull(d.ram);
        assertNull(d.gpu);
        assertTrue(d.track.playing());
        assertNull(d.track.coverUrl);
        Models.Device phone = Models.Device.of(Json.obj("id", "phone", "kind", "phone", "track", JSONObject.NULL,
                "stats", Json.obj("battery", 78, "charging", true)));
        assertNull(phone.track);
        assertEquals(Integer.valueOf(78), phone.battery);
        assertTrue(phone.charging);
        assertEquals("телефон", phone.name);
    }

    @Test
    public void scenarioRoundTripAndSummary() {
        Models.Scenario s = new Models.Scenario(null, "Режим сна", true, false,
                Arrays.asList(new Models.Step("time", "22:00-07:00")),
                Arrays.asList(new Models.Step("action", "phone.dnd_on"), new Models.Step("notify", "спокойной ночи")));
        JSONObject j = s.json();
        assertFalse(j.has("id"));
        Models.Scenario back = Models.Scenario.of(j);
        assertEquals("phone.dnd_on", back.actions.get(0).value);
        assertEquals("Если время: 22:00-07:00 → Действие: phone.dnd_on, Уведомление: спокойной ночи",
                ScenarioTypes.summary(back));
        assertEquals(5, ScenarioTypes.CONDITION_IDS.length);
        assertEquals(4, ScenarioTypes.ACTION_IDS.length);
    }

    @Test
    public void loadableStates() {
        assertEquals(Loadable.Status.OFFLINE, Loadable.failed(new ApiError("offline", "")).status);
        Loadable<Object> un = Loadable.failed(new ApiError("unsupported", ""));
        assertEquals(Loadable.Status.ERROR, un.status);
        assertEquals("Сервер ещё не поддерживает сценарии", un.errorText("сценарии"));
        assertFalse(un.retryable());
        Loadable<Object> sec = Loadable.failed(new ApiError("secure_channel_required", "нужен защищённый канал"));
        assertEquals(ErrorText.SECURE_REQUIRED, sec.errorText("память"));
        Loadable<Object> nm = Loadable.failed(new ApiError("not_master", "memory_list: только для master-устройств"));
        assertEquals("memory_list: только для master-устройств", nm.errorText("память"));
        assertEquals(ErrorText.OFFLINE, Loadable.offline().errorText(null));
    }

    @Test
    public void catalogFromGeneratedAsset() throws Exception {
        File f = new File("src/main/assets/phone_triggers.json");
        if (!f.isFile()) {
            f = new File("app/" + f.getPath());
        }
        ActionCatalog c = ActionCatalog.parse(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
        assertTrue(c.actions.size() > 100);
        assertNotNull(c.find("music.wave"));
        assertNotNull(c.find("phone.dnd_on"));
        assertEquals("time", c.find("phone.alarm").params.get(0));
        for (int i = 1; i < c.triggers.size(); i++) {
            assertTrue("самый длинный первым", c.triggers.get(i - 1).phrase.length() >= c.triggers.get(i).phrase.length());
        }
        for (ActionCatalog.Trigger t : c.triggers) {
            assertTrue(t.action.startsWith("phone."));
        }
    }
}
