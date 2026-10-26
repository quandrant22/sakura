package app.sakura.mobile.keys;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.nio.file.Files;
import java.security.GeneralSecurityException;

import app.sakura.mobile.crypto.noise.Primitives;
import app.sakura.mobile.testutil.SoftWrapper;

public class DeviceKeyStoreTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    @Test
    public void wrapUnwrap() throws Exception {
        SoftWrapper w = new SoftWrapper();
        byte[] secret = new byte[32];
        secret[3] = 7;
        byte[] blob = w.wrap(secret);
        assertEquals(1 + 12 + 32 + 16, blob.length);
        assertEquals(1, blob[0]);
        assertArrayEquals(secret, w.unwrap(blob));
        blob[20] ^= 1;
        assertThrows(GeneralSecurityException.class, () -> w.unwrap(blob));
        assertThrows(GeneralSecurityException.class, () -> w.unwrap(new byte[10]));
    }

    @Test
    public void unwrapWithAnotherKeyFails() throws Exception {
        SoftWrapper a = new SoftWrapper();
        SoftWrapper b = new SoftWrapper();
        byte[] blob = a.wrap(new byte[32]);
        b.wrap(new byte[1]);
        assertThrows(GeneralSecurityException.class, () -> b.unwrap(blob));
    }

    @Test
    public void deviceKeyIsStableAndEncryptedOnDisk() throws Exception {
        File dir = tmp.newFolder("keys");
        SoftWrapper w = new SoftWrapper();
        DeviceKeyStore ks = new DeviceKeyStore(dir, w);
        byte[] priv = ks.devicePrivate();
        assertArrayEquals(priv, ks.devicePrivate());
        byte[] onDisk = Files.readAllBytes(new File(dir, "device.key").toPath());
        assertFalse(java.util.Arrays.equals(priv, java.util.Arrays.copyOfRange(onDisk, 13, 45)));
        assertArrayEquals(Primitives.publicFromPrivate(priv), ks.devicePublic());
    }

    @Test
    public void serverSaveRotateForget() throws Exception {
        File dir = tmp.newFolder("keys2");
        SoftWrapper w = new SoftWrapper();
        DeviceKeyStore ks = new DeviceKeyStore(dir, w);
        assertFalse(ks.isPaired());
        byte[] pub = new byte[32];
        pub[0] = 1;
        ks.saveServer(new DeviceKeyStore.Server("ws://h:8765", pub, "phone", 5));
        assertTrue(ks.isPaired());
        assertEquals("phone", ks.server().deviceId);
        byte[] next = new byte[32];
        next[0] = 2;
        ks.rotateServerKey(next);
        assertArrayEquals(next, ks.server().pub);
        ks.devicePrivate();
        ks.forget();
        assertNull(ks.server());
        assertFalse(new File(dir, "device.key").exists());
        assertNull(w.key);
    }
}
