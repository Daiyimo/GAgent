package com.ljq.ga

import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject

/**
 * 透明中转 Activity: 磁贴/桌面快捷方式的开录意图落在这里 —— 它是「可见 Activity」这一 A34
 * mic-FGS 前置条件的最小满足体。不画 UI, 起完会话就 finish, 用户只感到「点一下就在录了」。
 *
 * 权限缺失(首次从磁贴开录且未授麦克风)时: 本 Activity 不是 MainActivity, Sense.perm 的系统授权框
 * 要求 MainActivity 在前台才弹得出, 故这条路只回 toast 引导用户「去 GA 内授权」, 不在这里弹框也不死等
 * (与 /sense/session start 的 need_perm 语义一致)。授权后再点磁贴即可。
 */
class SenseQuickActivity : Activity() {

    companion object {
        const val ACTION_START = "com.ljq.ga.SENSE_QUICK_START"
        const val ACTION_STOP = "com.ljq.ga.SENSE_QUICK_STOP"
        // 磁贴/快捷方式无法让用户勾选源, 用最小可用集: 只录音(采集面最小, 无 bystander 之外的额外权限面)。
        // 要位置/同场者等多源, 走 GA 内的显式 /sense.session start。
        private val QUICK_SOURCES = listOf("mic")
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        // 防混淆代理: 本 Activity 必须 exported(磁贴 PendingIntent 与桌面快捷方式要启它), 但「开麦」是隐私动作,
        // 只允许本应用(磁贴/快捷方式都是 GA 自身)与 launcher 发起。A34+ 能拿到发起方 uid, 非本应用直接拒;
        // 低版本无此 API, 靠 mic 常驻指示灯 + FGS 通知兜底(开麦对用户永远可见)。
        if (Build.VERSION.SDK_INT >= 34) {
            val fromUid = runCatching { launchedFromUid }.getOrDefault(-1)
            val launcherOk = fromUid == android.os.Process.myUid() || fromUid == android.os.Process.SYSTEM_UID
            if (fromUid >= 0 && !launcherOk && !isLauncherUid(fromUid)) { finish(); return }
        }
        val stop = intent?.action == ACTION_STOP
        val ctx = applicationContext
        // 关键: Sense.session 内部会 startForegroundService 后**忙等** SenseService.live(由 onStartCommand 置位),
        // 而 Service 的 onStartCommand 也跑在主线程 —— 若在本 Activity 的 onCreate(主线程)直调, 二者互锁, 必等满
        // 3s 超时且回报「未启动」, 随后 finish 才让 Service 真正起来: 既卡 UI 又谎报失败。故必须放后台线程跑,
        // 主线程只留着让 onStartCommand 能被调度; 且**不提前 finish** —— 活动保持可见直到 start 返回, 正好覆盖
        // startForeground(microphone) 那一刻(A34 要求 mic FGS 由可见 Activity 起)。
        Thread {
            val res = runCatching {
                if (stop) {
                    Sense.session(ctx, JSONObject().put("action", "stop"))
                } else {
                    Sense.session(ctx, JSONObject().put("action", "start")
                        .put("sources", JSONArray(QUICK_SOURCES))
                        .put("label", "快捷记录"))
                }
            }.getOrElse { JSONObject().put("ok", 0).put("error", it.toString()) }
            runOnUiThread {
                toast(stop, res)
                // 磁贴态刷新: 请系统重新回调 onStartListening(否则标签/高亮只在下次下拉面板时才更新)
                runCatching {
                    android.service.quicksettings.TileService.requestListeningState(
                        this, ComponentName(this, SenseTileService::class.java))
                }
                finish()
            }
        }.start()
    }

    /** 发起方是否默认桌面(用户从 launcher 长按快捷方式进来是合法路径)。取不到一律放行, 不因判定失败误伤真实用户。 */
    private fun isLauncherUid(uid: Int): Boolean = runCatching {
        val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        val ri = packageManager.resolveActivity(home, android.content.pm.PackageManager.MATCH_DEFAULT_ONLY)
        val pkg = ri?.activityInfo?.packageName ?: return true
        packageManager.getPackageUid(pkg, 0) == uid
    }.getOrDefault(true)

    private fun toast(stop: Boolean, res: JSONObject) {
        val src = res.optJSONObject("sources")
        val micOn = src?.optJSONObject("mic")?.optString("state") == "on"
        val degraded = res.optString("degraded_to")
        val msg = when {
            stop -> "已停止记录"
            micOn -> "已开始记录 · 下拉通知可停止"
            degraded == "bg_start_blocked" || degraded == "no_activity" ->
                "请在 GA 前台再点一次"
            res.optJSONArray("need_perm")?.length() ?: 0 > 0 ->
                "需要麦克风权限, 请授权后重试"
            else -> "无法开始记录: ${degraded.ifEmpty { res.optString("error", "未知") }}"
        }
        runCatching { Toast.makeText(this, msg, Toast.LENGTH_SHORT).show() }
    }
}
