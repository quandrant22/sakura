package app.sakura.mobile.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * AGSL в JVM не компилируется (layoutlib рисует программно), поэтому проверяем согласованность:
 * каждый uniform, который задаёт SakuraCoreView, объявлен в шейдере, и наоборот. Компиляцию на
 * устройстве проверяет androidTest CoreShaderInstrumentedTest.
 */
public class AgslUniformsTest {

    private static Set<String> declared() {
        Set<String> out = new HashSet<>();
        Matcher m = Pattern.compile("uniform\\s+\\w+\\s+(\\w+)").matcher(CoreShading.AGSL);
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    private static Set<String> setInView() throws Exception {
        File f = new File("src/main/java/app/sakura/mobile/core/SakuraCoreView.java");
        if (!f.isFile()) {
            f = new File("app/" + f.getPath());
        }
        String src = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
        Set<String> out = new HashSet<>();
        Matcher m = Pattern.compile("set(?:Float|Color)Uniform\\(\"(\\w+)\"").matcher(src);
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    @Test
    public void uniformsConsistent() throws Exception {
        assertEquals(declared(), setInView());
    }

    @Test
    public void circlesArraySize() {
        assertTrue(CoreShading.AGSL.contains("uniform float3 uC[" + CoreShading.CIRCLES + "]"));
        assertTrue(CoreShading.AGSL.contains("half4 main(float2 frag)"));
    }
}
