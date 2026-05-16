package com.shopper12.stockscanner.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.shopper12.stockscanner.data.ScannerEngine
import com.shopper12.stockscanner.notify.TelegramNotifier

class ScanWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {
    override suspend fun doWork(): Result {
        return try {
            val scan = ScannerEngine().runScan()
            TelegramNotifier().send(scan)
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }
}
