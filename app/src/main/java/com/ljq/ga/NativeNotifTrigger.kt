package com.ljq.ga

import android.app.Notification
import android.content.Context
import android.content.SharedPreferences
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.math.floor

/**
 * Native, persistent notification-rule state. Notification values are used only
 * while matching selectors; only SHA-256 values derived from notifications are
 * persisted for baseline and duplicate tracking.
 */
object NativeNotifTrigger {
    private const val TAG = "GA.NativeNotifTrigger"
    private const val PREF = "native_notif_trigger"
    private const val KEY_RUNNING = "running"
    private const val KEY_RULES = "rules_json"
    private const val SEEN_PREFIX = "seen."
    private const val LAST_FIRE_PREFIX = "last_fire."
    private const val MAX_RULES = 64
    private const val LISTENER_ERROR =
        "notification listener not enabled: Settings > Notifications > Device & app notifications > GA"

    private val lock = Any()
    private val ruleFields = setOf("id", "pkg", "keywords", "task", "enabled", "cooldown_ms")

    private data class Rule(
        val id: String,
        val pkg: String,
        val keywords: List<String>,
        val task: String,
        val enabled: Boolean,
        val cooldownMs: Long,
    )

    private data class Notice(
        val key: String,
        val pkg: String,
        val title: String,
        val text: String,
        val bigText: String,
    ) {
        /** Full body handed to the agent: primary text plus expanded/big-text content. */
        fun body(): String = listOf(text, bigText)
            .filter { it.isNotEmpty() }
            .distinct()
            .joinToString("\n")
    }

    /** Validate, persist, enable, and baseline all notifications already active. */
    fun start(context: Context, rawRules: JSONArray): JSONObject {
        val rules = parseRules(rawRules)
        val listener = NotifService.instance ?: throw IllegalStateException(LISTENER_ERROR)
        val active = listener.snapshotActiveNotifications()
        return synchronized(lock) {
            // WorkManager cancellation is asynchronous. Wait while holding the trigger lock
            // so no callback can enqueue replacement work before the old tagged set is gone.
            NativeNotifTriggerDispatch.cancel(context.applicationContext).result.get()
            val prefs = prefs(context)
            val edit = prefs.edit()
            clearTransientState(prefs, edit)
            edit.putString(KEY_RULES, encodeRules(rules))
                .putBoolean(KEY_RUNNING, true)
            baseline(edit, active)
            if (!edit.commit()) throw IllegalStateException("unable to persist native notification rules")
            lifecycle(true, true, listenerEnabled(), rules.size, "")
        }
    }

    /** Report persisted state even when Android has not connected the listener. */
    fun status(context: Context): JSONObject = synchronized(lock) {
        val prefs = prefs(context)
        val running = prefs.getBoolean(KEY_RUNNING, false)
        val listenerEnabled = listenerEnabled()
        try {
            val rules = storedRules(prefs)
            lifecycle(
                ok = true,
                running = running,
                listenerEnabled = listenerEnabled,
                ruleCount = rules.size,
                error = if (running && !listenerEnabled) LISTENER_ERROR else "",
            )
        } catch (e: Exception) {
            lifecycle(
                ok = false,
                running = running,
                listenerEnabled = listenerEnabled,
                ruleCount = 0,
                error = "stored native notification rules are invalid: ${e.message ?: e.javaClass.simpleName}",
            )
        }
    }

    /** Return the complete persisted rule set without requiring listener access. */
    fun rules(context: Context): JSONObject = synchronized(lock) {
        val prefs = prefs(context)
        rulesResponse(prefs, storedRules(prefs))
    }

    /** Append one rule after validating the complete resulting list. */
    fun addRule(context: Context, rawRule: Any?): JSONObject = synchronized(lock) {
        val prefs = prefs(context)
        val rawRules = rulesArray(storedRules(prefs)).put(rawRule)
        persistRules(prefs, parseRules(rawRules))
    }

    /** Enable or disable one existing rule without replacing the other rules. */
    fun setRuleEnabled(context: Context, rawId: Any?, rawEnabled: Any?): JSONObject = synchronized(lock) {
        val ruleId = requiredRuleId(rawId)
        if (rawEnabled !is Boolean) {
            throw IllegalArgumentException("notification rule enabled must be boolean")
        }
        val prefs = prefs(context)
        val current = storedRules(prefs)
        if (current.none { it.id == ruleId }) {
            throw IllegalArgumentException("notification rule '$ruleId' does not exist")
        }
        val updated = current.map { rule ->
            if (rule.id == ruleId) rule.copy(enabled = rawEnabled) else rule
        }
        val response = persistRules(prefs, updated, if (rawEnabled) null else ruleId)
        if (!rawEnabled) {
            NativeNotifTriggerDispatch.cancelRule(context.applicationContext, ruleId)
        }
        response
    }

