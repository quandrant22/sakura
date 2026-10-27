package app.sakura.mobile.ui.more;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import org.json.JSONObject;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.ApiError;
import app.sakura.mobile.proto.ErrorText;
import app.sakura.mobile.proto.Json;
import app.sakura.mobile.proto.RequestClient;
import app.sakura.mobile.ui.common.Loadable;

/** «Ещё → Профиль». */
public class ProfileFragment extends Fragment {
    private ProfileScreen screen;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.screen_profile, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        screen = new ProfileScreen(view, this::save, this::load);
        load();
    }

    private void post(Runnable r) {
        View v = getView();
        if (v != null) {
            v.post(r);
        }
    }

    private void load() {
        screen.render(Loadable.loading());
        SakuraApp.get().client().request(Json.obj("type", "profile_get"), new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                JSONObject p = Json.optObj(r, "profile");
                post(() -> screen.render(p == null ? Loadable.empty() : Loadable.ready(p)));
            }

            @Override
            public void onError(ApiError e) {
                post(() -> screen.render(Loadable.failed(e)));
            }
        });
    }

    private void save(JSONObject profile) {
        JSONObject m = Json.obj("type", "profile_set");
        java.util.Iterator<String> keys = profile.keys();
        while (keys.hasNext()) {
            String k = keys.next();
            Json.put(m, k, profile.opt(k));
        }
        SakuraApp.get().client().request(m, new RequestClient.Callback() {
            @Override
            public void onResult(JSONObject r) {
                post(() -> screen.note("Сохранено"));
            }

            @Override
            public void onError(ApiError e) {
                post(() -> screen.note(ErrorText.text(e, "изменение профиля")));
            }
        });
    }
}
