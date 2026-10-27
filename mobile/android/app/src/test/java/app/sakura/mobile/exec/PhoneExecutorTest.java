package app.sakura.mobile.exec;

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

import app.sakura.mobile.proto.Json;
import app.sakura.mobile.ui.model.ActionCatalog;

public class PhoneExecutorTest {
    private final FakePhone phone = new FakePhone();
    private final PhoneExecutor ex = new PhoneExecutor(phone);

    private JSONObject cmd(String action, Object arg) {
        return ex.onCommand(Json.obj("type", "command", "id", "c1", "action", action, "arg", arg));
    }

    @Test
    public void resultFormat() throws Exception {
        JSONObject r = cmd("phone.find", null);
        assertEquals("command_result", r.getString("type"));
        assertEquals("c1", r.getString("id"));
        assertTrue(r.getBoolean("ok"));
        assertEquals("done", r.getString("status"));
        assertTrue(r.getString("detail").contains("30"));
        assertEquals("ring 30", phone.calls.get(0));
    }

    @Test
    public void everyContractAction() throws Exception {
        assertEquals("done", cmd("phone.dnd_on", null).getString("status"));
        assertEquals("done", cmd("phone.dnd_off", null).getString("status"));
        assertEquals("done", cmd("phone.alarm", "07:30").getString("status"));
        assertEquals("done", cmd("phone.timer", 300).getString("status"));
        assertEquals("done", cmd("phone.timer", "90").getString("status"));
        assertEquals("done", cmd("phone.flashlight", "on").getString("status"));
        assertEquals("done", cmd("phone.flashlight", "OFF").getString("status"));
        assertEquals("done", cmd("phone.volume", 40).getString("status"));
        assertEquals("done", cmd("phone.clipboard", "код 1234").getString("status"));
        assertEquals("done", cmd("phone.open_url", "https://ya.ru").getString("status"));
        assertEquals("done", cmd("phone.open_app", "телеграм").getString("status"));
        assertEquals("done", cmd("phone.media_play_pause", null).getString("status"));
        assertEquals("done", cmd("phone.media_next", null).getString("status"));
        assertEquals("done", cmd("phone.media_prev", null).getString("status"));
        assertEquals("done", cmd("phone.notify", "Чайник вскипел").getString("status"));
        assertTrue(phone.calls.contains("dnd true"));
        assertTrue(phone.calls.contains("alarm 7:30"));
        assertTrue(phone.calls.contains("timer 300"));
        assertTrue(phone.calls.contains("torch false"));
        assertTrue(phone.calls.contains("volume 40"));
        assertTrue(phone.calls.contains("launch org.telegram.messenger"));
        assertTrue(phone.calls.contains("key 85"));
        assertTrue(phone.calls.contains("key 87"));
        assertTrue(phone.calls.contains("key 88"));
        assertTrue(phone.calls.contains("notify Чайник вскипел"));
    }

    @Test
    public void badArgumentsFail() throws Exception {
        assertEquals("failed", cmd("phone.alarm", "25:00").getString("status"));
        assertEquals("failed", cmd("phone.alarm", "семь").getString("status"));
        assertEquals("failed", cmd("phone.timer", -5).getString("status"));
        assertEquals("failed", cmd("phone.flashlight", "maybe").getString("status"));
        assertEquals("failed", cmd("phone.volume", 150).getString("status"));
        assertEquals("failed", cmd("phone.open_url", "javascript:alert(1)").getString("status"));
        assertEquals("noop", cmd("phone.clipboard", "").getString("status"));
        assertEquals("noop", cmd("phone.open_app", "несуществующее").getString("status"));
        assertFalse(cmd("phone.volume", null).getBoolean("ok"));
        assertTrue(phone.calls.isEmpty());
    }

    @Test
    public void missingPermissionIsUnsupportedWithNotice() throws Exception {
        phone.dndAccess = false;
        JSONObject r = cmd("phone.dnd_on", null);
        assertEquals("unsupported", r.getString("status"));
        assertEquals("нет разрешения: Режим «Не беспокоить»", r.getString("detail"));
        assertFalse(r.getBoolean("ok"));
        phone.canStartActivities = false;
        assertEquals("нет разрешения: Поверх других окон", cmd("phone.alarm", "07:00").getString("detail"));
        phone.notifications = false;
        assertEquals("unsupported", cmd("phone.notify", "x").getString("status"));
        assertEquals(3, phone.missingNotices.size());
    }

    @Test
    public void noFlashAndUnknownAction() throws Exception {
        phone.hasFlash = false;
        assertEquals("unsupported", cmd("phone.flashlight", "on").getString("status"));
        JSONObject r = cmd("phone.teleport", null);
        assertEquals("unsupported", r.getString("status"));
        assertTrue(PhoneExecutor.handles("phone.find"));
        assertFalse(PhoneExecutor.handles("music.next"));
    }

    @Test
    public void appMatcherFuzzy() {
        assertEquals("ru.yandex.music", AppMatcher.best("музыка", phone.apps).pkg);
        assertEquals("ru.yandex.music", AppMatcher.best("Яндекс Музыка", phone.apps).pkg);
        assertEquals("org.telegram.messenger", AppMatcher.best("телеграмм", phone.apps).pkg);
        assertEquals("com.android.camera", AppMatcher.best("камеру", phone.apps).pkg);
        assertNull(AppMatcher.best("фотошоп", phone.apps));
        assertEquals(2, AppMatcher.distance("кот", "кит") + 1);
    }

    public static OfflineMatcher matcher() throws Exception {
        File f = new File("src/main/assets/phone_triggers.json");
        if (!f.isFile()) {
            f = new File("app/" + f.getPath());
        }
        return new OfflineMatcher(ActionCatalog.parse(new String(Files.readAllBytes(f.toPath()),
                StandardCharsets.UTF_8)).triggers);
    }

    @Test
    public void offlineMatcherBoundariesAndLongest() throws Exception {
        OfflineMatcher m = matcher();
        OfflineMatcher.Match a = m.match("Сакура, выключи не беспокоить!");
        assertEquals("phone.dnd_off", a.action);   // длиннее «не беспокоить»
        assertEquals("phone.dnd_on", m.match("включи не беспокоить").action);
        assertEquals("off", m.match("выключи фонарик").arg);
        assertEquals("on", m.match("включи фонарик").arg);
        assertEquals("phone.find", m.match("где мой телефон?").action);
        assertNull("подстрока внутри слова не считается", m.match("фонарикам привет"));
        assertNull(m.match("какая погода"));
    }

    @Test
    public void offlineMatcherArguments() throws Exception {
        OfflineMatcher m = matcher();
        assertEquals("07:30", m.match("поставь будильник на 7:30").arg);
        assertEquals("19:00", m.match("разбуди меня на 7 вечера").arg);
        assertEquals(300, m.match("поставь таймер на 5 минут").arg);
        assertEquals(45, m.match("засеки 45 секунд").arg);
        assertNull("таймер без длительности не выполняется локально", m.match("поставь таймер"));
        assertEquals("телеграм", m.match("открой на телефоне телеграм").arg);
        OfflineMatcher.Match url = m.match("открой ссылку на телефоне https://ya.ru/x");
        assertNotNull(url);
        assertEquals("https://ya.ru/x", url.arg);
    }
}
