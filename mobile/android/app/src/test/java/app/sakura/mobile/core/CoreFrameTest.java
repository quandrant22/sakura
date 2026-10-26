package app.sakura.mobile.core;

import static org.junit.Assert.assertEquals;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.util.Locale;

import app.sakura.mobile.testutil.Hex;

/** Сверка порта с coreFrame.ts (tools/export-core-frames.mjs → core_frames.json), допуск 1e-3. */
public class CoreFrameTest {
    private static final double EPS = 1e-3;

    private static CoreFrame.State state(String s) {
        return CoreFrame.State.valueOf(s.toUpperCase(Locale.ROOT));
    }

    @Test
    public void matchesDesktopFrames() throws Exception {
        JSONArray frames = Hex.resourceJson("core_frames.json").getJSONArray("frames");
        assertEquals(180, frames.length());
        CoreFrame.Out out = new CoreFrame.Out();
        for (int i = 0; i < frames.length(); i++) {
            JSONObject e = frames.getJSONObject(i);
            CoreFrame.compute(e.getDouble("t"), state(e.getString("state")), e.getDouble("level"),
                    CoreFrame.Mobility.of(e.getString("mobility")), out);
            JSONObject f = e.getJSONObject("frame");
            String at = e.toString().substring(0, 60);
            assertEquals(at, f.getJSONObject("drop").getDouble("r"), out.dropR, EPS);
            assertEquals(at, f.getDouble("opacity"), out.opacity, EPS);
            JSONArray sats = f.getJSONArray("satellites");
            for (int s = 0; s < CoreFrame.SATS; s++) {
                JSONObject c = sats.getJSONObject(s);
                assertEquals(at, c.getDouble("cx"), out.satCx[s], EPS);
                assertEquals(at, c.getDouble("cy"), out.satCy[s], EPS);
                assertEquals(at, c.getDouble("r"), out.satR[s], EPS);
            }
            JSONArray rings = f.getJSONArray("rings");
            assertEquals(at, rings.length(), out.ringCount);
            for (int r = 0; r < rings.length(); r++) {
                assertEquals(at, rings.getJSONObject(r).getDouble("r"), out.ringR[r], EPS);
                assertEquals(at, rings.getJSONObject(r).getDouble("opacity"), out.ringOpacity[r], EPS);
            }
        }
    }

    @Test
    public void constantsMatch() throws Exception {
        JSONObject c = Hex.resourceJson("core_frames.json").getJSONObject("constants");
        assertEquals(c.getDouble("DROP_R"), CoreFrame.DROP_R, 0);
        assertEquals(c.getDouble("MAX_RING_R"), CoreFrame.MAX_RING_R, 0);
        JSONArray sats = c.getJSONArray("SATELLITES");
        for (int i = 0; i < CoreFrame.SATS; i++) {
            for (int j = 0; j < 3; j++) {
                assertEquals(sats.getJSONArray(i).getDouble(j), CoreFrame.SATELLITES[i][j], 0);
            }
        }
        assertEquals(c.getJSONObject("VIEWBOX").getDouble("w"), CoreFrame.VIEWBOX_W, 0);
        assertEquals(c.getJSONObject("VIEWBOX").getDouble("x"), CoreFrame.VIEWBOX_X, 0);
        assertEquals(c.getJSONObject("MOBILITY").getDouble("high"), CoreFrame.Mobility.HIGH.k, 0);
        JSONObject liquid = c.getJSONObject("MERGE_PRESETS").getJSONObject("liquid");
        assertEquals(liquid.getDouble("blur"), CoreFrame.MergePreset.LIQUID.blur, 0);
        assertEquals(liquid.getString("matrix"), "26 -12");
    }

    @Test
    public void nanAndInfinityAreSafe() {
        CoreFrame.Out a = new CoreFrame.Out();
        CoreFrame.Out b = new CoreFrame.Out();
        for (CoreFrame.State s : CoreFrame.State.values()) {
            CoreFrame.compute(Double.NaN, s, Double.POSITIVE_INFINITY, CoreFrame.Mobility.NORMAL, a);
            CoreFrame.compute(0, s, 0, CoreFrame.Mobility.NORMAL, b);
            assertEquals(b.dropR, a.dropR, 0);
            for (int i = 0; i < CoreFrame.SATS; i++) {
                assertEquals(b.satCx[i], a.satCx[i], 0);
                assertEquals(false, Double.isNaN(a.satR[i]));
            }
            CoreFrame.compute(Double.NEGATIVE_INFINITY, s, Double.NaN, CoreFrame.Mobility.HIGH, a);
            assertEquals(false, Double.isNaN(a.dropR));
        }
    }

    @Test
    public void fpsByState() {
        assertEquals(30, CoreFrame.fps(CoreFrame.State.IDLE));
        assertEquals(10, CoreFrame.fps(CoreFrame.State.OFFLINE));
        assertEquals(60, CoreFrame.fps(CoreFrame.State.SPEAKING));
    }
}
