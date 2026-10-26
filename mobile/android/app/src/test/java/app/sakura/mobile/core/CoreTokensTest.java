package app.sakura.mobile.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** В res/layout* цвета — только токены (?attr/…, @color/…): никаких #RRGGBB и @android:color. */
public class CoreTokensTest {
    private static final Pattern HEX = Pattern.compile("\"#[0-9a-fA-F]{3,8}\"");
    private static final Pattern SYSTEM = Pattern.compile("@android:color/(?!transparent)");

    private static File res() {
        File f = new File("src/main/res");
        return f.isDirectory() ? f : new File("app/src/main/res");
    }

    @Test
    public void noHardcodedColorsInLayouts() throws IOException {
        File[] dirs = res().listFiles((d, n) -> n.startsWith("layout"));
        assertTrue("нет каталогов разметки", dirs != null && dirs.length > 0);
        List<String> bad = new ArrayList<>();
        for (File dir : dirs) {
            File[] files = dir.listFiles((d, n) -> n.endsWith(".xml"));
            if (files == null) {
                continue;
            }
            for (File f : files) {
                String text = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
                Matcher m = HEX.matcher(text);
                while (m.find()) {
                    bad.add(dir.getName() + "/" + f.getName() + ": " + m.group());
                }
                if (SYSTEM.matcher(text).find()) {
                    bad.add(dir.getName() + "/" + f.getName() + ": @android:color");
                }
            }
        }
        assertEquals("хардкод цветов в разметке: " + bad, 0, bad.size());
    }

    @Test
    public void tokensMatchUiMd() throws IOException {
        String colors = new String(Files.readAllBytes(new File(res(), "values/colors.xml").toPath()),
                StandardCharsets.UTF_8);
        assertTrue(colors.contains("<color name=\"accent\">#FF6AE3</color>"));
        assertTrue(colors.contains("<color name=\"accent_deep\">#3E0074</color>"));
        String dimens = new String(Files.readAllBytes(new File(res(), "values/dimens.xml").toPath()),
                StandardCharsets.UTF_8);
        assertTrue(dimens.contains("<dimen name=\"radius_card\">20dp</dimen>"));
        assertTrue(dimens.contains("<dimen name=\"radius_btn\">12dp</dimen>"));
    }

    @Test
    public void shadingInsideAndOutside() {
        CoreFrame.Out f = new CoreFrame.Out();
        CoreFrame.compute(0, CoreFrame.State.IDLE, 0, CoreFrame.Mobility.NORMAL, f);
        float[] c = new float[CoreShading.CIRCLES * 3];
        CoreShading.pack(f, c);
        int accent = 0xFFFF6AE3;
        int deep = 0xFF3E0074;
        int soft = 0x29FF6AE3;
        int center = CoreShading.pixel(0, 0, c, CoreFrame.MergePreset.SOFT, accent, deep, soft, 1);
        assertEquals(0xFF, center >>> 24);
        int far = CoreShading.pixel(125, 125, c, CoreFrame.MergePreset.SOFT, accent, deep, soft, 1);
        assertEquals(0, far >>> 24);
        // градиент: у центра градиента — accent, к краю темнее
        int atGc = CoreShading.pixel((float) CoreFrame.GRADIENT_CX, (float) CoreFrame.GRADIENT_CY, c,
                CoreFrame.MergePreset.SOFT, accent, deep, soft, 1);
        assertEquals(0xFF6AE3, atGc & 0xFFFFFF);
        int edge = CoreShading.pixel(40, 10, c, CoreFrame.MergePreset.SOFT, accent, deep, soft, 1);
        assertTrue(((edge >> 16) & 0xFF) < 0xFF);
        int offline = CoreShading.pixel(0, 0, c, CoreFrame.MergePreset.SOFT, accent, deep, soft, 0.45);
        assertEquals(Math.round(0.45 * 255), offline >>> 24);
    }

    @Test
    public void rasterBudget() {
        CoreFrame.Out f = new CoreFrame.Out();
        float[] c = new float[CoreShading.CIRCLES * 3];
        int[] px = new int[64 * 64];
        CoreFrame.compute(1.5, CoreFrame.State.SPEAKING, 0.7, CoreFrame.Mobility.HIGH, f);
        CoreShading.raster(f, CoreFrame.MergePreset.LIQUID, 0xFFFF6AE3, 0xFF3E0074, 0x29FF6AE3, 64, c, px);
        int opaque = 0;
        for (int p : px) {
            opaque += (p >>> 24) == 0xFF ? 1 : 0;
        }
        assertTrue("капля видна", opaque > 64 * 64 / 10);
        assertTrue("есть прозрачный фон", opaque < 64 * 64 * 9 / 10);
    }
}
