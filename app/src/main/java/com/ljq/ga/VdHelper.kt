package com.ljq.ga

import android.content.AttributionSource
import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.io.File
import java.io.FileOutputStream

/**
 * 虚拟屏 helper: 由 app_process(shell uid) 独立进程运行的入口, 不是正常 app 组件, 不随 GA 主进程生死。
 * 唯一调用方 = gacore/vdisplay.py(全走 droid.adb_shell 编排), 不供 app 内直接 new。
 *   CLASSPATH=<GA apk 路径> app_process / com.ljq.ga.VdHelper <w> <h> <dpi>
 * 建成离屏 VirtualDisplay 后打印 "DISPLAY_ID=<id>" 到 stdout, 再阻塞保活 —— VirtualDisplay 生命周期
 * 绑定创建它的进程(本进程死则屏销毁, vd_stop() = kill 本进程即可, 无需显式 release)。
 * 反射/建屏失败一律打印 "ERR:<msg>" 后整进程退出(半径可控, vdisplay.py 侧据此 raise)。
 *
 * 截屏: Flyme/部分 ROM 的 `screencap -d <虚拟屏>` 拒截("Display Id not valid"), 故不依赖它 —— 本 helper
 * 把虚拟屏渲染进自带 ImageReader, 每帧(节流)落一张 PNG 到 SHOT_PATH, vd_shot() 直接读该文件(scrcpy 同款思路)。
 *
 * 反射面参考 scrcpy(FakeContext/Workarounds): shell uid 已被系统预授予创建 VirtualDisplay 所需权限,
 * DisplayManager.createVirtualDisplay(...) 本身是公开 SDK API, 只有两处必须反射:
 *   ① app_process 裸进程无现成 Context, 借 ActivityThread 反射拿一个系统 Context;
 *   ② DisplayManager(Context) 构造函数是 @hide, 反射调用。
 * createVirtualDisplay 的 AppOps 校验要求 Context 包名归属调用 uid(shell=2000→com.android.shell), 故套 ShellContext。
 * 部分 flag 常量(TRUSTED/OWN_FOCUS 等)在 SDK stub 里是 @hide 取不到, 与 scrcpy 一致改用同值字面量本地声明。
 */
object VdHelper {
    // 与 android.hardware.display.DisplayManager 同值(@hide, compileSdk stub 不可见, 故字面量本地声明)
    private const val FLAG_SUPPORTS_TOUCH = 1 shl 6
    private const val FLAG_ROTATES_WITH_CONTENT = 1 shl 7
    private const val FLAG_DESTROY_CONTENT_ON_REMOVAL = 1 shl 8
    private const val FLAG_TRUSTED = 1 shl 10
    private const val FLAG_OWN_DISPLAY_GROUP = 1 shl 11
    private const val FLAG_ALWAYS_UNLOCKED = 1 shl 12
    private const val FLAG_TOUCH_FEEDBACK_DISABLED = 1 shl 13
    private const val FLAG_OWN_FOCUS = 1 shl 14
    private const val FLAG_DEVICE_DISPLAY_GROUP = 1 shl 15

    private const val SHOT_PATH = "/data/local/tmp/ga_vd_shot.png"
    private const val META_PATH = "/data/local/tmp/ga_vd_shot.meta"   // 每次落帧后原子写 SEQ/UPTIME_MS/PID/W/H: vd_shot 据此判 新鲜度+归属当前 helper
    private const val STATUS_PATH = "/data/local/tmp/ga_vd.status"  // 建屏后写 DISPLAY_ID+PID: vdisplay.py 幂等复用/liveness 真相源, 解耦易失 stdout
    private const val SHOT_MIN_INTERVAL = 400L   // 每帧落盘节流(ms): 静态画面不重复编码, 动态画面≤400ms一帧
    private var lastShotMs = 0L                  // 以下状态只在主 Looper 线程读写(回调与 drain 同一 Handler), 无需同步
    private var pending: android.media.Image? = null
    private var pendingAtMs = 0L
    private var drainPosted = false
    private var seq = 0L

