package app.sakura.mobile.tile;

import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

import app.sakura.mobile.app.SakuraApp;
import app.sakura.mobile.proto.SakuraClient;
import app.sakura.mobile.ui.MainActivity;

/** Плитка «Сакура»: нажатие открывает приложение и сразу слушает. Подпись — состояние связи. */
public class ListenTileService extends TileService {

    @Override
    public void onStartListening() {
        Tile t = getQsTile();
        if (t == null) {
            return;
        }
        SakuraClient.Status s = SakuraApp.get().client().status();
        t.setState(s.conn == SakuraClient.Conn.ONLINE ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        t.setSubtitle(s.conn == SakuraClient.Conn.ONLINE ? "Говорить" : "Нет связи");
        t.updateTile();
    }

    @Override
    public void onClick() {
        Intent i = new Intent(this, MainActivity.class).setAction(MainActivity.ACTION_LISTEN)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 10, i,
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        } else {
            startActivityAndCollapseCompat(i);
        }
    }

    /** Android 13 (minSdk 33): варианта с PendingIntent ещё нет. */
    @SuppressWarnings("deprecation")
    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated")
    private void startActivityAndCollapseCompat(Intent i) {
        startActivityAndCollapse(i);
    }
}