    /** Delete one existing rule and discard its pending work and cooldown state. */
    fun deleteRule(context: Context, rawId: Any?): JSONObject = synchronized(lock) {
        val ruleId = requiredRuleId(rawId)
        val prefs = prefs(context)
        val current = storedRules(prefs)
        if (current.none { it.id == ruleId }) {
            throw IllegalArgumentException("notification rule '$ruleId' does not exist")
        }
        val response = persistRules(prefs, current.filterNot { it.id == ruleId }, ruleId)
        NativeNotifTriggerDispatch.cancelRule(context.applicationContext, ruleId)
        response
    }

    /** Disable matching and discard only this trigger's transient state. */
    fun stop(context: Context): JSONObject {
        val response = synchronized(lock) {
            val prefs = prefs(context)
            val rules = try {
                storedRules(prefs)
            } catch (_: Exception) {
                emptyList()
            }
            val edit = prefs.edit().putBoolean(KEY_RUNNING, false)
            clearTransientState(prefs, edit)
            if (!edit.commit()) throw IllegalStateException("unable to stop native notification trigger")
            lifecycle(true, false, listenerEnabled(), rules.size, "")
        }
        NativeNotifTriggerDispatch.cancel(context.applicationContext)
        return response
    }

    /** Baseline current active notifications after Android reconnects this service. */
    fun onListenerConnected(context: Context, active: Collection<StatusBarNotification>) {
        try {
            synchronized(lock) {
                val prefs = prefs(context)
                if (!prefs.getBoolean(KEY_RUNNING, false)) return@synchronized
                val edit = prefs.edit()
                clearSeenState(prefs, edit)
                baseline(edit, active)
                if (!edit.commit()) Log.w(TAG, "unable to persist notification baseline")
            }
        } catch (e: Exception) {
            Log.w(TAG, "unable to baseline active notifications", e)
        }
    }

    /** Serialize matching, de-duplication, cooldown accounting, and fixed-task handoff. */
    fun onNotificationPosted(context: Context, sbn: StatusBarNotification) {
        try {
            synchronized(lock) {
                val prefs = prefs(context)
                if (!prefs.getBoolean(KEY_RUNNING, false)) return@synchronized
                val notice = noticeOf(sbn) ?: return@synchronized
                // Never let GA's own completion/progress notification form a feedback loop.
                if (notice.pkg == context.packageName) return@synchronized

                val seenKey = seenKey(notice.key)
                val signature = fingerprint(notice)
                if (prefs.getString(seenKey, null) == signature) return@synchronized

                // Stage the duplicate marker; it is flushed on every exit path below so
                // a re-post of identical content is suppressed whether or not a rule fired.
                val edit = prefs.edit().putString(seenKey, signature)

                val rule = try {
                    // Only the FIRST enabled rule that matches fires. If a notification
                    // could satisfy several rules, storage order decides the winner.
                    storedRules(prefs).firstOrNull { it.enabled && matches(it, notice) }
                } catch (e: Exception) {
                    Log.w(TAG, "stored rules could not be read", e)
                    return@synchronized
                } ?: run {
                    if (!edit.commit()) Log.w(TAG, "unable to persist notification duplicate state")
                    return@synchronized
                }

                val now = System.currentTimeMillis()
                val fireKey = lastFireKey(rule.id)
                val last = prefs.getLong(fireKey, 0L)
                if (rule.cooldownMs > 0L && last > 0L && now >= last && now - last < rule.cooldownMs) {
                    if (!edit.commit()) Log.w(TAG, "unable to persist notification duplicate state")
                    return@synchronized
                }

                // Persist duplicate marker + cooldown stamp in one blocking write instead of two.
                if (!edit.putLong(fireKey, now).commit()) {
                    Log.w(TAG, "unable to persist notification trigger state")
                    return@synchronized
                }

                // SECURITY: notice.title / notice.body() originate from arbitrary apps or
                // remote senders and are UNTRUSTED. They are forwarded to the agent only as
                // context; the executed task is the operator-defined rule.task, never content
                // derived from the notification. Downstream must treat the body as tainted
                // input (prompt-injection surface) — see notif_trigger_sop security note.
                if (!NativeNotifTriggerDispatch.enqueue(
                        context.applicationContext, rule.id, rule.task,
                        notice.pkg, notice.title, notice.body(),
                    )) {
                    prefs.edit().remove(fireKey).commit()
                }
            }
        } catch (e: Exception) {
            // NotificationListener callbacks must not take down the listener process.
            Log.w(TAG, "native notification callback failed", e)
        }
    }

