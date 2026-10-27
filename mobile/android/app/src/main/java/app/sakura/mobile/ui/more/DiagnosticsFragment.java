package app.sakura.mobile.ui.more;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import app.sakura.mobile.BuildConfig;
import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.link.CloseCodes;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.common.Rows;

/**
 * «Ещё → Диагностика»: только метрики и состояния — без содержимого приватных классов
 * (никаких текстов чата, памяти, профиля, ключей).
 */
public class DiagnosticsFragment extends Fragment {
    private Runnable unsubscribe;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_list, container, false);
    }

    /** Пары «название — значение». */
    public static List<String[]> rows(SakuraClient.Status s, int outbox, int gaps, boolean onDevice,
                                      boolean model, long coreDrawNanos) {
        List<String[]> r = new ArrayList<>();
        r.add(new String[]{"Связь", s.conn.name().toLowerCase(Locale.ROOT)});
        r.add(new String[]{"Протокол", s.proto == 0 ? "—" : "proto " + s.proto});
        r.add(new String[]{"Права master", s.master ? "да" : "нет"});
        r.add(new String[]{"Последнее закрытие", s.closeCode == 0 ? "—" : s.closeCode + " · " + CloseCodes.describe(s.closeCode)});
        r.add(new String[]{"Очередь реплик", String.valueOf(outbox)});
        r.add(new String[]{"Разрывы озвучки", String.valueOf(gaps)});
        r.add(new String[]{"Распознавание", onDevice ? "на устройстве" : "системное"});
        r.add(new String[]{"Модель «Сакура»", model ? "установлена" : "нет"});
        r.add(new String[]{"Кадр ядра", coreDrawNanos == 0 ? "—"
                : String.format(Locale.ROOT, "%.2f мс", coreDrawNanos / 1e6)});
        r.add(new String[]{"Версия", BuildConfig.VERSION_NAME + " (" + BuildConfig.VERSION_CODE + ")"});
        return r;
    }

    public static void bind(View v, List<String[]> rows) {
        ((TextView) v.findViewById(R.id.title)).setText("Диагностика");
        LinearLayout box = v.findViewById(R.id.rows);
        box.removeAllViews();
        for (String[] kv : rows) {
            Rows.add(box, kv[0], null, kv[1]);
        }
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        SakuraApp app = SakuraApp.get();
        unsubscribe = app.client().onStatus(s -> view.post(() -> bind(view, rows(s, app.client().outboxSize(),
                app.voice().playbackGaps(), app.voice().onDeviceRecognition(), app.voice().models().installed(),
                SakuraCoreView.lastDrawNanos()))));
    }

    @Override
    public void onDestroyView() {
        if (unsubscribe != null) {
            unsubscribe.run();
        }
        super.onDestroyView();
    }
}
