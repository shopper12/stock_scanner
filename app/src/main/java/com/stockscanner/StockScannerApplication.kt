package com.stockscanner

import android.app.Application

class StockScannerApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        RecommendationAlertScheduler.ensureScheduled(this)
    }
}
