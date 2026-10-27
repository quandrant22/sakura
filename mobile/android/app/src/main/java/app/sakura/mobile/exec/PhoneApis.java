package app.sakura.mobile.exec;

import java.util.List;

/**
 * Возможности телефона для исполнителя (реализация — AndroidPhoneApis). Каждый метод бросает
 * {@link Missing}, если не хватает разрешения, и {@link Failed} при сбое.
 */
public interface PhoneApis {

    /** Не хватает разрешения: title — название из экрана «Разрешения». */
    final class Missing extends Exception {
        public final String title;

        public Missing(String title) {
            super(title);
            this.title = title;
        }
    }

    final class Failed extends Exception {
        public Failed(String message) {
            super(message);
        }
    }

    /** Приложение для open_app: подпись и пакет. */
    final class App {
        public final String label;
        public final String pkg;

        public App(String label, String pkg) {
            this.label = label;
            this.pkg = pkg;
        }
    }

    /** USAGE_ALARM на максимуме, seconds секунд. */
    void ring(int seconds) throws Missing, Failed;

    /** true — «Не беспокоить» включить. */
    void dnd(boolean on) throws Missing, Failed;

    void alarm(int hour, int minute) throws Missing, Failed;

    void timer(int seconds) throws Missing, Failed;

    /** Возвращает false, если на телефоне нет вспышки. */
    boolean torch(boolean on) throws Missing, Failed;

    void volume(int percent) throws Missing, Failed;

    void clipboard(String text) throws Missing, Failed;

    void openUrl(String url) throws Missing, Failed;

    List<App> launchableApps();

    void launch(App app) throws Missing, Failed;

    /** KeyEvent.KEYCODE_MEDIA_* (play_pause, next, previous). */
    void mediaKey(int keyCode) throws Missing, Failed;

    void notify(String text) throws Missing, Failed;

    /** Уведомление «нет разрешения: …» со ссылкой на выдачу. */
    void notifyMissing(String title);
}