    /** A removal clears its duplicate marker, so a later re-post can match again. */
    fun onNotificationRemoved(context: Context, sbn: StatusBarNotification) {
        try {
            synchronized(lock) {
                if (!prefs(context).edit().remove(seenKey(sbn.key)).commit()) {
                    Log.w(TAG, "unable to clear removed-notification state")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "native notification removal callback failed", e)
        }
    }

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(PREF, Context.MODE_PRIVATE)

    private fun listenerEnabled(): Boolean = NotifService.instance != null

    private fun lifecycle(
        ok: Boolean,
        running: Boolean,
        listenerEnabled: Boolean,
        ruleCount: Int,
        error: String,
    ): JSONObject = JSONObject()
        .put("ok", ok)
        .put("running", running)
        .put("listener_enabled", listenerEnabled)
        .put("rule_count", ruleCount)
        .put("error", error)

    private fun rulesResponse(prefs: SharedPreferences, rules: List<Rule>): JSONObject {
        val running = prefs.getBoolean(KEY_RUNNING, false)
        val listenerEnabled = listenerEnabled()
        return lifecycle(
            ok = true,
            running = running,
            listenerEnabled = listenerEnabled,
            ruleCount = rules.size,
            error = if (running && !listenerEnabled) LISTENER_ERROR else "",
        ).put("rules", rulesArray(rules))
    }

    private fun requiredRuleId(rawId: Any?): String {
        if (rawId !is String) throw IllegalArgumentException("notification rule id must be a string")
        val ruleId = rawId.trim()
        if (ruleId.isEmpty()) throw IllegalArgumentException("notification rule id must not be empty")
        return ruleId
    }

    private fun persistRules(
        prefs: SharedPreferences,
        rules: List<Rule>,
        ruleId: String? = null,
    ): JSONObject {
        // Re-parse the whole candidate set so every management operation has the
        // same strict schema, duplicate-ID, and cardinality checks as start().
        val validated = parseRules(rulesArray(rules))
        val edit = prefs.edit().putString(KEY_RULES, encodeRules(validated))
        if (ruleId != null) edit.remove(lastFireKey(ruleId))
        if (!edit.commit()) throw IllegalStateException("unable to persist native notification rules")
        return rulesResponse(prefs, validated)
    }

    private fun storedRules(prefs: SharedPreferences): List<Rule> =
        parseRules(JSONArray(prefs.getString(KEY_RULES, "[]") ?: "[]"))

    private fun parseRules(rawRules: JSONArray): List<Rule> {
        if (rawRules.length() > MAX_RULES) {
            throw IllegalArgumentException("too many notification rules (max $MAX_RULES)")
        }
        val ids = HashSet<String>()
        val rules = ArrayList<Rule>(rawRules.length())
        for (index in 0 until rawRules.length()) {
            val rawRule = rawRules.opt(index)
            if (rawRule !is JSONObject) invalid(index, "must be an object")
            rejectUnknownFields(rawRule, index)
            val id = requiredString(rawRule, "id", index, trim = true, allowEmpty = false)
            if (!ids.add(id)) invalid(index, "duplicate id '$id'")
            val pkg = requiredString(rawRule, "pkg", index, trim = true, allowEmpty = true)
            val rawKeywords = requiredValue(rawRule, "keywords", index)
            if (rawKeywords !is JSONArray) invalid(index, "keywords must be an array of strings")
            val keywords = ArrayList<String>(rawKeywords.length())
            for (keywordIndex in 0 until rawKeywords.length()) {
                val value = rawKeywords.opt(keywordIndex)
                if (value !is String || value.trim().isEmpty()) {
                    invalid(index, "keywords[$keywordIndex] must be a non-empty string")
                }
                keywords += value.trim()
            }
            val task = requiredString(rawRule, "task", index, trim = false, allowEmpty = false)
            if (task.isBlank()) invalid(index, "task must not be blank")
            val enabled = requiredValue(rawRule, "enabled", index)
            if (enabled !is Boolean) invalid(index, "enabled must be boolean")
            val cooldownMs = requiredNonNegativeLong(rawRule, "cooldown_ms", index)
            rules += Rule(id, pkg, keywords, task, enabled, cooldownMs)
        }
        return rules
    }

    private fun rejectUnknownFields(rule: JSONObject, index: Int) {
        val keys = rule.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            if (key !in ruleFields) invalid(index, "unsupported field '$key'")
        }
    }

