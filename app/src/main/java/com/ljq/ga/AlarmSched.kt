package com.ljq.ga

import android.content.Context
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import androidx.work.BackoffPolicy
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

// 定时闹钟: Python 只管"下次触发绝对时刻(at, epoch ms) + 重复间隔(every ms, 0=一次性) + prompt",
//   Kotlin 只负责调度/持久化/重排, 不解析任何人类时间。省电靠 WorkManager(Doze 友好, 系统合批唤醒)。
//   持久化用 SharedPreferences(每个 id 一条 JSON), WorkManager 自身也跨重启持久化 → 双保险。
object AlarmSched {
    private const val PREF = "ga_alarms"
    private const val TAG_PREFIX = "ga_alarm_"   // uniqueWorkName = TAG_PREFIX + id
    /** WorkManager Result.retry 初始退避；与 NativeNotifTriggerDispatch 同量级，指数退避。 */
    internal const val RETRY_BACKOFF_SECONDS = 10L

    private fun store(ctx: Context) = ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)

    // 新增/更新一个闹钟(id 相同则覆盖, 幂等)。at<=now 也照排, 交给 WorkManager 立即触发。
    @Synchronized fun set(ctx: Context, id: String, at: Long, every: Long, prompt: String) {
        val a = JSONObject().put("id", id).put("at", at).put("every", every).put("prompt", prompt)
        store(ctx).edit().putString(id, a.toString()).apply()
        schedule(ctx, id, at, every, prompt)
    }

    // 删除一个闹钟: 撤调度 + 清存储。
    @Synchronized fun del(ctx: Context, id: String) {
        WorkManager.getInstance(ctx).cancelUniqueWork(TAG_PREFIX + id)
        store(ctx).edit().remove(id).apply()
    }

    // 列出所有闹钟(供 /alarm/list)。
    @Synchronized fun list(ctx: Context): JSONArray {
        val arr = JSONArray()
        for ((_, v) in store(ctx).all) runCatching { arr.put(JSONObject(v as String)) }
        return arr
    }

    // 真正下发一次调度: 计算 now→at 的延迟(负数归零 → 立即), 唯一名替换旧任务。
    private fun schedule(ctx: Context, id: String, at: Long, every: Long, prompt: String) {
        val delay = (at - System.currentTimeMillis()).coerceAtLeast(0L)
        val data = Data.Builder()
            .putString("id", id).putLong("at", at).putLong("every", every).putString("prompt", prompt)
            .build()
        val req = OneTimeWorkRequestBuilder<AlarmWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setInputData(data)
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                RETRY_BACKOFF_SECONDS,
                TimeUnit.SECONDS,
            )
            .addTag(TAG_PREFIX + id)
            .build()
        // REPLACE: 同 id 重设直接顶掉旧的, 天然幂等(用户重复 set 不会堆叠)。
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork(TAG_PREFIX + id, ExistingWorkPolicy.REPLACE, req)
    }

    // Worker 触发后调用: 若是重复闹钟(every>0)则按 every 递推下次时刻并重排; 一次性则清存储。
    // 仅在 call_once 真正受理(非 defer 拒绝)后调用 —— 拒绝时保留存储项, 由 Result.retry 再试(A12)。
    internal fun onFired(ctx: Context, id: String, at: Long, every: Long, prompt: String) {
        if (every > 0L) {
            // 从上次 at 起步累加 every, 跳过所有已错过的周期, 保证 next 落在未来(避免补跑风暴)。
            var next = at + every
            val now = System.currentTimeMillis()
            if (next <= now) { val k = (now - next) / every + 1; next += k * every }
            set(ctx, id, next, every, prompt)   // 复用 set: 更新存储 + 重排下一枪
        } else {
            store(ctx).edit().remove(id).apply()
        }
    }

    /**
     * call_once 结构化拒绝/未就绪：不可推进 onFired、不可 remove 存储。
     * 与 plan §6-A12 / NativeNotif busy 语义对齐；额外覆盖 cap_full/low_memory/multi_off/not_ready
     *（Python 现发 busy/not_ready；其余为预留拒绝码，Kotlin 侧已识别以免将来蒸发）。
     */
    internal fun isDeferResult(result: String?): Boolean {
        if (result.isNullOrBlank()) return false
        return when (result.trim()) {
            "busy", "not_ready", "cap_full", "low_memory", "multi_off" -> true
            else -> false
        }
    }
}

/**
 * 后台唤醒执行体: 确保 Python 已就绪 → 调 call_once(prompt) → 仅成功受理后递推/清理。
 *
 * A12 修正（相对旧实现「无论成败都 onFired」）:
 * - busy / not_ready / cap_full / low_memory / multi_off → 不 onFired、不删 pref、Result.retry(+指数退避)
 * - 一次性闹钟：call_once 成功返回终态前绝不 remove
 * - 与 NativeNotifTriggerWorker 的差异：通知事件可丢（有 MAX_BUSY_RETRIES 上限）；闹钟不可静默蒸发，
 *   故此处**不设** busy 重试上限，靠 WorkManager 退避持续改期直到受理或用户 del
 * - Worker ~10min 系统约束：call_once 仍可能同步堵住 doWork 至任务结束（既有行为）；拒绝路径立即 retry，
 *   不占用长窗口。长跑任务若被系统杀，pref 仍在（仅 onFired 后才清一次性），下次进程起来可再被
 *   用户/list 看见；完整前台服务保活不在本步范围。
 */
class AlarmWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {
    override fun doWork(): Result {
        val id = inputData.getString("id") ?: return Result.success()
        val at = inputData.getLong("at", 0L)
        val every = inputData.getLong("every", 0L)
        val prompt = inputData.getString("prompt") ?: ""

        val result = runCatching {
            if (!Python.isStarted())
                Python.start(AndroidPlatform(applicationContext))
            if (!Py.ready)
                Py.boot(File(applicationContext.filesDir, "ga").absolutePath, applicationContext.packageName)
            Py.call("call_once", prompt)
        }.onFailure {
            Log.e(TAG, "alarm $id fire error", it)
        }.getOrNull()

        // 基础设施失败(null) 与结构化拒绝同属「未受理」: 一次性命中不可蒸发
        if (result == null || AlarmSched.isDeferResult(result)) {
            Log.i(
                TAG,
                "alarm $id deferred result=${result ?: "infra_error"} attempt=$runAttemptCount; " +
                    "keep store, Result.retry (no onFired)",
            )
            return Result.retry()
        }

        Log.i(TAG, "alarm $id accepted result=${result.take(80)}; onFired every=$every")
        AlarmSched.onFired(applicationContext, id, at, every, prompt)
        return Result.success()
    }

    private companion object {
        const val TAG = "GA.AlarmWorker"
    }
}
