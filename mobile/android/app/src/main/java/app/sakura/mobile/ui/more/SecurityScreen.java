package app.sakura.mobile.ui.more;

import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.android.material.materialswitch.MaterialSwitch;

import java.util.List;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.Rows;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.Models;

/** «Безопасность»: сервер и отпечаток §8.1, спаривание, secure_devices, «Забыть сервер». */
public final class SecurityScreen {

    public static final class Info {
        public boolean paired;
        public String url;
        public String fingerprint;
        public String deviceId;
        public String connection;
        public boolean alwaysOn;
    }

    private final TextView serverState;
    private final TextView serverUrl;
    private final TextView serverFp;
    private final MaterialSwitch alwaysOn;
    private final StateView devicesState;
    private final LinearLayout devices;
    private final View forget;
    private final Runnable retry;

    public SecurityScreen(View root, Runnable retry) {
        this.retry = retry;
        serverState = root.findViewById(R.id.server_state);
        serverUrl = root.findViewById(R.id.server_url);
        serverFp = root.findViewById(R.id.server_fp);
        alwaysOn = root.findViewById(R.id.always_on);
        devicesState = root.findViewById(R.id.devices_state);
        devices = root.findViewById(R.id.devices);
        forget = root.findViewById(R.id.forget);
        devicesState.setSection("список устройств");
        devicesState.setEmptyText("Устройств нет");
    }

    public MaterialSwitch alwaysOnSwitch() {
        return alwaysOn;
    }

    public void renderInfo(Info i) {
        if (!i.paired) {
            serverState.setText("Не спарено");
            serverUrl.setText("Получите QR или 8 слов командой /pair в Telegram");
            serverFp.setText("");
        } else {
            serverState.setText("Сервер · " + i.connection);
            serverUrl.setText(i.url + " · устройство " + i.deviceId);
            serverFp.setText("Отпечаток ключа: " + i.fingerprint);
        }
        forget.setVisibility(i.paired ? View.VISIBLE : View.GONE);
        alwaysOn.setChecked(i.alwaysOn);
    }

    public void renderDevices(Loadable<List<Models.SecureDevice>> l) {
        devicesState.show(l, retry);
        devices.removeAllViews();
        if (l.data == null) {
            return;
        }
        for (Models.SecureDevice d : l.data) {
            String sub = "отпечаток " + d.fingerprint + (d.secureNow ? " · Noise" : "") + (d.revoked ? " · отозван" : "");
            Rows.addWithDot(devices, d.name + (d.current ? " (это устройство)" : ""), sub, null, d.online);
        }
    }
}
