package app.sakura.mobile.core;

import static org.junit.Assert.assertEquals;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RuntimeShader;
import android.os.SystemClock;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

/** На устройстве: AGSL компилируется, uniform-ы принимаются, кадр рисуется (в RUNBOOK). */
@RunWith(AndroidJUnit4.class)
public class CoreShaderInstrumentedTest {
    @Test
    public void shaderCompilesAndDraws() {
        RuntimeShader s = new RuntimeShader(CoreShading.AGSL);
        CoreFrame.Out f = new CoreFrame.Out();
        CoreFrame.compute(0, CoreFrame.State.IDLE, 0, CoreFrame.Mobility.NORMAL, f);
        float[] c = new float[CoreShading.CIRCLES * 3];
        CoreShading.pack(f, c);
        s.setFloatUniform("uC", c);
        s.setFloatUniform("uSigma", 6f);
        s.setFloatUniform("uMat", 22f, -10f);
        s.setFloatUniform("uGc", -21.5f, -17f);
        s.setFloatUniform("uGr", 71.4f);
        s.setFloatUniform("uScale", 1f);
        s.setFloatUniform("uOrigin", 130f, 130f);
        s.setFloatUniform("uOpacity", 1f);
        s.setColorUniform("uA", 0xFFFF6AE3);
        s.setColorUniform("uB", 0xFF3E0074);
        s.setColorUniform("uSoft", 0x29FF6AE3);
        Paint p = new Paint();
        p.setShader(s);
        Bitmap b = Bitmap.createBitmap(260, 260, Bitmap.Config.ARGB_8888);
        long t0 = SystemClock.elapsedRealtimeNanos();
        new Canvas(b).drawRect(0, 0, 260, 260, p);
        assertEquals(0xFF, b.getPixel(130, 130) >>> 24);
        assertEquals(0, b.getPixel(2, 2) >>> 24);
        android.util.Log.i("CoreShader", "draw ns=" + (SystemClock.elapsedRealtimeNanos() - t0));
    }
}
