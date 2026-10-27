package app.sakura.mobile.ui.more;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import app.sakura.mobile.R;
import app.sakura.mobile.app.Permissions;
import app.sakura.mobile.ui.common.Rows;

/** «Ещё → Разрешения»: статус каждого разрешения и выдача по тапу. */
public class PermissionsFragment extends Fragment {
    private final ActivityResultLauncher<String> request = registerForActivityResult(
            new ActivityResultContracts.RequestPermission(), g -> refresh());

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_list, container, false);
    }

    /** Строки (без запросов) — и для снимков: granted[i] соответствует Permissions.ALL[i]. */
    public static void bind(View v, boolean[] granted, java.util.function.Consumer<Permissions.Entry> onTap) {
        ((TextView) v.findViewById(R.id.title)).setText("Разрешения");
        TextView sub = v.findViewById(R.id.subtitle);
        sub.setVisibility(View.VISIBLE);
        sub.setText("Без разрешения действие телефона отвечает «нет разрешения» и присылает уведомление со ссылкой сюда");
        LinearLayout rows = v.findViewById(R.id.rows);
        rows.removeAllViews();
        for (int i = 0; i < Permissions.ALL.size(); i++) {
            Permissions.Entry e = Permissions.ALL.get(i);
            View row = Rows.addWithDot(rows, e.title, e.why, granted[i] ? "выдано" : "выдать", granted[i]);
            if (onTap != null && !granted[i]) {
                row.setOnClickListener(x -> onTap.accept(e));
            }
        }
    }

    private void refresh() {
        View v = getView();
        if (v == null) {
            return;
        }
        boolean[] g = new boolean[Permissions.ALL.size()];
        for (int i = 0; i < g.length; i++) {
            g[i] = Permissions.granted(requireContext(), Permissions.ALL.get(i).kind);
        }
        bind(v, g, e -> {
            String p = Permissions.runtime(e.kind);
            if (p != null && !shouldShowRequestPermissionRationale(p) && !asked(p)) {
                markAsked(p);
                request.launch(p);
            } else {
                startActivity(Permissions.settingsIntent(requireContext(), e.kind));
            }
        });
    }

    private boolean asked(String p) {
        return requireContext().getSharedPreferences("perm", 0).getBoolean(p, false);
    }

    private void markAsked(String p) {
        requireContext().getSharedPreferences("perm", 0).edit().putBoolean(p, true).apply();
    }

    @Override
    public void onResume() {
        super.onResume();
        refresh();
    }
}
