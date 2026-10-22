package com.ljq.ga

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject

/**
 * 前台「任务浏览器」: agent 操作网页的**默认可见 surface**(浏览器三级路由 L1)。
 * 与 [BrowserActivity](用户人工登录, FLAG_SECURE 隐私态, GA 永不驱动)、[WebController](离屏后台) 三分:
 *   - **无 FLAG_SECURE** → droid.shot()/screencap 能截到内容(登录浏览器截图黑屏的根因不复现);
 *   - 前台真窗口真渲染 → Chromium 持续光栅化, 比离屏虚拟屏(不可见即停光栅+CDP空图)更快;
 *   - 首载 data: 哨兵页(url 含 "ga-task", 不可被真实网页 pushState 伪造) → webcdp role='fg' 经 _task_tab 硬白名单唯一绑定;
 *   - 结构上独立于登录浏览器: 本页只由 agent 经总线拉起、载 agent 任务 url, **绝不承接用户登录**, 隐私不变量#3 天然成立。
 * 用户可见"GA 操作中"横幅 + 只读地址 + 停止按钮(finish 即断 CDP tab, webcdp 自愈)。
 * 驱动: webcdp.open_url(url)(默认 background=False) → /web/ensure_fg 拉起本页 → CDP 绑哨兵 tab → Page.navigate 到真实 url。
 */
class AgentBrowserActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var addr: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 关键: 不加 FLAG_SECURE —— 本页是"给 agent 看/截图操作"的任务浏览器, 与登录浏览器的隐私职责正交(见 BrowserActivity)。
        WebView.setWebContentsDebuggingEnabled(true)   // 进程级暴露 webview_devtools_remote_<pid>, 使前台路径不依赖离屏先建也能 CDP

        val dark = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
        val fg = if (dark) 0xFFE6E6E6.toInt() else 0xFF1A1A1A.toInt()
        val barBg = if (dark) 0xFF1A1D21.toInt() else 0xFFF3F4F6.toInt()
        val accent = 0xFF2563EB.toInt()
        val d = resources.displayMetrics.density
        fun dp(v: Int) = (v * d).toInt()

        val badge = TextView(this).apply {
            text = "● GA 操作中"; textSize = 12f; setTextColor(accent); gravity = Gravity.CENTER
            setPadding(dp(10), 0, dp(10), 0)
        }
        addr = TextView(this).apply {
            text = "GA 任务浏览器 · 待命"; setTextColor(fg); textSize = 13f
            maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val stop = TextView(this).apply {
            text = "✕"; textSize = 20f; setTextColor(fg); gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
            setOnClickListener { finish() }   // 用户随时可停; finish → tab 消失 → webcdp _call 下次 OSError 自愈
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; setBackgroundColor(barBg); gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48))
            addView(badge); addView(addr); addView(stop)
        }
        web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
            tuneForBrowsing(settings)
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)   // 复用登录态/SSO 跳转链
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, url: String) {
                    val isHome = url.startsWith("data:") && url.contains(AgentBrowser.MARK)
                    AgentBrowser.lastUrl = url                       // 导航后 status() 上报真实 url, 让 _task_tab 路径② 继续可用
                    addr.text = if (isHome) "GA 任务浏览器 · 待命" else url
                    if (isHome) AgentBrowser.onHomeReady(this@AgentBrowserActivity)
                }
                override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                    // 渲染进程被系统回收(OOM/后台): 销毁旧 WebView 防整 Activity 崩, 直接收尾让下次 open_url 重建净页
                    runCatching { (view.parent as? ViewGroup)?.removeView(view); view.destroy() }
                    AgentBrowser.onGone(this@AgentBrowserActivity)
                    finish()
                    return true
                }
            }
        }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; fitsSystemWindows = true
            setBackgroundColor(if (dark) 0xFF111315.toInt() else 0xFFFFFFFF.toInt())
            addView(bar); addView(web)
        })
        window.statusBarColor = barBg
        if (!dark) window.decorView.systemUiVisibility =
            window.decorView.systemUiVisibility or android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR

        web.loadUrl(AgentBrowser.HOME_URL)   // 先载哨兵页固定 tab 身份; webcdp 绑定后再 Page.navigate 到真实 url
    }

    override fun onDestroy() {
        AgentBrowser.onGone(this)
        runCatching { (web.parent as? ViewGroup)?.removeView(web); web.destroy() }
        super.onDestroy()
    }

    companion object {
        /** WebSettings 调到"当浏览器用"的语义(内嵌 WebView 默认值是为 App 片段调的, 逐项翻到接近 Chrome)。 */
        fun tuneForBrowsing(s: WebSettings) {
            s.javaScriptEnabled = true
            s.domStorageEnabled = true
            s.databaseEnabled = true
            s.userAgentString = s.userAgentString.replace("; wv", "")           // 去 WebView 标记, 更像真实浏览器
            s.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE   // targetSdk 默认 NEVER_ALLOW 会静默拦 https 页内 http 资源→缺图/空脚本
            s.useWideViewPort = true                                            // 尊重 <meta viewport>, 与 Chrome 布局语义一致
            s.loadWithOverviewMode = true
            s.cacheMode = WebSettings.LOAD_DEFAULT                              // 显式=依 HTTP 缓存(勿 clearCache, 二访提速靠它)
            s.javaScriptCanOpenWindowsAutomatically = true
            s.setSupportZoom(true); s.builtInZoomControls = true; s.displayZoomControls = false
        }
    }
}

