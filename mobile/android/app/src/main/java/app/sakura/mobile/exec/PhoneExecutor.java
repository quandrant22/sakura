package app.sakura.mobile.exec;

import android.view.KeyEvent;

import org.json.JSONObject;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import app.sakura.mobile.proto.Json;

/**
 * Исполнитель команд «Контракта телефона»: {"type":"command","id","action":"phone.*","arg"} →
 * {"type":"command_result","id","ok","status":"done|noop|failed|unsupported","detail"}.
 * Холодный путь: не зависит от анимаций, темы и озвучки. Нет разрешения → unsupported,
 * detail «нет разрешения: …» и уведомление со ссылкой на выдачу.
 */
public final class PhoneExecutor {
    public static final String DONE = "done";
    public static final String NOOP = "noop";
    public static final String FAILED = "failed";
    public static final String UNSUPPORTED = "unsupported";
    public static final int FIND_SECONDS = 30;

    public static final class Result {
        public final String status;
        public final String detail;

        Result(String status, String detail) {
            this.status = status;
            this.detail = detail;
        }

        public boolean ok() {
            return DONE.equals(status);
        }

        public JSONObject toJson(String id) {
            return Json.obj("type", "command_result", "id", id, "ok", ok(), "status", status, "detail", detail);
        }
    }

    private static final Pattern HHMM = Pattern.compile("^\\s*(\\d{1,2})[:.](\\d{2})\\s*$");

    private final PhoneApis apis;

    public PhoneExecutor(PhoneApis apis) {
        this.apis = apis;
    }

    public static boolean handles(String action) {
        return action != null && action.startsWith("phone.");
    }

    static Result done(String d) {
        return new Result(DONE, d);
    }

    static Result failed(String d) {
        return new Result(FAILED, d);
    }

    static String str(Object arg) {
        if (arg == null || arg == JSONObject.NULL) {
            return "";
        }
        return String.valueOf(arg).trim();
    }

    static Integer integer(Object arg) {
        if (arg instanceof Number) {
            return ((Number) arg).intValue();
        }
        String s = str(arg);
        try {
            return s.isEmpty() ? null : (int) Math.round(Double.parseDouble(s.replace(',', '.')));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** Команда сервера → command_result. */
    public JSONObject onCommand(JSONObject cmd) {
        String id = cmd.optString("id", "");
        return run(cmd.optString("action", ""), cmd.opt("arg")).toJson(id);
    }

    public Result run(String action, Object arg) {
        try {
            return exec(action == null ? "" : action, arg);
        } catch (PhoneApis.Missing m) {
            apis.notifyMissing(m.title);
            return new Result(UNSUPPORTED, "нет разрешения: " + m.title);
        } catch (PhoneApis.Failed f) {
            return failed(f.getMessage());
        } catch (RuntimeException e) {
            return failed("ошибка телефона");
        }
    }

    private Result exec(String action, Object arg) throws PhoneApis.Missing, PhoneApis.Failed {
        switch (action) {
            case "phone.find":
                apis.ring(FIND_SECONDS);
                return done("звоню " + FIND_SECONDS + " с");
            case "phone.dnd_on":
                apis.dnd(true);
                return done("«Не беспокоить» включён");
            case "phone.dnd_off":
                apis.dnd(false);
                return done("«Не беспокоить» выключен");
            case "phone.alarm": {
                Matcher m = HHMM.matcher(str(arg));
                if (!m.matches()) {
                    return failed("нужно время ЧЧ:ММ");
                }
                int h = Integer.parseInt(m.group(1));
                int min = Integer.parseInt(m.group(2));
                if (h > 23 || min > 59) {
                    return failed("нужно время ЧЧ:ММ");
                }
                apis.alarm(h, min);
                return done(String.format(Locale.ROOT, "будильник на %02d:%02d", h, min));
            }
            case "phone.timer": {
                Integer s = integer(arg);
                if (s == null || s <= 0 || s > 24 * 3600) {
                    return failed("нужно число секунд");
                }
                apis.timer(s);
                return done("таймер на " + s + " с");
            }
            case "phone.flashlight": {
                String a = str(arg).toLowerCase(Locale.ROOT);
                if (!a.equals("on") && !a.equals("off")) {
                    return failed("нужно on или off");
                }
                if (!apis.torch(a.equals("on"))) {
                    return new Result(UNSUPPORTED, "на телефоне нет вспышки");
                }
                return done(a.equals("on") ? "фонарик включён" : "фонарик выключен");
            }
            case "phone.volume": {
                Integer v = integer(arg);
                if (v == null || v < 0 || v > 100) {
                    return failed("нужна громкость 0–100");
                }
                apis.volume(v);
                return done("громкость " + v + "%");
            }
            case "phone.clipboard": {
                String t = str(arg);
                if (t.isEmpty()) {
                    return new Result(NOOP, "пустой текст");
                }
                apis.clipboard(t);
                return done("скопировано");
            }
            case "phone.open_url": {
                String u = str(arg);
                String low = u.toLowerCase(Locale.ROOT);
                if (!(low.startsWith("https://") || low.startsWith("http://"))) {
                    return failed("нужна ссылка http(s)");
                }
                apis.openUrl(u);
                return done("открыто");
            }
            case "phone.open_app": {
                String name = str(arg);
                if (name.isEmpty()) {
                    return failed("нужно название приложения");
                }
                PhoneApis.App app = AppMatcher.best(name, apis.launchableApps());
                if (app == null) {
                    return new Result(NOOP, "нет приложения «" + name + "»");
                }
                apis.launch(app);
                return done("открыто: " + app.label);
            }
            case "phone.media_play_pause":
                apis.mediaKey(KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE);
                return done("пауза/продолжить");
            case "phone.media_next":
                apis.mediaKey(KeyEvent.KEYCODE_MEDIA_NEXT);
                return done("следующий");
            case "phone.media_prev":
                apis.mediaKey(KeyEvent.KEYCODE_MEDIA_PREVIOUS);
                return done("предыдущий");
            case "phone.notify": {
                String t = str(arg);
                if (t.isEmpty()) {
                    return new Result(NOOP, "пустой текст");
                }
                apis.notify(t);
                return done("уведомление показано");
            }
            default:
                return new Result(UNSUPPORTED, "телефон не знает действие " + action);
        }
    }
}
