package app.sakura.mobile;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

import app.sakura.mobile.overlay.Snap;
import app.sakura.mobile.vision.Vision;

/** Чистая логика M8: прилипание и зона «×», размер кадра для vision_request, манифест. */
public class M8Test {

    @Test
    public void floatingCoreSnapsToNearestEdge() {
        assertEquals(8, Snap.edgeX(100, 56, 1080, 8));
        assertEquals(1080 - 56 - 8, Snap.edgeX(700, 56, 1080, 8));
        assertEquals(8, Snap.clampY(-50, 56, 2400, 8));
        assertEquals(2400 - 56 - 8, Snap.clampY(5000, 56, 2400, 8));
        assertTrue(Snap.overClose(500, 2000, 56, 528, 2028, 56));
        assertFalse(Snap.overClose(100, 500, 56, 528, 2028, 56));
    }

    @Test
    public void visionFitKeepsAspectAndLimit() {
        assertArrayEquals(new int[]{1280, 960}, Vision.fit(4000, 3000));
        assertArrayEquals(new int[]{720, 1280}, Vision.fit(2160, 3840));
        assertArrayEquals(new int[]{800, 600}, Vision.fit(800, 600));
        assertEquals(70, Vision.QUALITY);
    }

    @Test
    public void sharePrefix() throws Exception {
        java.lang.reflect.Method m = app.sakura.mobile.share.ShareActivity.class
                .getDeclaredMethod("textMessage", String.class);
        m.setAccessible(true);
        assertEquals("Мастер поделился: ссылка", m.invoke(null, "  ссылка "));
        assertNull(m.invoke(null, "   "));
    }

    private static String manifest() throws Exception {
        File f = new File("src/main/AndroidManifest.xml");
        if (!f.isFile()) {
            f = new File("app/" + f.getPath());
        }
        return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
    }

    @Test
    public void manifestDeclaresM8Components() throws Exception {
        String m = manifest();
        assertTrue(m.contains("android.service.voice.VoiceInteractionService"));
        assertTrue(m.contains("android.permission.BIND_VOICE_INTERACTION"));
        assertTrue(m.contains("android.service.quicksettings.action.QS_TILE"));
        assertTrue(m.contains("android.appwidget.provider"));
        assertTrue(m.contains("android.intent.action.SEND"));
        assertTrue(m.contains("image/*"));
        assertTrue(m.contains("PROPERTY_SPECIAL_USE_FGS_SUBTYPE"));
        assertTrue(m.contains("android:allowBackup=\"false\""));
        assertFalse("fullBackupContent убран", m.contains("fullBackupContent"));
    }
}
