package app.sakura.mobile.exec;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Фейковый телефон: пишет вызовы в журнал; разрешения и вспышку можно отключить. */
public final class FakePhone implements PhoneApis {
    public final List<String> calls = new ArrayList<>();
    public final List<String> missingNotices = new ArrayList<>();
    public boolean dndAccess = true;
    public boolean notifications = true;
    public boolean canStartActivities = true;
    public boolean hasFlash = true;
    public List<App> apps = new ArrayList<>(Arrays.asList(
            new App("Телеграм", "org.telegram.messenger"),
            new App("Яндекс Музыка", "ru.yandex.music"),
            new App("Камера", "com.android.camera"),
            new App("Карты", "ru.yandex.maps")));

    private void activity() throws Missing {
        if (!canStartActivities) {
            throw new Missing("Поверх других окон");
        }
    }

    @Override
    public void ring(int seconds) {
        calls.add("ring " + seconds);
    }

    @Override
    public void dnd(boolean on) throws Missing {
        if (!dndAccess) {
            throw new Missing("Режим «Не беспокоить»");
        }
        calls.add("dnd " + on);
    }

    @Override
    public void alarm(int hour, int minute) throws Missing {
        activity();
        calls.add("alarm " + hour + ":" + minute);
    }

    @Override
    public void timer(int seconds) throws Missing {
        activity();
        calls.add("timer " + seconds);
    }

    @Override
    public boolean torch(boolean on) {
        if (hasFlash) {
            calls.add("torch " + on);
        }
        return hasFlash;
    }

    @Override
    public void volume(int percent) {
        calls.add("volume " + percent);
    }

    @Override
    public void clipboard(String text) {
        calls.add("clipboard " + text);
    }

    @Override
    public void openUrl(String url) throws Missing {
        activity();
        calls.add("url " + url);
    }

    @Override
    public List<App> launchableApps() {
        return apps;
    }

    @Override
    public void launch(App app) throws Missing {
        activity();
        calls.add("launch " + app.pkg);
    }

    @Override
    public void mediaKey(int keyCode) {
        calls.add("key " + keyCode);
    }

    @Override
    public void notify(String text) throws Missing {
        if (!notifications) {
            throw new Missing("Уведомления");
        }
        calls.add("notify " + text);
    }

    @Override
    public void notifyMissing(String title) {
        missingNotices.add(title);
    }
}
