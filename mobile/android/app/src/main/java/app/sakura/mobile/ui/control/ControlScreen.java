package app.sakura.mobile.ui.control;

import android.view.LayoutInflater;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.android.material.button.MaterialButton;

import java.util.List;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.Models;

/** «Пульт»: карточки ПК, мини-плеер по track, кнопки action_run (device — выбранный ПК). */
public final class ControlScreen {

    public interface Callbacks {
        void select(String deviceId);

        /** action_run; arg — null без аргумента. */
        void run(String action, String arg);

        void openApp();

        void gameMode();

        void retry();
    }

    public static final class State {
        public Loadable<List<Models.Device>> devices = Loadable.loading();
        public String selected;
        public String note;
    }

    private final StateView state;
    private final LinearLayout pcs;
    private final TextView note;
    private final View player;
    private final TextView trackTitle;
    private final TextView trackArtist;
    private final MaterialButton play;
    private final Callbacks cb;

    public ControlScreen(View root, Callbacks cb) {
        this.cb = cb;
        state = root.findViewById(R.id.state);
        pcs = root.findViewById(R.id.pcs);
        note = root.findViewById(R.id.note);
        player = root.findViewById(R.id.player);
        trackTitle = root.findViewById(R.id.track_title);
        trackArtist = root.findViewById(R.id.track_artist);
        play = root.findViewById(R.id.m_play);
        state.setEmptyText("Нет компьютеров. Включите ПК с агентом Сакуры");
        state.setSection("список устройств");
        bind(root, R.id.m_play, "music.play_pause");
        bind(root, R.id.m_next, "music.next");
        bind(root, R.id.m_prev, "music.prev");
        bind(root, R.id.m_like, "music.like");
        bind(root, R.id.m_dislike, "music.dislike");
        bind(root, R.id.a_wave, "music.wave");
        bind(root, R.id.a_vol_down, "music.volume_down");
        bind(root, R.id.a_vol_up, "music.volume_up");
        bind(root, R.id.a_screenshot, "screenshot.run");
        bind(root, R.id.a_kettle_boil, "kettle.boil");
        bind(root, R.id.a_kettle_off, "kettle.off");
        bind(root, R.id.a_kettle_status, "kettle.status");
        bind(root, R.id.a_shutdown, "system.shutdown");
        bind(root, R.id.a_restart, "system.restart");
        bind(root, R.id.a_sleep, "power.sleep");
        root.findViewById(R.id.a_open_app).setOnClickListener(v -> cb.openApp());
        root.findViewById(R.id.a_game).setOnClickListener(v -> cb.gameMode());
    }

    private void bind(View root, int id, String action) {
        root.findViewById(id).setOnClickListener(v -> cb.run(action, null));
    }

    static String statsLine(Models.Device d) {
        StringBuilder sb = new StringBuilder();
        if (d.cpu != null) {
            sb.append("CPU ").append(d.cpu).append("%");
        }
        if (d.ram != null) {
            sb.append(sb.length() > 0 ? " · " : "").append("RAM ").append(d.ram).append("%");
        }
        if (d.gpu != null) {
            sb.append(sb.length() > 0 ? " · " : "").append("GPU ").append(d.gpu).append("%");
        }
        return sb.length() == 0 ? "нет данных" : sb.toString();
    }

    public void render(State s) {
        state.show(s.devices, cb::retry);
        note.setVisibility(s.note == null ? View.GONE : View.VISIBLE);
        note.setText(s.note);
        pcs.removeAllViews();
        Models.Device selected = null;
        if (s.devices.data != null) {
            LayoutInflater inf = LayoutInflater.from(pcs.getContext());
            for (Models.Device d : s.devices.data) {
                if (!d.isPc()) {
                    continue;
                }
                boolean sel = d.id.equals(s.selected);
                if (sel) {
                    selected = d;
                }
                View card = inf.inflate(R.layout.item_pc, pcs, false);
                card.findViewById(R.id.pc_dot).setBackgroundResource(
                        d.online ? R.drawable.bg_dot_online : R.drawable.bg_dot_offline);
                ((TextView) card.findViewById(R.id.pc_name)).setText(d.name);
                ((TextView) card.findViewById(R.id.pc_state)).setText(
                        !d.online ? "не в сети" : d.active ? "активный" : "в сети");
                ((TextView) card.findViewById(R.id.pc_stats)).setText(d.online ? statsLine(d) : "");
                card.setActivated(sel);
                card.setAlpha(sel ? 1f : 0.7f);
                card.setContentDescription(d.name + (sel ? ", выбран" : ""));
                card.setOnClickListener(v -> cb.select(d.id));
                pcs.addView(card);
            }
        }
        Models.Track t = selected == null ? null : selected.track;
        player.setVisibility(t == null ? View.GONE : View.VISIBLE);
        if (t != null) {
            trackTitle.setText(t.title);
            trackArtist.setText(t.artist + (t.status.isEmpty() ? "" : " · " + t.status));
            play.setIconResource(t.playing() ? R.drawable.ic_pause : R.drawable.ic_play);
        }
    }
}
