package expo.modules.sakurawake

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import androidx.core.content.ContextCompat
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.LibVosk
import org.vosk.LogLevel
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.atomic.AtomicBoolean

private const val EVENT_WAKE = "onWakeWord"
private const val EVENT_STATE = "onWakeState"
private const val EVENT_MEDIA = "onMediaAction"
private const val MODEL_ASSET_DIR = "vosk-model-small-ru-0.22"
private const val SAMPLE_RATE = 16000

class SakuraWakeModule : Module() {
  private val ctx: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  private var model: Model? = null
  private val running = AtomicBoolean(false)
  private var workerThread: Thread? = null
  private val lock = Any()

  override fun definition() = ModuleDefinition {
    Name("SakuraWake")

    Events(EVENT_WAKE, EVENT_STATE, EVENT_MEDIA)

    OnCreate {
      SakuraNotifications.ensureChannels(ctx)
      SakuraMediaBus.actionListener = { action, posMs ->
        try {
          sendEvent(EVENT_MEDIA, mapOf("action" to action, "positionMs" to posMs))
        } catch (_: Exception) {}
      }
    }

    Function("isSupported") {
      try {
        val list = ctx.assets.list(MODEL_ASSET_DIR)
        list != null && list.isNotEmpty()
      } catch (_: Exception) {
        false
      }
    }

    AsyncFunction("start") { phrases: List<String>? ->
      val phraseList = if (phrases.isNullOrEmpty()) {
        listOf("сакура", "привет сакура", "слушай сакура", "эй сакура")
      } else {
        phrases.map { it.trim().lowercase() }.filter { it.isNotEmpty() }
      }
      startListening(phraseList)
    }

    AsyncFunction("stop") {
      stopListening()
      true
    }

    Function("showNotification") { title: String, body: String, route: String?, tag: String? ->
      SakuraNotifications.showPopup(ctx, title, body, route, tag)
    }

    Function("updateMediaState") { data: Map<String, Any?> ->
      val trackId = (data["trackId"] as? String).orEmpty()
      val title = (data["title"] as? String).orEmpty()
      val artist = (data["artist"] as? String).orEmpty()
      val album = (data["album"] as? String).orEmpty()
      val artworkUrl = data["artworkUrl"] as? String
      val durationMs = (data["durationMs"] as? Number)?.toLong()?.coerceAtLeast(0L) ?: 0L
      val positionMs = (data["positionMs"] as? Number)?.toLong()?.coerceAtLeast(0L) ?: 0L
      val isPlaying = data["isPlaying"] as? Boolean ?: false
      val isLiked = data["isLiked"] as? Boolean ?: false
      val hasPrev = data["hasPrev"] as? Boolean ?: false
      val hasNext = data["hasNext"] as? Boolean ?: false
      SakuraMediaBus.update(
        ctx,
        SakuraMediaPayload(
          trackId = trackId,
          title = title,
          artist = artist,
          album = album,
          artworkUrl = artworkUrl,
          durationMs = durationMs,
          positionMs = positionMs,
          updatedAtElapsedMs = SystemClock.elapsedRealtime(),
          isPlaying = isPlaying,
          isLiked = isLiked,
          hasPrev = hasPrev,
          hasNext = hasNext,
        )
      )
      true
    }

    Function("clearMediaState") {
      SakuraMediaBus.clear(ctx)
      true
    }

    OnDestroy {
      SakuraMediaBus.actionListener = null
      stopListening()
      synchronized(lock) {
        try {
          model?.close()
        } catch (_: Exception) {}
        model = null
      }
    }
  }

  private fun ensureModelUnpacked(context: Context): File? {
    val targetDir = File(context.filesDir, MODEL_ASSET_DIR)
    val marker = File(targetDir, ".ready_v1")
    if (marker.exists() && File(targetDir, "conf").exists()) {
      return targetDir
    }
    val assets = context.assets
    val rootEntries = assets.list(MODEL_ASSET_DIR)
    if (rootEntries.isNullOrEmpty()) {
      return null
    }
    if (targetDir.exists()) {
      targetDir.deleteRecursively()
    }
    copyAssetTree(assets, MODEL_ASSET_DIR, targetDir)
    marker.writeText("ok")
    return targetDir
  }

  private fun copyAssetTree(assets: AssetManager, assetPath: String, outDir: File) {
    val items = assets.list(assetPath) ?: return
    if (items.isEmpty()) {
      outDir.parentFile?.mkdirs()
      assets.open(assetPath).use { input ->
        FileOutputStream(outDir).use { output ->
          input.copyTo(output)
        }
      }
      return
    }
    outDir.mkdirs()
    for (child in items) {
      copyAssetTree(assets, "$assetPath/$child", File(outDir, child))
    }
  }

