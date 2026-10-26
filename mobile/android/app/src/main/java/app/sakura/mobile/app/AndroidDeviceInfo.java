package app.sakura.mobile.app;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.BatteryManager;
import android.telephony.SignalStrength;
import android.telephony.TelephonyManager;

import org.json.JSONObject;

import app.sakura.mobile.proto.DeviceInfo;
import app.sakura.mobile.proto.Json;

/** Батарея, тип сети (без SSID) и уровень сигнала 0–4 для system_info.stats. */
public final class AndroidDeviceInfo implements DeviceInfo {
    private final Context context;
    private final InputTracker input;

    public AndroidDeviceInfo(Context context, InputTracker input) {
        this.context = context.getApplicationContext();
        this.input = input;
    }

    @Override
    public JSONObject stats() {
        BatteryManager bm = context.getSystemService(BatteryManager.class);
        int battery = bm == null ? -1 : bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
        boolean charging = bm != null && bm.isCharging();
        String net = "none";
        int signal = 0;
        ConnectivityManager cm = context.getSystemService(ConnectivityManager.class);
        Network active = cm == null ? null : cm.getActiveNetwork();
        NetworkCapabilities caps = active == null ? null : cm.getNetworkCapabilities(active);
        if (caps != null) {
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                net = "wifi";
                signal = wifiLevel(caps.getSignalStrength());
            } else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) {
                net = "cellular";
                signal = cellLevel();
            } else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) {
                net = "ethernet";
                signal = 4;
            } else {
                net = "other";
            }
        }
        return Json.obj("cpu", JSONObject.NULL, "ram", JSONObject.NULL, "gpu", JSONObject.NULL,
                "battery", battery >= 0 ? battery : JSONObject.NULL,
                "charging", charging, "wifi", net, "signal", signal);
    }

    /** RSSI (дБм) → 0–4. */
    static int wifiLevel(int rssi) {
        if (rssi == NetworkCapabilities.SIGNAL_STRENGTH_UNSPECIFIED || rssi >= 0) {
            return 0;
        }
        if (rssi >= -55) {
            return 4;
        }
        if (rssi >= -66) {
            return 3;
        }
        if (rssi >= -77) {
            return 2;
        }
        return rssi >= -88 ? 1 : 0;
    }

    private int cellLevel() {
        try {
            TelephonyManager tm = context.getSystemService(TelephonyManager.class);
            SignalStrength s = tm == null ? null : tm.getSignalStrength();
            return s == null ? 0 : Math.max(0, Math.min(4, s.getLevel()));
        } catch (SecurityException e) {
            return 0;
        }
    }

    @Override
    public double inputIdleSeconds() {
        return input.idleSeconds();
    }
}
