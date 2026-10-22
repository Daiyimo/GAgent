package com.ljq.ga

import android.content.Context
import java.io.File
import org.json.JSONObject

/** Bounded, scrubbed diagnostics stay in app-private storage. */
object Diag {
    private var logFile: File? = null
    private const val MAX_BYTES = 256 * 1024

    fun init(ctx: Context) {
        if (logFile != null) return
        logFile = File(ctx.filesDir, "ga/logs/app.log").also { it.parentFile?.mkdirs() }
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            log("crash", error.stackTraceToString())
            previous?.uncaughtException(thread, error)
        }
    }

    fun scrub(value: String): String = Scrub.full(value)

    @Synchronized
    fun log(tag: String, message: String) {
        val file = logFile ?: return
        val safeTag = scrub(tag).replace(Regex("[\r\n]"), " ").take(24)
        val safeMessage = scrub(message.take(8192)).replace(Regex("[\r\n]"), " ")
        runCatching {
            if (file.length() > MAX_BYTES) file.writeText(file.readText().takeLast(MAX_BYTES / 4))
            file.appendText("${System.currentTimeMillis()} [$safeTag] $safeMessage\n")
        }.onFailure { android.util.Log.w("GAgent", "Could not write local diagnostics") }
    }

    private fun unavailable(): String = JSONObject().put("ok", false)
        .put("error", "Automatic collection and remote diagnostic uploads are not included").toString()
    fun uploadLogs(): String = unavailable()
    @Suppress("UNUSED_PARAMETER") fun submitFeedback(json: String): String = unavailable()
    @Suppress("UNUSED_PARAMETER") fun jobResult(id: String): String = unavailable()
    @Suppress("UNUSED_PARAMETER") fun contributePrompt(text: String, convoId: String) = Unit
}
