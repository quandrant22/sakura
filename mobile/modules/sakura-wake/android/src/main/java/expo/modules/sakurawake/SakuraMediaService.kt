package expo.modules.sakurawake

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.SimpleBasePlayer
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.CommandButton
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Collections

data class SakuraMediaPayload(
  val trackId: String,
  val title: String,
  val artist: String,
  val album: String,
  val artworkUrl: String?,
  val durationMs: Long,
  val positionMs: Long,
  val updatedAtElapsedMs: Long,
  val isPlaying: Boolean,
  val isLiked: Boolean,
  val hasPrev: Boolean,
  val hasNext: Boolean,
)

object SakuraMediaBus {
  const val ACTION_PREVIOUS = "expo.modules.sakurawake.MEDIA_PREVIOUS"
  const val ACTION_NEXT = "expo.modules.sakurawake.MEDIA_NEXT"
  const val ACTION_TOGGLE_LIKE = "expo.modules.sakurawake.MEDIA_TOGGLE_LIKE"
  const val EXTRA_COMMAND = "sakura_cmd"
  const val CMD_UPDATE = "update"
  const val CMD_CLEAR = "clear"

  @Volatile
  var current: SakuraMediaPayload? = null

  @Volatile
  var serviceRef: SakuraMediaService? = null

  @Volatile
  var actionListener: ((action: String, positionMs: Long) -> Unit)? = null

  fun update(context: Context, payload: SakuraMediaPayload) {
    val hadTrack = current != null
    current = payload
    val svc = serviceRef
    if (svc != null) {
      svc.syncFromBus()
      return
    }
    val intent = Intent(context, SakuraMediaService::class.java).apply {
      putExtra(EXTRA_COMMAND, CMD_UPDATE)
    }
    try {
      if (!hadTrack) {
        ContextCompat.startForegroundService(context, intent)
      } else {
        ContextCompat.startForegroundService(context, intent)
      }
    } catch (_: Exception) {
      try {
        context.startService(intent)
      } catch (_: Exception) {}
    }
  }

  fun clear(context: Context) {
    current = null
    val svc = serviceRef
    if (svc != null) {
      svc.stopServiceCleanly()
    } else {
      try {
        context.stopService(Intent(context, SakuraMediaService::class.java))
      } catch (_: Exception) {}
    }
  }

  fun emitAction(action: String, positionMs: Long = 0L) {
    actionListener?.invoke(action, positionMs)
  }
}

