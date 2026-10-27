package app.sakura.mobile.ui.more;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;

import androidx.activity.result.ActivityResultLauncher;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONObject;

import java.util.List;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.keys.DeviceKeyStore;
import app.sakura.mobile.pairing.PairingCodes;
import app.sakura.mobile.pairing.PairingSession;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.Motion;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.model.Models;

/** «Ещё → Безопасность». Спаривание: QR (ZXing) со сверкой k, или адрес + 8 слов вручную. */
public class SecurityFragment extends Fragment {
    private SecurityScreen screen;
    private Runnable unsubscribe;
    private final ActivityResultLauncher<ScanOptions> scan = registerForActivityResult(new ScanContract(), r -> {
        if (r.getContents() != null) {
            onQr(r.getContents());
        }
    });

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_security, container, false);
    }

    static SecurityScreen.Info info(SakuraApp app, SakuraClient.Status st) {
        SecurityScreen.Info i = new SecurityScreen.Info();
        DeviceKeyStore.Server s = app.keys().server();
        i.paired = s != null;
        if (s != null) {
            i.url = s.url;
            i.fingerprint = s.fingerprint();
            i.deviceId = s.deviceId;
        }
        i.connection = st.conn == SakuraClient.Conn.ONLINE ? "онлайн (Noise)" : "нет связи";
        i.alwaysOn = app.settings().alwaysOn();
        return i;
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        SakuraApp app = SakuraApp.get();
        screen = new SecurityScreen(view, this::loadDevices);
        unsubscribe = app.client().onStatus(st -> view.post(() -> screen.renderInfo(info(app, st))));
        screen.alwaysOnSwitch().setOnCheckedChangeListener((b, on) -> {
            if (on != app.settings().alwaysOn()) {
                app.setAlwaysOn(on);
            }
        });
        view.findViewById(R.id.pair_qr).setOnClickListener(v -> scan.launch(new ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Наведите на QR из Telegram (/pair)")
                .setBeepEnabled(false)
                .setOrientationLocked(true)));
        view.findViewById(R.id.pair_manual).setOnClickListener(v -> manual());
        view.findViewById(R.id.forget).setOnClickListener(v -> new MaterialAlertDialogBuilder(requireContext())
                .setTitle("Забыть сервер?")
                .setMessage("Ключ устройства и ключ сервера будут удалены. Чтобы снова подключиться, нужно спарить телефон заново (/pair).")
                .setPositiveButton("Забыть", (d, w) -> {
                    Motion.confirm(v);
                    app.client().forget();
                })
                .setNegativeButton("Отмена", null)
                .show());
        loadDevices();
    }

    @Override
    public void onDestroyView() {
        if (unsubscribe != null) {
            unsubscribe.run();
        }
        super.onDestroyView();
    }

    private void post(Runnable r) {
        View v = getView();
        if (v != null) {
            v.post(r);
        }
    }

    private void loadDevices() {
        screen.renderDevices(Loadable.loading());
        SakuraApp.get().client().request(Json.obj("type", "secure_devices"), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                List<Models.SecureDevice> list = Models.list(Json.optArr(r, "devices"), Models.SecureDevice::of);
                post(() -> screen.renderDevices(list.isEmpty() ? Loadable.empty() : Loadable.ready(list)));
            }

            @Override
            public void onError(ApiError e) {
                post(() -> screen.renderDevices(Loadable.failed(e)));
            }
        });
    }

    private void onQr(String text) {
        try {
            PairingCodes.QrPayload qr = PairingCodes.parseQrUri(text, System.currentTimeMillis() / 1000);
            start(s -> s.startFromQr(qr));
        } catch (PairingCodes.PairingException e) {
            result(e.getMessage(), false);
        }
    }

    private void manual() {
        LinearLayout box = new LinearLayout(requireContext());
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = getResources().getDimensionPixelSize(R.dimen.edge);
        box.setPadding(pad, 0, pad, 0);
        EditText url = new EditText(requireContext());
        url.setHint("ws://адрес:8765");
        EditText words = new EditText(requireContext());
        words.setHint("8 слов через пробел");
        box.addView(url);
        box.addView(words);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle("Спаривание вручную")
                .setView(box)
                .setPositiveButton("Спарить", (d, w) -> start(s ->
                        s.startManual(url.getText().toString().trim(), words.getText().toString())))
                .setNegativeButton("Отмена", null)
                .show();
    }

    private void start(java.util.function.Consumer<PairingSession> how) {
        SakuraApp app = SakuraApp.get();
        app.client().stop();
        PairingSession session = new PairingSession(app.http(), app.keys(), app.net(), new PairingSession.Callback() {
            @Override
            public void onPaired(DeviceKeyStore.Server server, String fingerprint) {
                post(() -> {
                    result("Спарено. Сверьте отпечаток с Telegram:\n\n" + fingerprint, true);
                    app.client().start();
                    screen.renderInfo(info(app, app.client().status()));
                });
            }

            @Override
            public void onFailed(String message) {
                post(() -> {
                    result(message, false);
                    app.client().start();
                });
            }
        });
        how.accept(session);
    }

    private void result(String text, boolean ok) {
        View v = getView();
        if (v != null) {
            if (ok) {
                Motion.confirm(v);
            } else {
                Motion.reject(v);
            }
        }
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(ok ? "Готово" : "Не удалось спарить")
                .setMessage(text)
                .setPositiveButton("OK", null)
                .show();
    }
}
