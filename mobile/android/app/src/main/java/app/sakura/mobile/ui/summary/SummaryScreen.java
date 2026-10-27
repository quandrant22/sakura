package app.sakura.mobile.ui.summary;

import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.Rows;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.Models;

/** «Сводка»: status_request, устройства (с батареей телефона), scenario_event, последние ответы. */
public final class SummaryScreen {

    public static final class Status {
        public final String mode;
        public final String tone;
        public final String quote;

        public Status(String mode, String tone, String quote) {
            this.mode = mode;
            this.tone = tone;
            this.quote = quote;
        }
    }

    public static final class Data {
        public Status status;
        public List<Models.Device> devices = new ArrayList<>();
        public List<String> events = new ArrayList<>();
        public List<Models.Message> replies = new ArrayList<>();
    }

    private final StateView state;
    private final TextView mode;
    private final TextView quote;
    private final LinearLayout devices;
    private final LinearLayout events;
    private final LinearLayout replies;
    private final Runnable retry;

    public SummaryScreen(View root, Runnable retry) {
        this.retry = retry;
        state = root.findViewById(R.id.state);
        mode = root.findViewById(R.id.status_mode);
        quote = root.findViewById(R.id.status_quote);
        devices = root.findViewById(R.id.devices);
        events = root.findViewById(R.id.events);
        replies = root.findViewById(R.id.replies);
        state.setEmptyText("Сервер пока ничего не сообщил");
        state.setSection("сводку");
    }

    static String deviceSub(Models.Device d) {
        if (!d.online) {
            return "не в сети";
        }
        StringBuilder sb = new StringBuilder(d.active ? "активный" : "в сети");
        if (d.battery != null) {
            sb.append(" · батарея ").append(d.battery).append('%').append(d.charging ? " ⚡" : "");
        }
        return sb.toString();
    }

    public void render(Loadable<Data> l) {
        state.show(l, retry);
        devices.removeAllViews();
        events.removeAllViews();
        replies.removeAllViews();
        if (l.data == null) {
            return;
        }
        Data d = l.data;
        if (d.status != null) {
            mode.setText("Режим: " + d.status.mode + (d.status.tone.isEmpty() ? "" : " · тон " + d.status.tone));
            quote.setText(d.status.quote);
        } else {
            mode.setText("Статус недоступен");
            quote.setText("");
        }
        if (d.devices.isEmpty()) {
            Rows.hint(devices, "Нет устройств");
        }
        for (Models.Device dev : d.devices) {
            Rows.addWithDot(devices, dev.name, deviceSub(dev), dev.isPc() ? "ПК" : "", dev.online);
        }
        if (d.events.isEmpty()) {
            Rows.hint(events, "Запусков пока не было");
        }
        for (String e : d.events) {
            Rows.add(events, e, null, null);
        }
        if (d.replies.isEmpty()) {
            Rows.hint(replies, "Ответов пока нет");
        }
        for (Models.Message m : d.replies) {
            Rows.add(replies, m.text, m.label(), Models.time(m.ts));
        }
    }
}
