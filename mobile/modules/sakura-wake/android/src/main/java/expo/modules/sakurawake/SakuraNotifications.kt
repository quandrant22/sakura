package expo.modules.sakurawake

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.util.concurrent.atomic.AtomicInteger

object SakuraNotifications {
  private const val CHANNEL_ALERTS_ID = "sakura_alerts_high_v1"
  private val nextId = AtomicInteger(9000)

  fun ensureChannels(context: Context) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (nm.getNotificationChannel(CHANNEL_ALERTS_ID) == null) {
      val ch = NotificationChannel(
        CHANNEL_ALERTS_ID,
        "Уведомления Сакуры",
        NotificationManager.IMPORTANCE_HIGH
      ).apply {
        description = "Всплывающие ответы, напоминания и важные статусы Сакуры"
        enableVibration(true)
        enableLights(true)
        setShowBadge(true)
        lockscreenVisibility = Notification.VISIBILITY_PUBLIC
      }
      nm.createNotificationChannel(ch)
    }
  }

  fun showPopup(
    context: Context,
    title: String,
    body: String,
    route: String? = null,
    tag: String? = null
  ): Boolean {
    if (body.isBlank()) return false
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      val granted = ContextCompat.checkSelfPermission(
        context,
        Manifest.permission.POST_NOTIFICATIONS
      ) == PackageManager.PERMISSION_GRANTED
      if (!granted) return false
    }

    ensureChannels(context)
    val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    val launchIntent = if (!route.isNullOrBlank()) {
      Intent(Intent.ACTION_VIEW, Uri.parse("sakura:///$route")).apply {
        setPackage(context.packageName)
        addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
      }
    } else {
      context.packageManager.getLaunchIntentForPackage(context.packageName)?.apply {
        addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
      }
    }

    val pendingIntent = if (launchIntent != null) {
      PendingIntent.getActivity(
        context,
        (route ?: "open").hashCode(),
        launchIntent,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
      )
    } else null

    val notifId = if (!tag.isNullOrBlank()) {
      7000 + (tag.hashCode() and 0x0FFF)
    } else {
      nextId.getAndIncrement()
    }

    val builder = NotificationCompat.Builder(context, CHANNEL_ALERTS_ID)
      .setSmallIcon(R.drawable.ic_sakura_notif)
      .setColor(0xFFFF6AE3.toInt())
      .setContentTitle(title.ifBlank { "Сакура" })
      .setContentText(body)
      .setStyle(NotificationCompat.BigTextStyle().bigText(body))
      .setPriority(NotificationCompat.PRIORITY_HIGH)
      .setCategory(NotificationCompat.CATEGORY_MESSAGE)
      .setDefaults(NotificationCompat.DEFAULT_ALL)
      .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
      .setAutoCancel(true)

    if (pendingIntent != null) {
      builder.setContentIntent(pendingIntent)
    }

    return try {
      nm.notify(notifId, builder.build())
      true
    } catch (_: SecurityException) {
      false
    } catch (_: Exception) {
      false
    }
  }
}
