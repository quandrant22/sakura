package app.sakura.mobile.voice;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Модель Vosk для слова «Сакура»: скачивается по кнопке, проверяется SHA-256 до распаковки,
 * распаковывается в files/vosk/model (защита от выхода за каталог). Без Android-зависимостей.
 */
public final class ModelInstaller {
    public static final String URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip";
    public static final String SHA256 = "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4";
    public static final long SIZE = 46_236_750L;
    static final String ROOT = "vosk-model-small-ru-0.22/";

    public static final class ModelException extends Exception {
        public ModelException(String message) {
            super(message);
        }
    }

    public interface Progress {
        void onProgress(long done, long total);
    }

    private final File dir;

    public ModelInstaller(File dir) {
        this.dir = dir;
    }

    public File modelDir() {
        return new File(dir, "model");
    }

    public boolean installed() {
        return new File(modelDir(), "am/final.mdl").isFile() && new File(modelDir(), ".ok").isFile();
    }

    /** Сохранить поток в zip, проверяя хеш на лету; неверный хеш — файл удаляется. */
    public File download(InputStream body, String expectedSha, Progress progress) throws IOException, ModelException {
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("нет каталога модели");
        }
        File zip = new File(dir, "model.zip.part");
        MessageDigest md = sha();
        long done = 0;
        try (InputStream in = new DigestInputStream(new BufferedInputStream(body), md);
             OutputStream out = new FileOutputStream(zip)) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                done += n;
                if (progress != null) {
                    progress.onProgress(done, SIZE);
                }
            }
        }
        String got = hex(md.digest());
        if (!got.equalsIgnoreCase(expectedSha)) {
            //noinspection ResultOfMethodCallIgnored
            zip.delete();
            throw new ModelException("контрольная сумма модели не совпала — файл удалён");
        }
        return zip;
    }

    /** Распаковка проверенного архива; содержимое ROOT → model/. */
    public void unpack(File zip) throws IOException, ModelException {
        File target = modelDir();
        deleteTree(target);
        if (!target.mkdirs()) {
            throw new IOException("нет каталога модели");
        }
        String base = target.getCanonicalPath() + File.separator;
        try (ZipInputStream z = new ZipInputStream(new BufferedInputStream(new FileInputStream(zip)))) {
            ZipEntry e;
            byte[] buf = new byte[64 * 1024];
            while ((e = z.getNextEntry()) != null) {
                String name = e.getName();
                if (!name.startsWith(ROOT)) {
                    throw new ModelException("неожиданная структура архива");
                }
                String rel = name.substring(ROOT.length());
                if (rel.isEmpty()) {
                    continue;
                }
                File out = new File(target, rel);
                if (!out.getCanonicalPath().startsWith(base)) {
                    throw new ModelException("недопустимый путь в архиве");
                }
                if (e.isDirectory()) {
                    //noinspection ResultOfMethodCallIgnored
                    out.mkdirs();
                    continue;
                }
                File parent = out.getParentFile();
                if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                    throw new IOException("не создать каталог");
                }
                try (OutputStream o = new FileOutputStream(out)) {
                    int n;
                    while ((n = z.read(buf)) > 0) {
                        o.write(buf, 0, n);
                    }
                }
            }
        }
        if (!new File(target, "am/final.mdl").isFile()) {
            throw new ModelException("в архиве нет модели");
        }
        //noinspection ResultOfMethodCallIgnored
        new File(target, ".ok").createNewFile();
        //noinspection ResultOfMethodCallIgnored
        zip.delete();
    }

    public void remove() {
        deleteTree(modelDir());
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) {
                deleteTree(k);
            }
        }
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    private static MessageDigest sha() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    static String hex(byte[] d) {
        StringBuilder sb = new StringBuilder(d.length * 2);
        for (byte b : d) {
            sb.append(String.format(Locale.ROOT, "%02x", b & 0xFF));
        }
        return sb.toString();
    }
}
