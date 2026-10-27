package app.sakura.mobile.ui.more;

import android.view.View;
import android.widget.EditText;
import android.widget.TextView;

import com.google.android.material.materialswitch.MaterialSwitch;

import org.json.JSONObject;

import java.util.function.Consumer;

import app.sakura.mobile.R;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.StateView;

/** «Профиль»: profile_get / profile_set (name, address_as, quiet_hours, voice, tone, notifications). */
public final class ProfileScreen {
    private final StateView state;
    private final EditText name;
    private final EditText address;
    private final EditText quiet;
    private final EditText voice;
    private final EditText tone;
    private final MaterialSwitch telegram;
    private final MaterialSwitch sound;
    private final TextView note;

    public ProfileScreen(View root, Consumer<JSONObject> save, Runnable retry) {
        state = root.findViewById(R.id.state);
        name = root.findViewById(R.id.p_name);
        address = root.findViewById(R.id.p_address);
        quiet = root.findViewById(R.id.p_quiet);
        voice = root.findViewById(R.id.p_voice);
        tone = root.findViewById(R.id.p_tone);
        telegram = root.findViewById(R.id.p_telegram);
        sound = root.findViewById(R.id.p_sound);
        note = root.findViewById(R.id.note);
        state.setSection("профиль");
        state.setEmptyText("Профиль пуст");
        root.findViewById(R.id.save).setOnClickListener(v -> save.accept(collect()));
        this.retry = retry;
    }

    private final Runnable retry;

    JSONObject collect() {
        return Json.obj("name", name.getText().toString().trim(),
                "address_as", address.getText().toString().trim(),
                "quiet_hours", quiet.getText().toString().trim(),
                "voice", voice.getText().toString().trim(),
                "tone", tone.getText().toString().trim(),
                "notifications", Json.obj("telegram", telegram.isChecked(), "sound", sound.isChecked()));
    }

    public void render(Loadable<JSONObject> l) {
        state.show(l, retry);
        if (l.data == null) {
            return;
        }
        JSONObject p = l.data;
        name.setText(p.optString("name"));
        address.setText(p.optString("address_as"));
        quiet.setText(p.optString("quiet_hours"));
        voice.setText(p.optString("voice"));
        tone.setText(p.optString("tone"));
        JSONObject n = Json.optObj(p, "notifications");
        telegram.setChecked(n != null && n.optBoolean("telegram", true));
        sound.setChecked(n != null && n.optBoolean("sound", true));
    }

    public void note(String text) {
        note.setVisibility(text == null ? View.GONE : View.VISIBLE);
        note.setText(text);
    }
}
