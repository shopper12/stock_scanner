package com.stockscanner

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

private const val LATEST_APK_URL = "https://github.com/shopper12/stock_scanner/releases/download/app-latest/stock-scanner-latest.apk"

fun downloadAndInstallLatestApk(context: Context, onStatus: (String) -> Unit) {
    CoroutineScope(Dispatchers.Main).launch {
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
                onStatus("알 수 없는 앱 설치 권한을 먼저 허용하세요. 권한 허용 후 업데이트/APK를 다시 누르세요.")
                val settingsIntent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES).apply {
                    data = Uri.parse("package:${context.packageName}")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(settingsIntent)
                return@launch
            }
            onStatus("최신 APK 다운로드 중...")
            val apkFile = withContext(Dispatchers.IO) { downloadLatestApk(context) }
            onStatus("다운로드 완료. 설치 화면을 엽니다.")
            installApk(context, apkFile)
        }.onFailure { error ->
            onStatus("APK 업데이트 실패: ${error.message ?: error::class.java.simpleName}")
        }
    }
}

private fun downloadLatestApk(context: Context): File {
    val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
    if (!dir.exists()) dir.mkdirs()
    val target = File(dir, "stock-scanner-latest.apk")
    val tmp = File(dir, "stock-scanner-latest.apk.tmp")
    val connection = (URL(LATEST_APK_URL).openConnection() as HttpURLConnection).apply {
        connectTimeout = 15000
        readTimeout = 120000
        requestMethod = "GET"
        instanceFollowRedirects = true
        setRequestProperty("User-Agent", "StockScanner-Android-Updater")
    }
    try {
        val code = connection.responseCode
        if (code !in 200..299) error("HTTP $code")
        connection.inputStream.use { input ->
            tmp.outputStream().use { output ->
                input.copyTo(output)
            }
        }
        if (tmp.length() < 100_000L) error("다운로드된 APK가 비정상적으로 작습니다: ${tmp.length()} bytes")
        if (target.exists()) target.delete()
        if (!tmp.renameTo(target)) {
            tmp.copyTo(target, overwrite = true)
            tmp.delete()
        }
        return target
    } finally {
        connection.disconnect()
    }
}

private fun installApk(context: Context, apkFile: File) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apkFile)
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(uri, "application/vnd.android.package-archive")
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(intent)
}
