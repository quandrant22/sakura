package app.sakura.mobile.snap;

import android.content.Context;
import android.view.View;

import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;

import java.io.File;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collection;
import java.util.Locale;

import app.cash.paparazzi.DeviceConfig;
import app.cash.paparazzi.EnvironmentKt;
import app.cash.paparazzi.Paparazzi;
import app.sakura.mobile.R;
import app.sakura.mobile.app.Settings;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.control.ControlScreen;
import app.sakura.mobile.ui.dialog.ChatScreen;
import app.sakura.mobile.ui.model.ActionCatalog;
import app.sakura.mobile.ui.more.DiagnosticsFragment;
import app.sakura.mobile.ui.more.InterfaceFragment;
import app.sakura.mobile.ui.more.MemoryScreen;
import app.sakura.mobile.ui.more.MoreFragment;
import app.sakura.mobile.ui.more.PermissionsFragment;
import app.sakura.mobile.ui.more.ProfileScreen;
import app.sakura.mobile.ui.more.SecurityScreen;
import app.sakura.mobile.ui.more.VoiceSettingsFragment;
import app.sakura.mobile.ui.scenarios.BuilderScreen;
import app.sakura.mobile.ui.scenarios.ScenariosScreen;
import app.sakura.mobile.ui.summary.SummaryScreen;

/**
 * Снимки экранов в обеих темах. Экраны с данными сервера — 4 состояния (normal, empty, offline,
 * error); локальные экраны (Голос, Интерфейс, Разрешения, Ещё) — normal; Диагностика — normal и offline.
 */
@RunWith(Parameterized.class)
public class ScreensSnapshotTest {

    @Parameterized.Parameters(name = "{0}")
    public static Collection<Object[]> themes() {
        return Arrays.asList(new Object[][]{{"Theme.Sakura.Night"}, {"Theme.Sakura.Sketch"}});
    }

    @Rule
    public final Paparazzi paparazzi;
    private final String tag;

    public ScreensSnapshotTest(String theme) {
        tag = Snap.themeTag(theme);
        paparazzi = new Paparazzi(EnvironmentKt.detectEnvironment(), DeviceConfig.PIXEL_5, theme);
    }