    private fun requiredValue(rule: JSONObject, field: String, index: Int): Any {
        if (!rule.has(field) || rule.isNull(field)) invalid(index, "missing $field")
        return rule.get(field)
    }

    private fun requiredString(
        rule: JSONObject,
        field: String,
        index: Int,
        trim: Boolean,
        allowEmpty: Boolean,
    ): String {
        val value = requiredValue(rule, field, index)
        if (value !is String) invalid(index, "$field must be a string")
        val result = if (trim) value.trim() else value
        if (!allowEmpty && result.isEmpty()) invalid(index, "$field must not be empty")
        return result
    }

    private fun requiredNonNegativeLong(rule: JSONObject, field: String, index: Int): Long {
        val raw = requiredValue(rule, field, index)
        if (raw !is Number) invalid(index, "$field must be a non-negative integer")
        val value = raw.toDouble()
        if (value.isNaN() || value.isInfinite() || value < 0.0 || floor(value) != value ||
            value > Long.MAX_VALUE.toDouble()) {
            invalid(index, "$field must be a non-negative integer")
        }
        return raw.toLong()
    }

    private fun rulesArray(rules: List<Rule>): JSONArray {
        val encoded = JSONArray()
        for (rule in rules) {
            val keywords = JSONArray()
            for (keyword in rule.keywords) keywords.put(keyword)
            encoded.put(JSONObject()
                .put("id", rule.id)
                .put("pkg", rule.pkg)
                .put("keywords", keywords)
                .put("task", rule.task)
                .put("enabled", rule.enabled)
                .put("cooldown_ms", rule.cooldownMs))
        }
        return encoded
    }

    private fun encodeRules(rules: List<Rule>): String = rulesArray(rules).toString()

    // A disconnect can hide removal callbacks. Reconcile only duplicate markers,
    // then baseline what Android reports now; preserve per-rule cooldown accounting.
    private fun clearSeenState(prefs: SharedPreferences, edit: SharedPreferences.Editor) {
        for (key in prefs.all.keys) {
            if (key.startsWith(SEEN_PREFIX)) edit.remove(key)
        }
    }

    private fun clearTransientState(prefs: SharedPreferences, edit: SharedPreferences.Editor) {
        for (key in prefs.all.keys) {
            if (key.startsWith(SEEN_PREFIX) || key.startsWith(LAST_FIRE_PREFIX)) edit.remove(key)
        }
    }

    private fun baseline(edit: SharedPreferences.Editor, active: Collection<StatusBarNotification>) {
        for (sbn in active) {
            val notice = noticeOf(sbn) ?: continue
            edit.putString(seenKey(notice.key), fingerprint(notice))
        }
    }

    private fun noticeOf(sbn: StatusBarNotification): Notice? {
        val key = sbn.key ?: return null
        val pkg = sbn.packageName ?: return null
        val extras = sbn.notification?.extras
        val title = extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras?.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
        // Messaging/big-text/inbox notifications carry the real body outside EXTRA_TEXT.
        val bigText = extras?.let { e ->
            val parts = mutableListOf<String>()
            e.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.let { parts.add(it) }
            e.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.let { parts.add(it) }
            e.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
                ?.mapNotNull { it?.toString() }
                ?.let { parts.addAll(it) }
            parts.filter { it.isNotEmpty() }.distinct().joinToString("\n")
        }.orEmpty()
        return Notice(key, pkg, title, text, bigText)
    }

    private fun matches(rule: Rule, notice: Notice): Boolean {
        if (rule.pkg.isNotEmpty() && rule.pkg != notice.pkg) return false
        if (rule.keywords.isEmpty()) return true
        val haystack = (notice.title + "\n" + notice.body()).lowercase(Locale.ROOT)
        return rule.keywords.all { haystack.contains(it.lowercase(Locale.ROOT)) }
    }

    private fun seenKey(notificationKey: String): String = SEEN_PREFIX + sha256(notificationKey)

    private fun lastFireKey(ruleId: String): String = LAST_FIRE_PREFIX + sha256(ruleId)

    // Content signature for one notification key. Excludes the key itself (the
    // seen_ marker is already keyed by it), so it only detects in-place content
    // changes that warrant re-firing.
    private fun fingerprint(notice: Notice): String = sha256(
        notice.pkg + "\u0000" + notice.title + "\u0000" +
            notice.text + "\u0000" + notice.bigText,
    )

    private fun sha256(value: String): String {
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(StandardCharsets.UTF_8))
        val digits = "0123456789abcdef".toCharArray()
        val output = CharArray(bytes.size * 2)
        for (index in bytes.indices) {
            val byte = bytes[index].toInt() and 0xff
            output[index * 2] = digits[byte ushr 4]
            output[index * 2 + 1] = digits[byte and 0x0f]
        }
        return String(output)
    }

    private fun invalid(index: Int, message: String): Nothing =
        throw IllegalArgumentException("invalid notification rule[$index]: $message")
}