    /** 尾沿节流(纯函数): 距上次落盘不足 interval 时延后到窗口末尾, 而不是丢弃。
     *  旧实现把窗口内到达的帧直接丢掉, 画面随后静止就不再有新帧 → 磁盘上停在过渡中间帧(动作后的终态丢失)。 */
    @JvmStatic
    internal fun writeDelayMs(nowMs: Long, lastWriteMs: Long, intervalMs: Long): Long =
        (lastWriteMs + intervalMs - nowMs).coerceIn(0L, intervalMs)

    @JvmStatic
    fun main(args: Array<String>) {
        try {
            Looper.prepareMainLooper()   // ActivityThread 反射构造路径要求当前线程已有 Looper; ImageReader 回调也走此 Looper
            val w = args.getOrElse(0) { "1080" }.toInt()
            val h = args.getOrElse(1) { "1920" }.toInt()
            val dpi = args.getOrElse(2) { "320" }.toInt()

            // maxImages=3: 最多持有 1 张待写帧, 仍留余量给 acquireLatestImage 取新帧并关掉旧帧
            val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3)
            val handler = Handler(Looper.myLooper()!!)
            val drain = Runnable {
                drainPosted = false
                val img = pending ?: return@Runnable
                pending = null
                try {
                    writePng(img, w, h); seq += 1
                    writeAtomic(META_PATH, "SEQ=$seq\nUPTIME_MS=$pendingAtMs\nPID=${android.os.Process.myPid()}\nW=$w\nH=$h\n")
                } catch (_: Throwable) { /* 单帧编码失败不影响保活 */ } finally { img.close() }
                lastShotMs = SystemClock.uptimeMillis()
            }
            reader.setOnImageAvailableListener({ r ->
                val img = try { r.acquireLatestImage() } catch (_: IllegalStateException) { null } ?: return@setOnImageAvailableListener
                pending?.close(); pending = img; pendingAtMs = SystemClock.uptimeMillis()   // 只留最新一帧, 时间=该帧到达(CLOCK_MONOTONIC, 同 Python time.monotonic)
                if (!drainPosted) {
                    drainPosted = true
                    handler.postDelayed(drain, writeDelayMs(pendingAtMs, lastShotMs, SHOT_MIN_INTERVAL))
                }
            }, handler)

            val ctor = DisplayManager::class.java.getDeclaredConstructor(Context::class.java)
            ctor.isAccessible = true
            val dm = ctor.newInstance(systemContext())

            val vd = dm.createVirtualDisplay("ga_vd", w, h, dpi, reader.surface, flags())
                ?: throw IllegalStateException("createVirtualDisplay -> null(权限不足或参数非法)")

            val vid = vd.display.displayId
            writeAtomic(STATUS_PATH, "DISPLAY_ID=$vid\nPID=${android.os.Process.myPid()}\nW=$w\nH=$h\nDPI=$dpi\n")   // 原子写: vdisplay.py 幂等复用/liveness/坐标边界真相源(解耦易失 stdout)
            println("DISPLAY_ID=$vid")
            System.out.flush()
            Looper.loop()   // 阻塞保活: 本进程是 VirtualDisplay 的宿主, 进程退出即销毁
        } catch (e: Throwable) {
            println("ERR:$e")
            System.out.flush()
            kotlin.system.exitProcess(1)   // 半径可控: 建屏失败整进程退出, 不留半死状态
        }
    }

    private fun writeAtomic(path: String, text: String) {
        val tmp = File("$path.tmp"); tmp.writeText(text); tmp.renameTo(File(path))
    }

    /** RGBA_8888 帧 → PNG, 原子落盘(.tmp→rename)避免 vd_shot 读到半截。rowStride 含行填充, 按填充宽建图再裁到真实 w。*/
    private fun writePng(img: android.media.Image, w: Int, h: Int) {
        val plane = img.planes[0]
        val buf = plane.buffer
        val padded = plane.rowStride / plane.pixelStride     // 含行填充的像素宽
        val full = Bitmap.createBitmap(padded, h, Bitmap.Config.ARGB_8888)
        buf.rewind(); full.copyPixelsFromBuffer(buf)
        val bmp = if (padded != w) Bitmap.createBitmap(full, 0, 0, w, h) else full
        val tmp = File("$SHOT_PATH.tmp")
        FileOutputStream(tmp).use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        tmp.renameTo(File(SHOT_PATH))
    }

    /** flags 按 API 递进(参考 scrcpy startNew): 高版本追加 own-focus/own-display-group, 使离屏操作既能收触摸又不外溢/不抢主屏焦点。
     *  DESTROY_CONTENT_ON_REMOVAL 必设: PUBLIC 虚拟屏缺它时, 屏销毁(vd_stop kill 本进程/OOM/崩溃)瞬间
     *  AOSP 会把屏上整条 task reparent 回默认屏并置顶=内容跳到用户前台(MEIZU21 取证: display removed 后
     *  10ms GA 被 Set invisible, 被采集 app 在主屏 relaunch)。设了=就地销毁, 主屏零打扰, Recents 也不残留。*/
    private fun flags(): Int {
        var f = DisplayManager.VIRTUAL_DISPLAY_FLAG_PUBLIC or
            DisplayManager.VIRTUAL_DISPLAY_FLAG_PRESENTATION or
            DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY or
            FLAG_DESTROY_CONTENT_ON_REMOVAL or
            FLAG_SUPPORTS_TOUCH or FLAG_ROTATES_WITH_CONTENT
        if (Build.VERSION.SDK_INT >= 33) {
            f = f or FLAG_TRUSTED or FLAG_OWN_DISPLAY_GROUP or FLAG_ALWAYS_UNLOCKED or FLAG_TOUCH_FEEDBACK_DISABLED
        }
        if (Build.VERSION.SDK_INT >= 34) {
            f = f or FLAG_OWN_FOCUS   // 对齐 scrcpy --new-display: 不叠 FLAG_DEVICE_DISPLAY_GROUP(与 OWN_DISPLAY_GROUP/OWN_FOCUS 的独立输入焦点隔离相斥, 曾致注入抢默认屏焦点=打扰); 常量保留便于回滚
        }
        return f
    }

    /** app_process(shell uid) 裸进程无 Context, 反射借 ActivityThread 拿一个, 再套 ShellContext 修正包名归属。*/
    private fun systemContext(): Context {
        val atClass = Class.forName("android.app.ActivityThread")
        val at = atClass.getDeclaredConstructor().apply { isAccessible = true }.newInstance()
        atClass.getDeclaredField("sCurrentActivityThread").apply { isAccessible = true }.set(null, at)
        atClass.getDeclaredField("mSystemThread").apply { isAccessible = true }.setBoolean(at, true)
        val sys = atClass.getDeclaredMethod("getSystemContext").apply { isAccessible = true }.invoke(at) as Context
        return ShellContext(sys)
    }

    /** 系统 Context 的包名非 shell → createVirtualDisplay 的 AppOps 校验抛 "packageName must match the calling uid"。
     *  伪装为 com.android.shell(uid 2000 的包) + A12+ 提供匹配 AttributionSource(scrcpy FakeContext 同款)。*/
    private class ShellContext(base: Context) : ContextWrapper(base) {
        override fun getPackageName(): String = SHELL_PKG
        override fun getOpPackageName(): String = SHELL_PKG
        override fun getAttributionSource(): AttributionSource =
            AttributionSource.Builder(SHELL_UID).setPackageName(SHELL_PKG).build()
        companion object { const val SHELL_PKG = "com.android.shell"; const val SHELL_UID = 2000 }
    }
}
