package com.stockscanner

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

private const val RECOMMENDATION_ALERT_URL = "https://stock-scanner-api-5sk6.onrender.com/api/recommendations"
private const val ALERT_PREFS = "stock_scanner_recommendation_alerts"
private const val KEY_LAST_SIGNATURE = "last_recommendation_signature"
private const val CHANNEL_ID = "chatgpt_recommendation_alerts"
private const val NOTIFICATION_ID = 9305

internal object RecommendationAlertScheduler {
    private const val PERIODIC_WORK_NAME = "chatgpt_recommendation_alert_periodic"
    private const val IMMEDIATE_WORK_NAME = "chatgpt_recommendation_alert_now"

    fun ensureScheduled(context: Context) {
        val appContext = context.applicationContext
        val immediate = OneTimeWorkRequestBuilder<RecommendationAlertWorker>().build()
        val periodic = PeriodicWorkRequestBuilder<RecommendationAlertWorker>(15, TimeUnit.MINUTES).build()

        WorkManager.getInstance(appContext).enqueueUniqueWork(
            IMMEDIATE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            immediate,
        )
        WorkManager.getInstance(appContext).enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            periodic,
        )
    }
}

class RecommendationAlertWorker(
    appContext: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(appContext, workerParams) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        runCatching {
            val payload = fetchRecommendationPayload()
            if (payload.signature.isBlank() || payload.recommendationCount <= 0) return@withContext Result.success()

            val prefs = applicationContext.getSharedPreferences(ALERT_PREFS, Context.MODE_PRIVATE)
            val previous = prefs.getString(KEY_LAST_SIGNATURE, "").orEmpty()

            if (previous.isBlank()) {
                prefs.edit().putString(KEY_LAST_SIGNATURE, payload.signature).apply()
                return@withContext Result.success()
            }
            if (previous == payload.signature) return@withContext Result.success()

            if (!canPostNotifications()) return@withContext Result.success()

            showRecommendationNotification(payload)
            prefs.edit().putString(KEY_LAST_SIGNATURE, payload.signature).apply()
            Result.success()
        }.getOrElse {
            Result.retry()
        }
    }

    private fun canPostNotifications(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
    }

    private fun fetchRecommendationPayload(): RecommendationAlertPayload {
        val json = JSONObject(httpGet(RECOMMENDATION_ALERT_URL))
        val rows = json.optJSONArray("recommendations")
            ?: json.optJSONArray("items")
            ?: json.optJSONArray("chatgpt_recommendations")
            ?: JSONArray()
        val updatedAt = json.anyString("briefing_datetime_kst", "updated_at_kst", "generated_at")
        val first = rows.optJSONObject(0)
        val firstName = first?.anyString("asset_name", "name", "ticker", "code", "symbol").orEmpty()
        val signatureBase = if (updatedAt.isNotBlank()) updatedAt else rows.toString()
        return RecommendationAlertPayload(
            updatedAt = updatedAt,
            recommendationCount = rows.length(),
            firstAsset = firstName,
            signature = sha256(signatureBase),
        )
    }

    private fun httpGet(url: String): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15000
            readTimeout = 15000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "StockScanner-Android")
        }
        try {
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) error("HTTP $code: ${body.take(200)}")
            if (body.trimStart().startsWith("<")) error("Server returned HTML instead of JSON")
            return body
        } finally {
            connection.disconnect()
        }
    }

    @SuppressLint("MissingPermission")
    private fun showRecommendationNotification(payload: RecommendationAlertPayload) {
        ensureNotificationChannel()
        val intent = Intent(applicationContext, BotCardsActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            applicationContext,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val title = "새 ChatGPT 브리핑 도착"
        val summary = buildString {
            append("추천 ").append(payload.recommendationCount).append("개")
            if (payload.updatedAt.isNotBlank()) append(" · ").append(payload.updatedAt)
            if (payload.firstAsset.isNotBlank()) append(" · ").append(payload.firstAsset)
        }
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(summary)
            .setStyle(NotificationCompat.BigTextStyle().bigText(summary))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        NotificationManagerCompat.from(applicationContext).notify(NOTIFICATION_ID, notification)
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            "ChatGPT 추천 알림",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "새 브리핑 추천이 도착하면 알림을 표시합니다."
        }
        manager.createNotificationChannel(channel)
    }
}

private data class RecommendationAlertPayload(
    val updatedAt: String,
    val recommendationCount: Int,
    val firstAsset: String,
    val signature: String,
)

private fun JSONObject.anyString(vararg keys: String): String {
    for (key in keys) if (has(key) && !isNull(key)) return opt(key).toString()
    return ""
}

private fun sha256(value: String): String {
    val bytes = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
    return bytes.joinToString("") { "%02x".format(it) }
}
