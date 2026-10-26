package app.sakura.mobile.snap;

import android.view.ViewGroup;
import android.widget.FrameLayout;

import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;

import java.util.Arrays;
import java.util.Collection;
import java.util.Locale;

import app.cash.paparazzi.DeviceConfig;
import app.cash.paparazzi.EnvironmentKt;
import app.cash.paparazzi.Paparazzi;
import app.sakura.mobile.R;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;

/** Снимки ядра: 5 состояний × 2 темы (статичный кадр t = 0, программный растр). */
@RunWith(Parameterized.class)
public class CoreSnapshotTest {

    @Parameterized.Parameters(name = "{0}")
    public static Collection<Object[]> themes() {
        return Arrays.asList(new Object[][]{{"Theme.Sakura.Night"}, {"Theme.Sakura.Sketch"}});
    }

    @Rule
    public final Paparazzi paparazzi;
    private final String theme;

    public CoreSnapshotTest(String theme) {
        this.theme = theme;
        paparazzi = new Paparazzi(EnvironmentKt.detectEnvironment(), DeviceConfig.PIXEL_5, theme);
    }

    @Test
    public void coreStates() {
        for (CoreFrame.State s : CoreFrame.State.values()) {
            FrameLayout root = new FrameLayout(paparazzi.getContext());
            root.setBackgroundColor(Snap.attr(paparazzi.getContext(), R.attr.sakuraBg));
            SakuraCoreView core = new SakuraCoreView(paparazzi.getContext());
            core.setStaticFrame(true);
            core.setState(s);
            int size = paparazzi.getResources().getDimensionPixelSize(R.dimen.core_size);
            root.addView(core, new FrameLayout.LayoutParams(size, size, android.view.Gravity.CENTER));
            root.setLayoutParams(new ViewGroup.LayoutParams(size * 2, size * 2));
            paparazzi.snapshot(root, "core_" + s.name().toLowerCase(Locale.ROOT) + "_" + Snap.themeTag(theme));
        }
    }
}
