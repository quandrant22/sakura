package app.sakura.mobile.ui.more;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.RadioGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.materialswitch.MaterialSwitch;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.app.Settings;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;

/** «Ещё → Интерфейс»: тема, подвижность, пресет слияния, «Убрать анимации», плавающее ядро. */
public class InterfaceFragment extends Fragment {

    /** Вызывается при включении плавающего ядра (M8: разрешение и запуск оверлея). */
    public interface FloatingCoreToggle {
        void setFloatingCore(boolean on);
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_interface, container, false);
    }

    public static void bind(View v, Settings s) {
        ((RadioGroup) v.findViewById(R.id.theme)).check(Settings.THEME_SKETCH.equals(s.theme())
                ? R.id.theme_sketch : R.id.theme_night);
        String m = s.mobility();
        ((RadioGroup) v.findViewById(R.id.mobility)).check("low".equals(m) ? R.id.mob_low
                : "high".equals(m) ? R.id.mob_high : R.id.mob_normal);
        String p = s.mergePreset();
        ((RadioGroup) v.findViewById(R.id.preset)).check("tight".equals(p) ? R.id.pre_tight
                : "liquid".equals(p) ? R.id.pre_liquid : R.id.pre_soft);
        ((MaterialSwitch) v.findViewById(R.id.reduce_motion)).setChecked(s.reduceMotion());
        ((MaterialSwitch) v.findViewById(R.id.floating_core)).setChecked(s.floatingCore());
        SakuraCoreView core = v.findViewById(R.id.preview_core);
        core.setMobility(CoreFrame.Mobility.of(m));
        core.setPreset(CoreFrame.MergePreset.of(p));
        core.setReduceMotion(s.reduceMotion());
        core.setState(CoreFrame.State.IDLE);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        Settings s = SakuraApp.get().settings();
        bind(view, s);
        ((RadioGroup) view.findViewById(R.id.theme)).setOnCheckedChangeListener((g, id) -> {
            String t = id == R.id.theme_sketch ? Settings.THEME_SKETCH : Settings.THEME_NIGHT;
            if (!t.equals(s.theme())) {
                s.setTheme(t);
                requireActivity().recreate();
            }
        });
        ((RadioGroup) view.findViewById(R.id.mobility)).setOnCheckedChangeListener((g, id) -> {
            s.setMobility(id == R.id.mob_low ? "low" : id == R.id.mob_high ? "high" : "normal");
            bind(view, s);
        });
        ((RadioGroup) view.findViewById(R.id.preset)).setOnCheckedChangeListener((g, id) -> {
            s.setMergePreset(id == R.id.pre_tight ? "tight" : id == R.id.pre_liquid ? "liquid" : "soft");
            bind(view, s);
        });
        ((MaterialSwitch) view.findViewById(R.id.reduce_motion)).setOnCheckedChangeListener((b, on) -> {
            s.setReduceMotion(on);
            ((SakuraCoreView) view.findViewById(R.id.preview_core)).setReduceMotion(on);
        });
        ((MaterialSwitch) view.findViewById(R.id.floating_core)).setOnCheckedChangeListener((b, on) -> {
            if (requireActivity() instanceof FloatingCoreToggle) {
                ((FloatingCoreToggle) requireActivity()).setFloatingCore(on);
            } else {
                s.setFloatingCore(on);
            }
        });
    }
}