@OptIn(UnstableApi::class)
class SakuraMediaService : MediaSessionService() {
  private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
  private var mediaSession: MediaSession? = null
  private var bridgePlayer: BridgePlayer? = null
  private val artworkCache: MutableMap<String, ByteArray> = Collections.synchronizedMap(
    object : LinkedHashMap<String, ByteArray>(24, 0.75f, true) {
      override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, ByteArray>?): Boolean {
        return size > 24
      }
    }
  )
  private var loadingArtUrl: String? = null
  private var artJob: Job? = null
  private var foregroundStarted = false

  override fun onCreate() {
    super.onCreate()
    SakuraMediaBus.serviceRef = this
    ensureMediaChannel()

    val provider = DefaultMediaNotificationProvider.Builder(this)
      .setChannelId(MEDIA_CHANNEL_ID)
      .setNotificationId(MEDIA_NOTIFICATION_ID)
      .build()
    provider.setSmallIcon(R.drawable.ic_sakura_notif)
    setMediaNotificationProvider(provider)
    setShowNotificationForIdlePlayer(SHOW_NOTIFICATION_FOR_IDLE_PLAYER_ALWAYS)

    val player = BridgePlayer()
    bridgePlayer = player

    val openMusicIntent = Intent(Intent.ACTION_VIEW, Uri.parse("sakura:///(tabs)/music")).apply {
      setPackage(packageName)
      addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    }
    val sessionActivity = PendingIntent.getActivity(
      this,
      101,
      openMusicIntent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    val session = MediaSession.Builder(this, player)
      .setId("SakuraMusicSession")
      .setSessionActivity(sessionActivity)
      .setCallback(SessionCallback())
      .build()

    mediaSession = session
    addSession(session)
    syncFromBus()
  }

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (!foregroundStarted) {
      ensureImmediateForeground()
    }
    when (intent?.getStringExtra(SakuraMediaBus.EXTRA_COMMAND)) {
      SakuraMediaBus.CMD_CLEAR -> {
        stopServiceCleanly()
        return START_NOT_STICKY
      }
      else -> syncFromBus()
    }
    return super.onStartCommand(intent, flags, startId)
  }

  override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

  override fun onDestroy() {
    SakuraMediaBus.serviceRef = null
    artJob?.cancel()
    scope.cancel()
    mediaSession?.let {
      try {
        removeSession(it)
      } catch (_: Exception) {}
      it.release()
    }
    mediaSession = null
    bridgePlayer = null
    foregroundStarted = false
    super.onDestroy()
  }

  fun syncFromBus() {
    val payload = SakuraMediaBus.current
    if (payload == null) {
      stopServiceCleanly()
      return
    }
    val url = payload.artworkUrl?.takeIf { it.isNotBlank() }
    if (url != null && !artworkCache.containsKey(url) && loadingArtUrl != url) {
      loadingArtUrl = url
      artJob?.cancel()
      artJob = scope.launch {
        val bytes = downloadArtworkJpeg(url)
        if (bytes != null && isActive) {
          artworkCache[url] = bytes
          runOnMain {
            refreshPlayerAndButtons()
          }
        }
      }
    }
    runOnMain {
      refreshPlayerAndButtons()
    }
  }

  fun stopServiceCleanly() {
    runOnMain {
      foregroundStarted = false
      try {
        stopForeground(STOP_FOREGROUND_REMOVE)
      } catch (_: Exception) {}
      stopSelf()
    }
  }

  private fun runOnMain(block: () -> Unit) {
    if (Looper.myLooper() == Looper.getMainLooper()) {
      block()
    } else {
      android.os.Handler(Looper.getMainLooper()).post(block)
    }
  }

  private fun ensureMediaChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (nm.getNotificationChannel(MEDIA_CHANNEL_ID) == null) {
      nm.createNotificationChannel(
        NotificationChannel(
          MEDIA_CHANNEL_ID,
          "Музыка Яндекс",
          NotificationManager.IMPORTANCE_LOW
        ).apply {
          description = "Управление плеером Сакуры на экране блокировки и в шторке"
          setShowBadge(false)
        }
      )
    }
  }

  private fun ensureImmediateForeground() {
    val payload = SakuraMediaBus.current
    val notif = NotificationCompat.Builder(this, MEDIA_CHANNEL_ID)
      .setSmallIcon(R.drawable.ic_sakura_notif)
      .setContentTitle(payload?.title ?: "Яндекс.Музыка")
      .setContentText(payload?.artist ?: "Сакура")
      .setCategory(NotificationCompat.CATEGORY_TRANSPORT)
      .setSilent(true)
      .setShowWhen(false)
      .build()
    try {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        startForeground(
          MEDIA_NOTIFICATION_ID,
          notif,
          ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        )
      } else {
        startForeground(MEDIA_NOTIFICATION_ID, notif)
      }
      foregroundStarted = true
    } catch (_: Exception) {}
  }

  private fun refreshPlayerAndButtons() {
    bridgePlayer?.refresh()
    val session = mediaSession ?: return
    val p = SakuraMediaBus.current ?: return

    val buttons = mutableListOf<CommandButton>()
    if (p.hasPrev) {
      buttons.add(
        CommandButton.Builder(CommandButton.ICON_PREVIOUS)
          .setDisplayName("Предыдущий трек")
          .setEnabled(true)
          .setPlayerCommand(Player.COMMAND_SEEK_TO_PREVIOUS)
          .setSlots(CommandButton.SLOT_BACK)
          .build()
      )
    }
    buttons.add(
      CommandButton.Builder(if (p.isPlaying) CommandButton.ICON_PAUSE else CommandButton.ICON_PLAY)
        .setDisplayName(if (p.isPlaying) "Пауза" else "Играть")
        .setEnabled(true)
        .setPlayerCommand(Player.COMMAND_PLAY_PAUSE)
        .setSlots(CommandButton.SLOT_CENTRAL)
        .build()
    )
    if (p.hasNext) {
      buttons.add(
        CommandButton.Builder(CommandButton.ICON_NEXT)
          .setDisplayName("Следующий трек")
          .setEnabled(true)
          .setPlayerCommand(Player.COMMAND_SEEK_TO_NEXT)
          .setSlots(CommandButton.SLOT_FORWARD)
          .build()
      )
    }
    buttons.add(
      CommandButton.Builder(
        if (p.isLiked) CommandButton.ICON_HEART_FILLED else CommandButton.ICON_HEART_UNFILLED
      )
        .setDisplayName(if (p.isLiked) "Убрать лайк" else "Лайк")
        .setEnabled(true)
        .setSessionCommand(SessionCommand(SakuraMediaBus.ACTION_TOGGLE_LIKE, Bundle.EMPTY))
        .setSlots(CommandButton.SLOT_FORWARD_SECONDARY)
        .build()
    )

    session.setMediaButtonPreferences(buttons)
    session.setCustomLayout(buttons)
    triggerNotificationUpdate()
  }

  private fun downloadArtworkJpeg(urlStr: String): ByteArray? {
    return try {
      val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
        connectTimeout = 6000
        readTimeout = 6000
        instanceFollowRedirects = true
      }
      conn.connect()
      if (conn.responseCode !in 200..299) {
        conn.disconnect()
        return null
      }
      val bmp = conn.inputStream.use { BitmapFactory.decodeStream(it) }
      conn.disconnect()
      if (bmp == null) return null
      val scaled = if (bmp.width > 320 || bmp.height > 320) {
        Bitmap.createScaledBitmap(bmp, 320, 320, true)
      } else {
        bmp
      }
      val out = ByteArrayOutputStream()
      scaled.compress(Bitmap.CompressFormat.JPEG, 88, out)
      if (scaled !== bmp) scaled.recycle()
      bmp.recycle()
      out.toByteArray()
    } catch (_: Exception) {
      null
    }
  }

  private inner class SessionCallback : MediaSession.Callback {
    override fun onConnect(
      session: MediaSession,
      controller: MediaSession.ControllerInfo
    ): MediaSession.ConnectionResult {
      val playerCommands = MediaSession.ConnectionResult.DEFAULT_PLAYER_COMMANDS.buildUpon()
        .add(Player.COMMAND_PLAY_PAUSE)
        .add(Player.COMMAND_PREPARE)
        .add(Player.COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM)
        .add(Player.COMMAND_SEEK_TO_PREVIOUS)
        .add(Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM)
        .add(Player.COMMAND_SEEK_TO_NEXT)
        .add(Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM)
        .build()

      val sessionCommands = MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS.buildUpon()
        .add(SessionCommand(SakuraMediaBus.ACTION_PREVIOUS, Bundle.EMPTY))
        .add(SessionCommand(SakuraMediaBus.ACTION_NEXT, Bundle.EMPTY))
        .add(SessionCommand(SakuraMediaBus.ACTION_TOGGLE_LIKE, Bundle.EMPTY))
        .build()

      return MediaSession.ConnectionResult.AcceptedResultBuilder(session)
        .setAvailablePlayerCommands(playerCommands)
        .setAvailableSessionCommands(sessionCommands)
        .build()
    }

    override fun onCustomCommand(
      session: MediaSession,
      controller: MediaSession.ControllerInfo,
      command: SessionCommand,
      args: Bundle
    ): ListenableFuture<SessionResult> {
      when (command.customAction) {
        SakuraMediaBus.ACTION_PREVIOUS -> {
          SakuraMediaBus.emitAction("previous")
          return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
        }
        SakuraMediaBus.ACTION_NEXT -> {
          SakuraMediaBus.emitAction("next")
          return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
        }
        SakuraMediaBus.ACTION_TOGGLE_LIKE -> {
          val cur = SakuraMediaBus.current
          if (cur != null) {
            SakuraMediaBus.current = cur.copy(isLiked = !cur.isLiked)
            refreshPlayerAndButtons()
          }
          SakuraMediaBus.emitAction("toggle_like")
          return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
        }
      }
      return super.onCustomCommand(session, controller, command, args)
    }
  }

  private inner class BridgePlayer : SimpleBasePlayer(Looper.getMainLooper()) {
    fun refresh() {
      invalidateState()
    }

    override fun getState(): State {
      val p = SakuraMediaBus.current
      if (p == null) {
        return State.Builder()
          .setPlaybackState(Player.STATE_IDLE)
          .setPlayWhenReady(false, PLAY_WHEN_READY_CHANGE_REASON_USER_REQUEST)
          .setAvailableCommands(Player.Commands.EMPTY)
          .setAudioAttributes(AudioAttributes.DEFAULT)
          .build()
      }

      val commands = Player.Commands.Builder()
        .add(Player.COMMAND_PLAY_PAUSE)
        .add(Player.COMMAND_PREPARE)
        .add(Player.COMMAND_GET_CURRENT_MEDIA_ITEM)
        .add(Player.COMMAND_GET_TIMELINE)
        .add(Player.COMMAND_GET_METADATA)
        .apply {
          if (p.durationMs > 0) add(Player.COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM)
          if (p.hasPrev) {
            add(Player.COMMAND_SEEK_TO_PREVIOUS)
            add(Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM)
          }
          if (p.hasNext) {
            add(Player.COMMAND_SEEK_TO_NEXT)
            add(Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM)
          }
        }
        .build()

      val metaBuilder = MediaMetadata.Builder()
        .setTitle(p.title)
        .setArtist(p.artist)
        .setAlbumTitle(p.album)
        .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)

      val cachedArt = p.artworkUrl?.let { artworkCache[it] }
      if (cachedArt != null) {
        metaBuilder.setArtworkData(cachedArt, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
      } else if (!p.artworkUrl.isNullOrBlank()) {
        metaBuilder.setArtworkUri(Uri.parse(p.artworkUrl))
      }

      val curMeta = metaBuilder.build()
      val items = mutableListOf<MediaItemData>()
      if (p.hasPrev) {
        items.add(
          MediaItemData.Builder("__sakura_prev__")
            .setMediaItem(MediaItem.Builder().setMediaId("__sakura_prev__").build())
            .build()
        )
      }
      val curIdx = items.size
      items.add(
        MediaItemData.Builder(p.trackId)
          .setMediaItem(
            MediaItem.Builder()
              .setMediaId(p.trackId)
              .setMediaMetadata(curMeta)
              .build()
          )
          .setMediaMetadata(curMeta)
          .setIsSeekable(p.durationMs > 0)
          .setDurationUs(if (p.durationMs > 0) p.durationMs * 1000L else C.TIME_UNSET)
          .build()
      )
      if (p.hasNext) {
        items.add(
          MediaItemData.Builder("__sakura_next__")
            .setMediaItem(MediaItem.Builder().setMediaId("__sakura_next__").build())
            .build()
        )
      }

      val elapsed = (SystemClock.elapsedRealtime() - p.updatedAtElapsedMs).coerceAtLeast(0L)
      val effectivePos = if (p.isPlaying) {
        val est = p.positionMs + elapsed
        if (p.durationMs > 0) est.coerceIn(0L, p.durationMs) else est
      } else {
        p.positionMs
      }

      val posSupplier = if (p.isPlaying) {
        PositionSupplier.getExtrapolating(effectivePos, 1.0f)
      } else {
        PositionSupplier.getConstant(effectivePos)
      }

      return State.Builder()
        .setAvailableCommands(commands)
        .setAudioAttributes(AudioAttributes.DEFAULT)
        .setMaxSeekToPreviousPositionMs(Long.MAX_VALUE)
        .setPlaylist(items)
        .setCurrentMediaItemIndex(curIdx)
        .setPlaybackState(Player.STATE_READY)
        .setPlayWhenReady(p.isPlaying, PLAY_WHEN_READY_CHANGE_REASON_USER_REQUEST)
        .setContentPositionMs(posSupplier)
        .build()
    }

    override fun handleSetPlayWhenReady(playWhenReady: Boolean): ListenableFuture<*> {
      val cur = SakuraMediaBus.current
      if (cur != null) {
        val elapsed = (SystemClock.elapsedRealtime() - cur.updatedAtElapsedMs).coerceAtLeast(0L)
        val estPos = if (cur.isPlaying) cur.positionMs + elapsed else cur.positionMs
        SakuraMediaBus.current = cur.copy(
          isPlaying = playWhenReady,
          positionMs = if (cur.durationMs > 0) estPos.coerceIn(0L, cur.durationMs) else estPos,
          updatedAtElapsedMs = SystemClock.elapsedRealtime()
        )
        refreshPlayerAndButtons()
      }
      SakuraMediaBus.emitAction(if (playWhenReady) "play" else "pause")
      return Futures.immediateVoidFuture()
    }

    override fun handleSeek(
      mediaItemIndex: Int,
      positionMs: Long,
      seekCommand: Int
    ): ListenableFuture<*> {
      val cur = SakuraMediaBus.current
      val curIdx = if (cur?.hasPrev == true) 1 else 0
      when {
        seekCommand == Player.COMMAND_SEEK_TO_NEXT ||
          seekCommand == Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM ||
          mediaItemIndex > curIdx -> {
          SakuraMediaBus.emitAction("next")
        }
        seekCommand == Player.COMMAND_SEEK_TO_PREVIOUS ||
          seekCommand == Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM ||
          mediaItemIndex < curIdx -> {
          SakuraMediaBus.emitAction("previous")
        }
        else -> {
          val target = if (positionMs == C.TIME_UNSET) 0L else positionMs.coerceAtLeast(0L)
          if (cur != null) {
            SakuraMediaBus.current = cur.copy(
              positionMs = target,
              updatedAtElapsedMs = SystemClock.elapsedRealtime()
            )
            invalidateState()
          }
          SakuraMediaBus.emitAction("seek", target)
        }
      }
      return Futures.immediateVoidFuture()
    }
  }

  companion object {
    private const val MEDIA_CHANNEL_ID = "sakura_music_playback_v1"
    private const val MEDIA_NOTIFICATION_ID = 4401
  }
}
