package app.sakura.mobile.ui.scenarios;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.AutoCompleteTextView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.common.Loadable;
import app.sakura.mobile.ui.common.Rows;
import app.sakura.mobile.ui.common.StateView;
import app.sakura.mobile.ui.model.ActionCatalog;
import app.sakura.mobile.ui.model.Models;

/** Конструктор «Если … То …» (пары условие/действие) и «Из фразы» с предпросмотром. */
public final class BuilderScreen {

    public interface Callbacks {
        void preview(String phrase);

        void save(Models.Scenario s);
    }

    private final Context context;
    private final EditText name;
    private final LinearLayout pairs;
    private final EditText phrase;
    private final StateView previewState;
    private final LinearLayout preview;
    private final TextView note;
    private final List<String> actionIds = new ArrayList<>();
    private final List<String> actionLabels = new ArrayList<>();
    private Models.Scenario previewed;

    public BuilderScreen(View root, ActionCatalog catalog, Callbacks cb) {
        context = root.getContext();
        name = root.findViewById(R.id.name);
        pairs = root.findViewById(R.id.pairs);
        phrase = root.findViewById(R.id.phrase);
        previewState = root.findViewById(R.id.preview_state);
        preview = root.findViewById(R.id.preview);
        note = root.findViewById(R.id.note);
        previewState.setSection("сценарии из фразы");
        for (ActionCatalog.Action a : catalog.actions) {
            actionIds.add(a.id);
            actionLabels.add(a.toString());
        }
        addPair("phrase", "", "action", "");
        root.findViewById(R.id.add_pair).setOnClickListener(v -> addPair("time", "", "action", ""));
        root.findViewById(R.id.preview_btn).setOnClickListener(v -> {
            String p = phrase.getText().toString().trim();
            if (!p.isEmpty()) {
                cb.preview(p);
            }
        });
        root.findViewById(R.id.save).setOnClickListener(v -> {
            Models.Scenario s = previewed != null && pairsEmpty() ? previewed : collect();
            if (s.name.isEmpty()) {
                showNote("Назовите сценарий");
            } else if (s.actions.isEmpty()) {
                showNote("Нужно хотя бы одно действие");
            } else {
                cb.save(s);
            }
        });
    }

    private static ArrayAdapter<String> adapter(Context c, String[] items) {
        ArrayAdapter<String> a = new ArrayAdapter<>(c, android.R.layout.simple_spinner_item, items);
        a.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        return a;
    }

    void addPair(String cond, String condValue, String act, String actValue) {
        View row = LayoutInflater.from(context).inflate(R.layout.item_pair, pairs, false);
        Spinner ct = row.findViewById(R.id.cond_type);
        Spinner at = row.findViewById(R.id.act_type);
        ct.setAdapter(adapter(context, ScenarioTypes.CONDITION_LABELS));
        at.setAdapter(adapter(context, ScenarioTypes.ACTION_LABELS));
        ct.setSelection(ScenarioTypes.index(ScenarioTypes.CONDITION_IDS, cond));
        at.setSelection(ScenarioTypes.index(ScenarioTypes.ACTION_IDS, act));
        ((EditText) row.findViewById(R.id.cond_value)).setText(condValue);
        AutoCompleteTextView av = row.findViewById(R.id.act_value);
        av.setText(actValue);
        av.setAdapter(new ArrayAdapter<>(context, android.R.layout.simple_dropdown_item_1line, actionLabels));
        av.setOnItemClickListener((p, v, pos, id) -> {
            String label = (String) p.getItemAtPosition(pos);
            int i = actionLabels.indexOf(label);
            av.setText(i >= 0 ? actionIds.get(i) : label);
        });
        at.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                av.setHint("action".equals(ScenarioTypes.ACTION_IDS[position]) ? "действие, например phone.dnd_on"
                        : "pause".equals(ScenarioTypes.ACTION_IDS[position]) ? "секунды" : "текст");
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        pairs.addView(row);
    }

    private boolean pairsEmpty() {
        Models.Scenario s = collect();
        return s.actions.isEmpty() && s.conditions.isEmpty();
    }

    Models.Scenario collect() {
        List<Models.Step> conds = new ArrayList<>();
        List<Models.Step> acts = new ArrayList<>();
        for (int i = 0; i < pairs.getChildCount(); i++) {
            View row = pairs.getChildAt(i);
            String cv = ((EditText) row.findViewById(R.id.cond_value)).getText().toString().trim();
            String av = ((EditText) row.findViewById(R.id.act_value)).getText().toString().trim();
            int ci = ((Spinner) row.findViewById(R.id.cond_type)).getSelectedItemPosition();
            int ai = ((Spinner) row.findViewById(R.id.act_type)).getSelectedItemPosition();
            if (!cv.isEmpty()) {
                conds.add(new Models.Step(ScenarioTypes.CONDITION_IDS[Math.max(0, ci)], cv));
            }
            if (!av.isEmpty()) {
                acts.add(new Models.Step(ScenarioTypes.ACTION_IDS[Math.max(0, ai)], av));
            }
        }
        return new Models.Scenario(null, name.getText().toString().trim(), true, false, conds, acts);
    }

    public void showNote(String text) {
        note.setVisibility(text == null ? View.GONE : View.VISIBLE);
        note.setText(text);
    }

    /** Предпросмотр сценария из фразы (не сохраняется, пока не нажать «Сохранить»). */
    public void renderPreview(Loadable<Models.Scenario> l, List<String> warnings, Runnable retry) {
        previewState.setVisibility(View.VISIBLE);
        previewState.show(l, retry);
        preview.removeAllViews();
        previewed = l.data;
        if (l.data == null) {
            return;
        }
        Models.Scenario s = l.data;
        Rows.add(preview, s.name, null, null);
        for (Models.Step c : s.conditions) {
            Rows.add(preview, "Если " + ScenarioTypes.conditionLabel(c.type).toLowerCase(java.util.Locale.ROOT)
                    + ": " + c.value, null, null);
        }
        for (Models.Step a : s.actions) {
            Rows.add(preview, "→ " + ScenarioTypes.actionLabel(a.type) + ": " + a.value, null, null);
        }
        if (warnings != null) {
            for (String w : warnings) {
                Rows.hint(preview, w);
            }
        }
        if (name.getText().toString().trim().isEmpty()) {
            name.setText(s.name);
        }
    }
}