/**
 * 前台任务浏览器的进程级控制器: 总线 /web/ensure_fg 幂等拉起/复用本页并阻塞等哨兵就绪。
 * 单实例语义: agent 的前台浏览需求共用一个可见 tab(同 CookieManager 登录态), 与离屏 WebController 各自独立。
 */
object AgentBrowser {
    const val MARK = "ga-task"
    const val HOME_URL = "data:text/html,<title>ga-task</title>"   // url 含 ga-task, 供 webcdp _task_tab 硬白名单锚定(data: 不可伪造)

    @Volatile private var inst: AgentBrowserActivity? = null
    @Volatile private var homeReady = false
    @Volatile private var launching = false            // 防并发 ensure 叠出第二实例(NanoHTTPD 每请求一线程)
    @Volatile var lastUrl = HOME_URL                   // 当前 tab 真实 url(导航后更新), 供 _task_tab 路径②在导航后仍能按 url 唯一识别(不再仅靠 pin 单点)
    private val lock = Object()

    /** 由 Bus worker 线程调用: 拉起(或复用)前台任务浏览器并**无条件带到前台**(兑现 L1"用户可见"契约: 第二次 open_url 时旧实例
     *  可能已被切后台, REORDER_TO_FRONT 前移而非叠新实例)。首次拉起阻塞至哨兵页就绪或超时。返回 {ok,url,visible}。 */
    fun ensure(ctx: Context): String {
        synchronized(lock) {
            if (inst == null) {
                if (!launching) { launching = true; startBrowser(ctx) }   // 唯一发起者启动, 其余进入者只等待(防双实例)
                val deadline = System.currentTimeMillis() + 8000
                while (!homeReady && System.currentTimeMillis() < deadline) {
                    try { lock.wait(200) } catch (_: InterruptedException) { break }
                }
                if (!homeReady) launching = false   // 启动失败(BAL 拦截/超时): 复位, 允许下次重试
            } else {
                startBrowser(ctx)   // 已存在: 无条件前移到前台(SINGLE_TOP+REORDER 不重建, 只 onNewIntent)
            }
        }
        return status()
    }

    private fun startBrowser(ctx: Context) {
        runCatching {
            ctx.startActivity(Intent(ctx, AgentBrowserActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
    }

    fun status(): String = JSONObject()
        .put("ok", if (homeReady) 1 else 0).put("url", lastUrl).put("visible", inst != null).toString()

    fun onHomeReady(a: AgentBrowserActivity) {
        synchronized(lock) { inst = a; homeReady = true; launching = false; lock.notifyAll() }
    }

    fun onGone(a: AgentBrowserActivity) {
        synchronized(lock) { if (inst === a) { inst = null; homeReady = false; launching = false; lastUrl = HOME_URL } }
    }
}
