package com.ljq.ga

import android.app.Presentation
import android.content.Context
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.os.Handler
import android.os.Looper
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject
import java.util.concurrent.CountDownLatch

/**
 * 离屏浏览器容器: App 自有进程内的一个 WebView, 渲染在 App 自建的离屏 VirtualDisplay 上(Presentation 宿主),
 * 永不进入用户可见对话 Activity 的视图树、永不落默认屏 → GA 操作浏览器时对话页始终前台可见。
 * 与 VdHelper/vdisplay(shell uid 把第三方 App 拉到虚拟屏)本质不同: 这里是 App 自有内容 + App 自有屏,
 * 全走公开 SDK, 无需 shell/反射/overlay 权限。
 * 复用登录态: CookieManager 进程级共享 → 本 WebView 与对话 WebView 及任意登录 WebView 同一 cookie jar 且持久。
 * 由 webcdp.py 经 CDP(webview_devtools_remote_<pid>) 驱动: setWebContentsDebuggingEnabled 暴露本 tab;
 * 截图经 CDP Page.captureScreenshot 回传对话页(temp png), 对话页只读图、绝不被导航(不变量#1/#2)。
 */
object WebController {
    private const val VIEWPORT_W = 1080
    private const val VIEWPORT_H = 1920
    private const val DENSITY = 320
    // 哨兵首页: url 含 "ga-automation" 让 webcdp._auto_tab 在 /json 里唯一锚定本 tab(不变量#3)。
    // about:blank 会与 BrowserActivity(用户可见登录浏览器)的空白页撞车导致识别歧义。
    private const val AUTO_HOME = "data:text/html,<title>ga-automation</title>"

    @Volatile private var wv: WebView? = null
    private var reader: ImageReader? = null
    private var vd: VirtualDisplay? = null
    private var presentation: Presentation? = null

    /** 幂等: 首建离屏 WebView+虚拟屏+Presentation, 之后直接返回。阻塞等主线程建完(由 Bus worker 线程调用)。
     *  ok() 读 WebView.title/url 必须在 WebView 构造线程(主线程): 故建屏与结果计算都在同一 post 里完成,
     *  绝不在 Bus worker 线程碰 WebView(否则 checkThread() 抛 RuntimeException, /web/ensure 恒 500)。
     *  失败半径可控: 建屏/建窗异常经 latch 冒泡给 Bus → 显式 500, 不留半死单例。 */
    fun ensure(ctx: Context): String {
        val latch = CountDownLatch(1); var err: String? = null; var result: String? = null
        Handler(Looper.getMainLooper()).post {
            try {
                if (wv == null) create(ctx.applicationContext)   // 幂等: 已建则跳过
                result = ok(wv!!)                                // title/url 读在主线程(WebView 构造线程)
            } catch (e: Throwable) { err = e.toString(); teardown() }
            finally { latch.countDown() }
        }
        latch.await()
        err?.let { throw RuntimeException("WebController.ensure: $it") }
        return result!!
    }

    private fun ok(w: WebView) =
        JSONObject().put("ok", 1).put("title", w.title ?: "").put("url", w.url ?: "about:blank")
            .put("viewport", "${VIEWPORT_W}x${VIEWPORT_H}").toString()

    private fun create(app: Context) {
        WebView.setWebContentsDebuggingEnabled(true)   // 暴露 webview_devtools_remote_<pid>, webcdp 据此连本进程 tab
        val ir = ImageReader.newInstance(VIEWPORT_W, VIEWPORT_H, PixelFormat.RGBA_8888, 2)
        // 必须排水: VirtualDisplay 合成帧入 ir 的 BufferQueue, 满 2 帧不取即背压→合成阻塞→WebView 停渲→CDP 截图空/旧图。
        ir.setOnImageAvailableListener({ r -> runCatching { r.acquireLatestImage()?.close() } },
            Handler(Looper.getMainLooper()))
        val dm = app.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
        val virt = dm.createVirtualDisplay(
            "ga_browser", VIEWPORT_W, VIEWPORT_H, DENSITY, ir.surface,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY or
                DisplayManager.VIRTUAL_DISPLAY_FLAG_PRESENTATION
        ) ?: throw IllegalStateException("createVirtualDisplay -> null")
        val dctx = app.createDisplayContext(virt.display)
        val pres = Presentation(dctx, virt.display)
        val web = WebView(dctx).apply {
            AgentBrowserActivity.tuneForBrowsing(settings)   // 与前台任务浏览器同一套"当浏览器用"的 WebSettings(mixedContent/viewport/cache...)
            settings.setOffscreenPreRaster(true)             // 离屏关键: 不可见时仍预光栅化, 缓解渲染节流→CDP 截图空图
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            webViewClient = object : WebViewClient() {
                override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                    runCatching { (view.parent as? ViewGroup)?.removeView(view); view.destroy() }
                    teardown(); return true   // 渲染进程被回收: 拆干净, 下次 ensure() 重建净页
                }
            }
        }
        pres.setContentView(web, ViewGroup.LayoutParams(VIEWPORT_W, VIEWPORT_H))
        pres.show()                                    // 真窗+真屏 → 渲染活跃, CDP 截图非空
        web.loadUrl(AUTO_HOME)
        wv = web; reader = ir; vd = virt; presentation = pres
    }

    private fun teardown() {
        runCatching { presentation?.dismiss() }; runCatching { wv?.destroy() }
        runCatching { vd?.release() }; runCatching { reader?.close() }
        presentation = null; wv = null; vd = null; reader = null
    }
}
