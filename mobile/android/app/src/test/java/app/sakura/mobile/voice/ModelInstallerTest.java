package app.sakura.mobile.voice;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class ModelInstallerTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static byte[] zip(String... namesAndBodies) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        try (ZipOutputStream z = new ZipOutputStream(b)) {
            for (int i = 0; i < namesAndBodies.length; i += 2) {
                z.putNextEntry(new ZipEntry(namesAndBodies[i]));
                z.write(namesAndBodies[i + 1].getBytes(StandardCharsets.UTF_8));
                z.closeEntry();
            }
        }
        return b.toByteArray();
    }

    private static String sha(byte[] d) throws Exception {
        return ModelInstaller.hex(MessageDigest.getInstance("SHA-256").digest(d));
    }

    @Test
    public void verifiedArchiveInstalls() throws Exception {
        byte[] z = zip(ModelInstaller.ROOT + "am/final.mdl", "x", ModelInstaller.ROOT + "conf/model.conf", "y");
        ModelInstaller m = new ModelInstaller(tmp.newFolder("vosk"));
        File f = m.download(new ByteArrayInputStream(z), sha(z), null);
        m.unpack(f);
        assertTrue(m.installed());
        assertFalse(f.exists());
        m.remove();
        assertFalse(m.installed());
    }

    @Test
    public void wrongHashDeletesFile() throws Exception {
        byte[] z = zip(ModelInstaller.ROOT + "am/final.mdl", "x");
        File dir = tmp.newFolder("vosk2");
        ModelInstaller m = new ModelInstaller(dir);
        assertThrows(ModelInstaller.ModelException.class,
                () -> m.download(new ByteArrayInputStream(z), ModelInstaller.SHA256, null));
        assertFalse(new File(dir, "model.zip.part").exists());
    }

    @Test
    public void zipSlipRejected() throws Exception {
        byte[] z = zip(ModelInstaller.ROOT + "../../evil.txt", "x");
        ModelInstaller m = new ModelInstaller(tmp.newFolder("vosk3"));
        File f = m.download(new ByteArrayInputStream(z), sha(z), null);
        assertThrows(ModelInstaller.ModelException.class, () -> m.unpack(f));
        assertFalse(m.installed());
    }

    @Test
    public void pinnedHashIsLowercaseSha256() {
        assertTrue(ModelInstaller.SHA256.matches("[0-9a-f]{64}"));
    }
}