  private fun startListening(phrases: List<String>): Boolean {
    val context = ctx
    if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
      != PackageManager.PERMISSION_GRANTED
    ) {
      emitState("permission_denied")
      return false
    }

    if (running.get()) {
      return true
    }

    val modelDir = ensureModelUnpacked(context)
    if (modelDir == null) {
      emitState("model_missing")
      return false
    }

    LibVosk.setLogLevel(LogLevel.WARNINGS)
    val loadedModel = synchronized(lock) {
      model ?: Model(modelDir.absolutePath).also { model = it }
    }

    val grammarArr = JSONArray()
    phrases.forEach { grammarArr.put(it) }
    grammarArr.put("[unk]")
    val grammar = grammarArr.toString()

    val minBuf = AudioRecord.getMinBufferSize(
      SAMPLE_RATE,
      AudioFormat.CHANNEL_IN_MONO,
      AudioFormat.ENCODING_PCM_16BIT
    )
    if (minBuf <= 0) {
      emitState("mic_error")
      return false
    }

    val bufferShorts = maxOf(minBuf / 2, 1600)
    val record = createAudioRecord(bufferShorts * 2) ?: run {
      emitState("mic_error")
      return false
    }

    running.set(true)
    emitState("listening")

    val thread = Thread {
      var recognizer: Recognizer? = null
      try {
        recognizer = Recognizer(loadedModel, SAMPLE_RATE.toFloat(), grammar)
        record.startRecording()
        val buf = ShortArray(bufferShorts)

        while (running.get()) {
          val n = record.read(buf, 0, buf.size)
          if (n <= 0) continue

          val isFinal = recognizer.acceptWaveForm(buf, n)
          val text = if (isFinal) {
            extractField(recognizer.result, "text")
          } else {
            extractField(recognizer.partialResult, "partial")
          }

          val matched = matchPhrase(text, phrases)
          if (matched != null) {
            running.set(false)
            try {
              record.stop()
            } catch (_: Exception) {}
            try {
              record.release()
            } catch (_: Exception) {}
            emitState("triggered")
            sendEvent(EVENT_WAKE, mapOf("phrase" to matched, "text" to text))
            return@Thread
          }
        }
      } catch (_: Exception) {
        emitState("error")
      } finally {
        running.set(false)
        try {
          if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
            record.stop()
          }
        } catch (_: Exception) {}
        try {
          record.release()
        } catch (_: Exception) {}
        try {
          recognizer?.close()
        } catch (_: Exception) {}
      }
    }
    thread.isDaemon = true
    thread.name = "SakuraWakeWorker"
    workerThread = thread
    thread.start()
    return true
  }

  private fun stopListening() {
    running.set(false)
    val t = workerThread
    workerThread = null
    if (t != null && t.isAlive && Thread.currentThread() !== t) {
      try {
        t.join(500)
      } catch (_: Exception) {}
    }
    emitState("idle")
  }

  private fun createAudioRecord(bufferBytes: Int): AudioRecord? {
    val sources = intArrayOf(
      MediaRecorder.AudioSource.VOICE_RECOGNITION,
      MediaRecorder.AudioSource.MIC
    )
    for (src in sources) {
      try {
        val rec = AudioRecord(
          src,
          SAMPLE_RATE,
          AudioFormat.CHANNEL_IN_MONO,
          AudioFormat.ENCODING_PCM_16BIT,
          bufferBytes
        )
        if (rec.state == AudioRecord.STATE_INITIALIZED) {
          return rec
        }
        rec.release()
      } catch (_: Exception) {}
    }
    return null
  }

  private fun extractField(jsonStr: String?, key: String): String {
    if (jsonStr.isNullOrBlank()) return ""
    return try {
      JSONObject(jsonStr).optString(key, "").trim().lowercase()
    } catch (_: Exception) {
      ""
    }
  }

  private fun matchPhrase(text: String, phrases: List<String>): String? {
    if (text.isEmpty()) return null
    val norm = text.replace('ё', 'е')
    for (p in phrases) {
      val np = p.replace('ё', 'е')
      if (norm.contains(np)) return np
    }
    return null
  }

  private fun emitState(state: String) {
    try {
      sendEvent(EVENT_STATE, mapOf("state" to state))
    } catch (_: Exception) {}
  }
}
