package com.stockscanner

import android.content.Context

private const val SETTINGS_FILE = "stock_scanner_local_settings"
private const val SERVER_EDIT_KEY = "server_edit_key"

internal fun readServerEditKey(context: Context): String =
    context.getSharedPreferences(SETTINGS_FILE, Context.MODE_PRIVATE)
        .getString(SERVER_EDIT_KEY, "")
        ?: ""

internal fun saveServerEditKey(context: Context, value: String) {
    context.getSharedPreferences(SETTINGS_FILE, Context.MODE_PRIVATE)
        .edit()
        .putString(SERVER_EDIT_KEY, value.trim())
        .apply()
}

internal fun clearServerEditKey(context: Context) {
    context.getSharedPreferences(SETTINGS_FILE, Context.MODE_PRIVATE)
        .edit()
        .remove(SERVER_EDIT_KEY)
        .apply()
}
