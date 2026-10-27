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

import java.util.function.Supplier;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.MainActivity;
import app.sakura.mobile.ui.common.Rows;

/** Вкладка «Ещё»: Память, Профиль, Голос, Безопасность, Интерфейс, Разрешения, Диагностика. */
public class MoreFragment extends Fragment {
    static final String[][] ITEMS = {
            {"Память", "что Сакура о вас знает"},
            {"Профиль", "имя, обращение, тихие часы"},
            {"Голос", "ответы текстом, «Сакура», дослушивание"},
            {"Безопасность", "спаривание, отпечаток, устройства"},
            {"Интерфейс", "тема, подвижность, слияние"},
            {"Разрешения", "микрофон, уведомления, камера"},
            {"Диагностика", "состояние связи и звука"},
    };

    @SuppressWarnings("unchecked")
    static final Supplier<Fragment>[] SCREENS = new Supplier[]{
            MemoryFragment::new, ProfileFragment::new, VoiceSettingsFragment::new, SecurityFragment::new,
            InterfaceFragment::new, PermissionsFragment::new, DiagnosticsFragment::new,
    };

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_list, container, false);
    }

    public static void bind(View v, java.util.function.IntConsumer onTap) {
        ((TextView) v.findViewById(R.id.title)).setText("Ещё");
        LinearLayout rows = v.findViewById(R.id.rows);
        rows.removeAllViews();
        for (int i = 0; i < ITEMS.length; i++) {
            View row = Rows.add(rows, ITEMS[i][0], ITEMS[i][1], "›");
            int idx = i;
            if (onTap != null) {
                row.setOnClickListener(x -> onTap.accept(idx));
            }
        }
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        bind(view, i -> ((MainActivity) requireActivity()).push(SCREENS[i].get()));
    }
}
