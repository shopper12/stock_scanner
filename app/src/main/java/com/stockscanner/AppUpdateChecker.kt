package com.stockscanner

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val APP_VERSION_URL = "https://github.com/shopper12/stock_scanner/releases/download/app-latest/app_version.json"
private const val UPDATE_CHANNEL_ID = "stock_scanner_update"

data class AppUpdateInfo(
    val updateAvailable: Boolean,
    val currentVersionCode: Int,
    val latestVersionCode: Int,
    val latestVersionName: String,
    val builtAtUtc: String,
    val commitSha: String,
    val message: String,
)

suspend fun checkForAppUpdate(context: Context): AppUpdateInfo = withContext(Dispatchers.IO) {
    val current = BuildConfig.VERSION_CODE
    val json = fetchLatestVersionJson()
    val latest = json.optInt("version_code", current)
    val latestName = json.optString("version_name", "-")
    val builtAt = json.optString("built_at_utc", "-")
    val commit = json.optString("commit_sha", "-")
    val available = latest > current
    AppUpdateInfo(
        updateAvailable = available,
        currentVersionCode = current,
        latestVersionCode = latest,
        latestVersionName = latestName,
        builtAtUtc = builtAt,
        commitSha = commit,
        message = if (available) "새 APK가 있습니다. 현재 $current → 최신 $latest ($latestName)" else "현재 APK가 최신입니다. versionCode=$current",
    )
}

fun notifyAppUpdateAvailable(context: Context, info: AppUpdateInfo) {
    if (!info.updateAvailable) return
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
        return
    }
    val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        manager.createNotificationChannel(NotificationChannel(UPDATE_CHANNEL_ID, "Stock Scanner 업데이트", NotificationManager.IMPORTANCE_DEFAULT))
    }
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/shopper12/stock_scanner/releases/tag/app-latest")).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
    val pendingIntent = PendingIntent.getActivity(context, 7001, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    val notification = NotificationCompat.Builder(context, UPDATE_CHANNEL_ID)
        .setSmallIcon(android.R.drawable.stat_sys_download_done)
        .setContentTitle("Stock Scanner 새 APK 있음")
        .setContentText(info.message)
        .setStyle(NotificationCompat.BigTextStyle().bigText("${info.message}\n빌드: ${info.builtAtUtc}\n앱 첫 화면에서 APK 바로 업데이트를 누르세요."))
        .setContentIntent(pendingIntent)
        .setAutoCancel(true)
        .build()
    NotificationManagerCompat.from(context).notify(7001, notification)
}

private fun fetchLatestVersionJson(): JSONObject {
    val connection = (URL(APP_VERSION_URL).openConnection() as HttpURLConnection).apply {
        connectTimeout = 10000
        readTimeout = 30000
        requestMethod = "GET"
        instanceFollowRedirects = true
        setRequestProperty("User-Agent", "StockScanner-Android-Updater")
        setRequestProperty("Accept", "application/json")
    }
    try {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        if (code !in 200..299) error("version manifest HTTP $code: ${body.take(200)}")
        return JSONObject(body)
    } finally {
        connection.disconnect()
    }
}
