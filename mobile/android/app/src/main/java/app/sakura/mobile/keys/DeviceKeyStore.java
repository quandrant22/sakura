package app.sakura.mobile.keys;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.GeneralSecurityException;
import java.util.Arrays;

import app.sakura.mobile.crypto.noise.Primitives;
import app.sakura.mobile.pairing.PairingCodes;

/**
 * Ключи на диске, каталог files/keys/:
 * device.key — закрытый X25519 устройства, зашифрованный KeyWrapper (AES-GCM под sakura_wrap);
 * server.json — адрес и открытый ключ сервера, device_id (открытые данные).
 */
public final class DeviceKeyStore {
    private static final String DEVICE_KEY = "device.key";
    private static final String SERVER = "server.json";

    /** Данные спаривания. */
    public static final class Server {
        public final String url;
        public final byte[] pub;
        public final String deviceId;
        public final double pairedAt;

        public Server(String url, byte[] pub, String deviceId, double pairedAt) {
            this.url = url;
            this.pub = pub.clone();
            this.deviceId = deviceId;
            this.pairedAt = pairedAt;
        }

        public String fingerprint() {
            return PairingCodes.fingerprint(pub);
        }
    }

    private final File dir;
    private final KeyWrapper wrapper;

    public DeviceKeyStore(File dir, KeyWrapper wrapper) {
        this.dir = dir;
        this.wrapper = wrapper;
    }

    /** Закрытый ключ устройства; создаётся при первом обращении. */
    public synchronized byte[] devicePrivate() throws GeneralSecurityException, IOException {
        File f = new File(dir, DEVICE_KEY);
        if (f.isFile()) {
            return wrapper.unwrap(Files.readAllBytes(f.toPath()));
        }
        byte[][] kp = Primitives.generateKeypair();
        writeAtomic(f, wrapper.wrap(kp[0]));
        Arrays.fill(kp[1], (byte) 0);
        return kp[0];
    }

    public byte[] devicePublic() throws GeneralSecurityException, IOException {
        byte[] priv = devicePrivate();
        try {
            return Primitives.publicFromPrivate(priv);
        } finally {
            Arrays.fill(priv, (byte) 0);
        }
    }

    public synchronized Server server() {
        File f = new File(dir, SERVER);
        if (!f.isFile()) {
            return null;
        }
        try {
            JSONObject o = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            return new Server(o.getString("url"), PairingCodes.unb64url(o.getString("pub")),
                    o.getString("device_id"), o.optDouble("paired_at", 0));
        } catch (IOException | JSONException | IllegalArgumentException e) {
            return null;
        }
    }

    public synchronized void saveServer(Server s) throws IOException {
        try {
            JSONObject o = new JSONObject()
                    .put("url", s.url)
                    .put("pub", PairingCodes.b64url(s.pub))
                    .put("device_id", s.deviceId)
                    .put("paired_at", s.pairedAt);
            writeAtomic(new File(dir, SERVER), o.toString().getBytes(StandardCharsets.UTF_8));
        } catch (JSONException e) {
            throw new IOException("не удалось сохранить сервер");
        }
    }

    /** secure_server_key: новый ключ сервера со следующего соединения. */
    public synchronized void rotateServerKey(byte[] newPub) throws IOException {
        Server s = server();
        if (s == null || newPub == null || newPub.length != 32) {
            return;
        }
        saveServer(new Server(s.url, newPub, s.deviceId, s.pairedAt));
    }

    public boolean isPaired() {
        return server() != null;
    }

    /** «Забыть сервер»: стереть всё, включая ключ обёртки. */
    public synchronized void forget() {
        for (String name : new String[]{SERVER, DEVICE_KEY}) {
            File f = new File(dir, name);
            if (f.isFile()) {
                overwrite(f);
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            }
        }
        wrapper.destroy();
    }

    private static void overwrite(File f) {
        try (FileOutputStream out = new FileOutputStream(f)) {
            out.write(new byte[(int) Math.min(f.length(), 4096)]);
        } catch (IOException ignored) {
            // удаление ниже всё равно выполнится
        }
    }

    private void writeAtomic(File target, byte[] data) throws IOException {
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("нет каталога ключей");
        }
        File tmp = new File(dir, target.getName() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(data);
            out.getFD().sync();
        }
        if (!tmp.renameTo(target)) {
            //noinspection ResultOfMethodCallIgnored
            target.delete();
            if (!tmp.renameTo(target)) {
                throw new IOException("не удалось записать " + target.getName());
            }
        }
    }
}
