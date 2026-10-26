package app.sakura.mobile.proto;

import org.json.JSONObject;

/** Что телефон сообщает в register/ping. */
public interface DeviceInfo {
    /** system_info.stats: battery, charging, wifi (тип сети без SSID), signal 0–4. */
    JSONObject stats();

    /** Секунд с последнего ввода Мастера в приложении (≥ 0). */
    double inputIdleSeconds();
}
