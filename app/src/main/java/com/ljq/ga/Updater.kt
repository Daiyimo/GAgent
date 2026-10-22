package com.ljq.ga

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

// 应用内热更新(OTA) 机制层: 取清单 / 下载 / 校验 sha256 / 拉起系统安装器。
//  策略与 UI(版本比对、跳过、弹窗)在前端 app.js —— 机制(网络/文件/Intent)在原生, 边界清晰。
//  ⚠ 配置保留是天然结论, 非额外逻辑: 同 applicationId + 同签名(debug.keystore)→ Android 原地升级,
//    /data/data/com.ljq.ga(mykey.py / kv / 会话)整体保留。前提不变量: 发布的 APK 必须是同签名的
//    CI 产物; 换签名会 INSTALL_FAILED_UPDATE_INCOMPATIBLE。下载/安装本身不触碰任何用户数据。
//  双通道(2026-08): 正式 latest.json 与 beta/latest.json 隔离; 通道=设置覆盖(若有)→BuildConfig.CHANNEL。
object Updater {
    private const val PREFS = "ga_ota"
    private const val KEY_CHANNEL = "channel"   // "" | "official" | "beta"; 空=跟随构建戳

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()
    private val exec = Executors.newSingleThreadExecutor()

    @Volatile private var state = "idle"     // idle | downloading | verifying | ready | error
    @Volatile private var pct = 0
    @Volatile private var err = ""
    @Volatile private var apk: File? = null
    private val busy = AtomicBoolean(false)   // 原子幂等闸: 两个桥线程并发调 download 时仅一个进入

    // 有效通道: 设置覆盖优先, 否则 BuildConfig.CHANNEL(默认 official)。仅识别 beta; 其它一律正式。
    fun channel(ctx: Context): String {
        val override = ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_CHANNEL, "")?.trim().orEmpty()
        val raw = if (override.isNotEmpty()) override else BuildConfig.CHANNEL
        return if (raw.equals("beta", ignoreCase = true)) "beta" else "official"
    }

    // 写通道覆盖。传空串=清除覆盖(回落构建戳)。非法值拒绝。
    fun setChannel(ctx: Context, ch: String): String {
        val v = ch.trim().lowercase()
        if (v !in setOf("", "official", "beta")) return jsonErr("bad-channel")
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_CHANNEL, v).apply()
        return JSONObject().put("ok", true).put("channel", channel(ctx))
            .put("build", BuildConfig.CHANNEL).toString()
    }

    fun manifestUrl(ctx: Context): String =
        if (channel(ctx) == "beta") Endpoints.UPDATE_MANIFEST_URL_BETA
        else Endpoints.UPDATE_MANIFEST_URL

    // 同步取清单: bridge 跑在 WebView 后台线程, 阻塞网络安全。失败半径小 → 返回 {"error":...} 优雅降级, 不抛。
    fun manifest(ctx: Context): String = try {
        val url = manifestUrl(ctx)
        require(url.isNotBlank()) { "Updates are available on the repository Releases page" }
        http.newCall(Request.Builder().url(url).header("Accept", "application/json").build())
            .execute().use { r ->
                if (!r.isSuccessful) return@use jsonErr("http ${r.code}")
                val body = r.body?.string() ?: return@use jsonErr("empty")
                // 附带通道元数据供前端展示(旧清单无 channel 字段时由客户端补)
                val m = JSONObject(body)
                if (!m.has("channel")) m.put("channel", channel(ctx))
                m.put("_manifestUrl", url)
                m.toString()
            }
    } catch (e: Exception) { jsonErr(e.message ?: e.javaClass.simpleName) }

    // 启动后台下载, 立即返回(并发幂等: 正在下载则忽略)。url/sha256 来自清单。
    fun download(ctx: Context, url: String, sha256: String): String {
        // 完整性是大半径不变量: 清单必须给 https 直链 + 64 位 hex sha256, 否则直接拒绝下载(不装未校验的包)。
        if (!url.startsWith("https://")) return jsonErr("insecure-url")
        val want = sha256.trim().lowercase()
        if (!Regex("^[0-9a-f]{64}$").matches(want)) return jsonErr("manifest-missing-sha256")
        if (!busy.compareAndSet(false, true)) return ok()   // 原子幂等: 已在下载则忽略
        state = "downloading"; pct = 0; err = ""; apk = null
        val app = ctx.applicationContext
        exec.execute {
            try {
                val dir = File(app.cacheDir, "ota").apply { mkdirs() }
                dir.listFiles()?.forEach { it.delete() }          // 旧包不留, 省空间
                val dst = File(dir, "update.apk")
                http.newCall(Request.Builder().url(url).build()).execute().use { r ->
                    if (!r.isSuccessful) throw IllegalStateException("http ${r.code}")
                    val body = r.body ?: throw IllegalStateException("empty body")
                    val total = body.contentLength()
                    body.byteStream().use { ins -> dst.outputStream().use { outs ->
                        val buf = ByteArray(64 * 1024); var done = 0L; var n: Int
                        while (ins.read(buf).also { n = it } >= 0) {
                            outs.write(buf, 0, n); done += n
                            if (total > 0) pct = ((done * 100) / total).toInt().coerceIn(0, 99)
                        }
                    } }
                }
                // sha256 必校验(大半径): 不匹配硬失败, 绝不安装。下载前已确保 want 是 64 位 hex。
                state = "verifying"
                if (sha256Of(dst) != want) throw IllegalStateException("sha256 mismatch")
                apk = dst; pct = 100; state = "ready"
            } catch (e: Exception) {
                err = e.message ?: e.javaClass.simpleName; state = "error"
            } finally { busy.set(false) }
        }
        return ok()
    }

    fun progress(): String = JSONObject()
        .put("state", state).put("pct", pct).put("error", err).put("ready", state == "ready").toString()

    // 拉起系统安装器(OTA 自升级: 同签名 → 原地升级, 数据不动)。Android 8+ 未授予「安装未知应用」先引导授权页。
    fun install(ctx: Context): String {
        val f = apk ?: return jsonErr("no-apk")
        return installFile(ctx, f)
    }

    // 通用装机原语: 拉起系统安装器装任意 APK(如 APK 工厂产物, 异签名新装)。用户在安装器上确认——OS 规矩, 非 GA 自我设限。
    //  ctx 可为 Service(如 BusA11yService), FLAG_ACTIVITY_NEW_TASK 使其可 startActivity。
    fun installFile(ctx: Context, f: File): String {
        if (!f.exists()) return jsonErr("no-apk")
        return try {
            if (Build.VERSION.SDK_INT >= 26 && !ctx.packageManager.canRequestPackageInstalls()) {
                ctx.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:${ctx.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return jsonErr("need-unknown-sources")
            }
            val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", f)
            ctx.startActivity(Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
            ok()
        } catch (e: Exception) { jsonErr(e.message ?: e.javaClass.simpleName) }
    }

    private fun sha256Of(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { ins -> val buf = ByteArray(64 * 1024); var n: Int
            while (ins.read(buf).also { n = it } >= 0) md.update(buf, 0, n) }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
    private fun ok() = "{\"ok\":true}"
    private fun jsonErr(m: String) = JSONObject().put("error", m).toString()
}
