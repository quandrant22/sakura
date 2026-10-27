package app.sakura.mobile.assistant;

import android.Manifest;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.service.voice.VoiceInteractionSession;
import android.view.ContextThemeWrapper;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.TextView;

import androidx.lifecycle.Observer;

import app.sakura.mobile.R;
import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.core.CoreFrame;
import app.sakura.mobile.core.SakuraCoreView;
import app.sakura.mobile.ui.MainActivity;
import app.sakura.mobile.ui.dialog.ChatScreen;
import app.sakura.mobile.voice.VoiceController;

/**
 * Панель ассистента (долгое нажатие питания): ядро, статус, живой транскрипт, ответ Сакуры.
 * На экране блокировки — только голос и ответ (кнопки «Открыть» нет, чат не показывается).
 */
public class SakuraSession extends VoiceInteractionSession {
    static final long LINGER_MS = 30_000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private SakuraCoreView core;
    private TextView status;
    private TextView transcript;
    private TextView reply;
    private View openApp;
    private boolean temporaryLink;
    private final Observer<CoreFrame.State> onState = s -> {
        core.setState(s);
        status.setText(ChatScreen.statusText(s));
    };
    private final Observer<String> onTranscript = t -> transcript.setText(t);
    private final Observer<String> onReply = t -> reply.setText(t);
    private final Runnable levelPump = new Runnable() {
        @Override
        public void run() {
            core.setLevel(SakuraApp.get().voice().level());
            core.postOnAnimation(this);
        }
    };
    private final Runnable dropLink = () -> {
        SakuraApp app = SakuraApp.get();
        if (temporaryLink && !app.inForeground() && !app.settings().alwaysOn()) {
            app.client().stop();
        }
    };

    public SakuraSession(Context context) {
        super(context);
    }

    @Override
    public View onCreateContentView() {
        Context themed = new ContextThemeWrapper(getContext(), R.style.Theme_Sakura_Night);
        View v = LayoutInflater.from(themed).inflate(R.layout.assistant_panel, null);
        core = v.findViewById(R.id.core);
        status = v.findViewById(R.id.status);
        transcript = v.findViewById(R.id.transcript);
        reply = v.findViewById(R.id.reply);
        openApp = v.findViewById(R.id.open_app);
        VoiceController voice = SakuraApp.get().voice();
        core.setOnClickListener(x -> listen());
        v.findViewById(R.id.mic).setOnClickListener(x -> listen());
        openApp.setOnClickListener(x -> {
            startAssistantActivity(new Intent(getContext(), MainActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP));
            hide();
        });
        v.setOnClickListener(x -> hide());   // тап мимо панели — закрыть
        v.findViewById(R.id.panel).setOnClickListener(x -> { });
        reply.setText("");
        return v;
    }

    static boolean locked(Context c) {
        KeyguardManager km = c.getSystemService(KeyguardManager.class);
        return km != null && km.isKeyguardLocked();
    }

    @Override
    public void onShow(Bundle args, int showFlags) {
        super.onShow(args, showFlags);
        SakuraApp app = SakuraApp.get();
        main.removeCallbacks(dropLink);
        temporaryLink = !app.settings().alwaysOn() && !app.inForeground();
        app.client().start();
        VoiceController voice = app.voice();
        voice.setAssistantSession(true);
        voice.state().observeForever(onState);
        voice.transcript().observeForever(onTranscript);
        voice.lastReply().observeForever(onReply);
        reply.setText("");
        openApp.setVisibility(locked(getContext()) ? View.GONE : View.VISIBLE);
        core.postOnAnimation(levelPump);
        listen();
    }

    private void listen() {
        if (getContext().checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            reply.setText("Разрешите микрофон: откройте Сакуру → Ещё → Разрешения");
            return;
        }
        SakuraApp.get().voice().listenForAssistant();
    }

    @Override
    public void onHide() {
        VoiceController voice = SakuraApp.get().voice();
        voice.setAssistantSession(false);
        voice.state().removeObserver(onState);
        voice.transcript().removeObserver(onTranscript);
        voice.lastReply().removeObserver(onReply);
        if (core != null) {
            core.removeCallbacks(levelPump);
        }
        main.postDelayed(dropLink, LINGER_MS);
        super.onHide();
    }
}