    @SuppressWarnings("unchecked")
    static <T> T noop(Class<T> type) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (p, m, a) -> {
            if (m.getName().equals("equals")) {
                return p == a[0];
            }
            return m.getName().equals("hashCode") ? 0 : null;
        });
    }

    private View inflate(int layout) {
        return paparazzi.inflate(layout);
    }

    private void snap(View v, String screen, Demo.Kind k) {
        paparazzi.snapshot(v, screen + "_" + k.name().toLowerCase(Locale.ROOT) + "_" + tag);
    }

    private static void freezeCores(View v) {
        if (v instanceof SakuraCoreView) {
            ((SakuraCoreView) v).setStaticFrame(true);
        } else if (v instanceof android.view.ViewGroup) {
            android.view.ViewGroup g = (android.view.ViewGroup) v;
            for (int i = 0; i < g.getChildCount(); i++) {
                freezeCores(g.getChildAt(i));
            }
        }
    }

    @Test
    public void dialog() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_dialog);
            freezeCores(v);
            ChatScreen s = new ChatScreen(v, noop(ChatScreen.Callbacks.class));
            ChatScreen.State st = new ChatScreen.State();
            st.messages = Demo.of(k, Demo.messages());
            st.hasMore = k == Demo.Kind.NORMAL;
            st.core = k == Demo.Kind.OFFLINE ? CoreFrame.State.OFFLINE : CoreFrame.State.IDLE;
            st.transcript = k == Demo.Kind.NORMAL ? "сделай потише" : "";
            s.render(st);
            snap(v, "dialog", k);
        }
    }

    @Test
    public void control() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_control);
            ControlScreen s = new ControlScreen(v, noop(ControlScreen.Callbacks.class));
            ControlScreen.State st = new ControlScreen.State();
            st.devices = Demo.of(k, Demo.devices());
            st.selected = "pc";
            s.render(st);
            snap(v, "control", k);
        }
    }

    @Test
    public void summary() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_summary);
            new SummaryScreen(v, () -> { }).render(Demo.of(k, Demo.summary()));
            snap(v, "summary", k);
        }
    }

    @Test
    public void scenarios() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_scenarios);
            ScenariosScreen s = new ScenariosScreen(v, noop(ScenariosScreen.Callbacks.class));
            ScenariosScreen.State st = new ScenariosScreen.State();
            st.list = Demo.of(k, Demo.scenarios());
            if (k == Demo.Kind.NORMAL) {
                st.journalTitle = "Запуск: Режим сна";
                st.journal = Arrays.asList("запущен", "• шаг 1 — Не беспокоить на телефоне", "✓ готово");
            }
            s.render(st);
            snap(v, "scenarios", k);
        }
    }

    static ActionCatalog catalog() throws Exception {
        File f = new File("src/main/assets/phone_triggers.json");
        if (!f.isFile()) {
            f = new File("app/" + f.getPath());
        }
        return ActionCatalog.parse(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
    }

    @Test
    public void builder() throws Exception {
        View v = inflate(R.layout.screen_scenario_builder);
        BuilderScreen s = new BuilderScreen(v, catalog(), noop(BuilderScreen.Callbacks.class));
        snap(v, "builder", Demo.Kind.EMPTY);
        View p = inflate(R.layout.screen_scenario_builder);
        BuilderScreen ps = new BuilderScreen(p, catalog(), noop(BuilderScreen.Callbacks.class));
        ps.renderPreview(Loadable.ready(Demo.scenarios().get(0)), Arrays.asList("время уточнено до 22:00"), null);
        snap(p, "builder", Demo.Kind.NORMAL);
        View e = inflate(R.layout.screen_scenario_builder);
        new BuilderScreen(e, catalog(), noop(BuilderScreen.Callbacks.class))
                .renderPreview(Loadable.failed(new ApiError("unsupported", "")), null, null);
        snap(e, "builder", Demo.Kind.ERROR);
        s.showNote(null);
    }

    @Test
    public void memory() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_memory);
            MemoryScreen s = new MemoryScreen(v, noop(MemoryScreen.Callbacks.class));
            MemoryScreen.State st = new MemoryScreen.State();
            st.items = Demo.of(k, Demo.memory());
            st.counts = k == Demo.Kind.NORMAL ? Demo.counts() : st.counts;
            s.render(st);
            snap(v, "memory", k);
        }
    }

    @Test
    public void profile() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_profile);
            new ProfileScreen(v, p -> { }, () -> { }).render(Demo.of(k, Demo.profile()));
            snap(v, "profile", k);
        }
    }

    @Test
    public void security() {
        for (Demo.Kind k : Demo.Kind.values()) {
            View v = inflate(R.layout.screen_security);
            SecurityScreen s = new SecurityScreen(v, () -> { });
            SecurityScreen.Info i = new SecurityScreen.Info();
            i.paired = k != Demo.Kind.EMPTY;
            i.url = "ws://31.76.80.5:8765";
            i.fingerprint = "3f9a 1c02 77de 0b41";
            i.deviceId = "phone";
            i.connection = k == Demo.Kind.OFFLINE ? "нет связи" : "онлайн (Noise)";
            s.renderInfo(i);
            s.renderDevices(Demo.of(k, Demo.secureDevices()));
            snap(v, "security", k);
        }
    }

    private Settings settings() {
        Context c = paparazzi.getContext();
        return new Settings(c);   // в layoutlib SharedPreferences — заглушка: значения по умолчанию
    }

    @Test
    public void localScreens() {
        View voice = inflate(R.layout.screen_voice);
        VoiceSettingsFragment.bind(voice, settings(), false, true);
        snap(voice, "voice", Demo.Kind.NORMAL);

        View ui = inflate(R.layout.screen_interface);
        freezeCores(ui);
        InterfaceFragment.bind(ui, settings());
        freezeCores(ui);
        snap(ui, "interface", Demo.Kind.NORMAL);

        View perms = inflate(R.layout.screen_list);
        PermissionsFragment.bind(perms, new boolean[]{true, true, false, false, false}, null);
        snap(perms, "permissions", Demo.Kind.NORMAL);

        View more = inflate(R.layout.screen_list);
        MoreFragment.bind(more, null);
        snap(more, "more", Demo.Kind.NORMAL);

        View diag = inflate(R.layout.screen_list);
        DiagnosticsFragment.bind(diag, DiagnosticsFragment.rows(
                new SakuraClient.Status(SakuraClient.Conn.ONLINE, 2, true, 0), 0, 1, true, true, 1_400_000));
        snap(diag, "diagnostics", Demo.Kind.NORMAL);

        View diagOff = inflate(R.layout.screen_list);
        DiagnosticsFragment.bind(diagOff, DiagnosticsFragment.rows(
                new SakuraClient.Status(SakuraClient.Conn.OFFLINE, 2, true, 4408), 2, 0, false, false, 0));
        snap(diagOff, "diagnostics", Demo.Kind.OFFLINE);
    }
}
