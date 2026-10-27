package app.sakura.mobile.exec;

import org.json.JSONObject;

import java.util.concurrent.Executor;
import java.util.function.Consumer;

import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.SakuraClient;

/**
 * Холодный путь command → исполнение → command_result. Подписан на шину клиента в Application,
 * не зависит от интерфейса, анимаций и озвучки. Команды не phone.* телефон не исполняет
 * (их исполняет активный ПК) — отвечает unsupported, чтобы сервер не ждал.
 *
 * Офлайн-путь: фраза без связи, совпавшая с триггером phone.*, выполняется локально.
 */
public final class CommandRouter {
    private final SakuraClient client;
    private final PhoneExecutor executor;
    private final OfflineMatcher matcher;
    private final Executor worker;

    public CommandRouter(SakuraClient client, PhoneExecutor executor, OfflineMatcher matcher, Executor worker) {
        this.client = client;
        this.executor = executor;
        this.matcher = matcher;
        this.worker = worker;
        client.bus().subscribe("command", this::onCommand);
    }

    void onCommand(JSONObject cmd) {
        String action = cmd.optString("action", "");
        if (!PhoneExecutor.handles(action)) {
            client.sendRaw(Json.obj("type", "command_result", "id", cmd.optString("id", ""), "ok", false,
                    "status", PhoneExecutor.UNSUPPORTED, "detail", "телефон не исполняет " + action));
            return;
        }
        worker.execute(() -> client.sendRaw(executor.onCommand(cmd)));
    }

    /**
     * Без связи: если фраза — действие телефона, выполнить сразу. Возвращает true, если фраза
     * обработана локально (тогда в outbox её не кладут, чтобы не выполнить дважды).
     */
    public boolean tryOffline(String phrase, Consumer<String> result) {
        if (client.status().conn == SakuraClient.Conn.ONLINE) {
            return false;
        }
        OfflineMatcher.Match m = matcher.match(phrase);
        if (m == null) {
            return false;
        }
        worker.execute(() -> {
            PhoneExecutor.Result r = executor.run(m.action, m.arg);
            result.accept("Без связи — на телефоне: " + r.detail);
        });
        return true;
    }
}