/**
 * Fixed-task handoff. Each rule has one unique WorkManager chain, while the
 * shared tag lets stop cancel every native-trigger chain without touching alarms.
 */
internal object NativeNotifTriggerDispatch {
    private const val TAG = "GA.NativeNotifDispatch"
    private const val WORK_NAME_PREFIX = "ga_native_notif_trigger_"
    private const val WORK_TAG = "ga_native_notif_trigger"
    internal const val INPUT_TASK = "task"
    internal const val INPUT_PKG = "notif_pkg"
    internal const val INPUT_TITLE = "notif_title"
    internal const val INPUT_TEXT = "notif_text"
    internal const val BUSY_RESULT = "busy"
    internal const val MAX_BUSY_RETRIES = 3
    private const val RETRY_BACKOFF_SECONDS = 10L

    fun enqueue(
        context: Context,
        ruleId: String,
        task: String,
        pkg: String = "",
        title: String = "",
        text: String = "",
    ): Boolean {
        val appContext = context.applicationContext
        return runCatching {
            val request = OneTimeWorkRequestBuilder<NativeNotifTriggerWorker>()
                .setInputData(
                    Data.Builder()
                        .putString(INPUT_TASK, task)
                        .putString(INPUT_PKG, pkg)
                        .putString(INPUT_TITLE, title)
                        .putString(INPUT_TEXT, text)
                        .build(),
                )
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    RETRY_BACKOFF_SECONDS,
                    TimeUnit.SECONDS,
                )
                .addTag(WORK_TAG)
                .build()
            // KEEP is intentional: while a rule's task is still queued/running, later
            // matching notifications for the SAME rule are dropped rather than piling up.
            // Combined with the per-rule cooldown this bounds agent load; the tradeoff is
            // that events arriving during a long-running task are silently skipped.
            WorkManager.getInstance(appContext).enqueueUniqueWork(
                WORK_NAME_PREFIX + ruleId,
                ExistingWorkPolicy.KEEP,
                request,
            )
            Log.i(TAG, "enqueued fixed native notification task for rule=$ruleId")
            true
        }.getOrElse { error ->
            Log.e(TAG, "unable to enqueue fixed native notification task for rule=$ruleId", error)
            false
        }
    }

    fun cancelRule(context: Context, ruleId: String) {
        WorkManager.getInstance(context.applicationContext)
            .cancelUniqueWork(WORK_NAME_PREFIX + ruleId)
    }

    fun cancel(context: Context) =
        WorkManager.getInstance(context.applicationContext).cancelAllWorkByTag(WORK_TAG)
}

/**
 * Cold-boot-capable native notification dispatcher. Only the explicit busy
 * result is retried; all terminal Python results and infrastructure failures
 * deliberately finish, so WorkManager never retries an arbitrary agent error.
 */
class NativeNotifTriggerWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {
    override fun doWork(): Result {
        val task = inputData.getString(NativeNotifTriggerDispatch.INPUT_TASK)
        if (task.isNullOrBlank()) {
            Log.w(TAG, "native notification worker missing fixed task")
            return Result.success()
        }
        val pkg   = inputData.getString(NativeNotifTriggerDispatch.INPUT_PKG)   ?: ""
        val title = inputData.getString(NativeNotifTriggerDispatch.INPUT_TITLE) ?: ""
        val text  = inputData.getString(NativeNotifTriggerDispatch.INPUT_TEXT)  ?: ""

        val result = runCatching {
            if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
            if (!Py.ready) Py.boot(File(applicationContext.filesDir, "ga").absolutePath, applicationContext.packageName)
            Py.call("call_once", task, pkg, title, text)
        }.onFailure { error ->
            Log.e(TAG, "native notification worker failed", error)
        }.getOrNull()

        if (result == NativeNotifTriggerDispatch.BUSY_RESULT &&
            runAttemptCount < NativeNotifTriggerDispatch.MAX_BUSY_RETRIES) {
            Log.i(TAG, "native notification agent busy; retry ${runAttemptCount + 1}/" +
                NativeNotifTriggerDispatch.MAX_BUSY_RETRIES)
            return Result.retry()
        }
        if (result == NativeNotifTriggerDispatch.BUSY_RESULT) {
            Log.w(TAG, "native notification busy retry cap exhausted")
        }
        return Result.success()
    }

    private companion object {
        const val TAG = "GA.NativeNotifWorker"
    }
}
