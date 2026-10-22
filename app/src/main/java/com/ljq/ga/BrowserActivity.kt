package com.ljq.ga

import android.app.Activity
import android.app.AlertDialog
import android.content.res.Configuration
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/**
 * 用户可见登录浏览器: 普通前台 WebView, 与离屏自动化 WebView(WebController)同进程 →
 * CookieManager 进程级单例天然共享登录态, 零同步代码。用途: 目标站需人工登录(密码/验证码/2FA)时,
 * 用户在这里自己登录, GA 的 webcdp 自动化随后直接复用会话; GA 永不代填账号密码。
 * 边界(不变量#3): 本 WebView 只由用户驱动; webcdp role='browser' 经硬白名单(_auto_tab)只绑离屏 tab,
 * 结构上连不到这里。入口按钮固定空白起始页, 绝不预填 agent 最后访问的 URL(防钓鱼语境混淆)。
 */
class BrowserActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var addr: EditText
    private val ui = Handler(Looper.getMainLooper())
    private val popups = ArrayList<WebView>()   // onCreateWindow 临时 WebView: 统一登记, 导航/window.close()/Activity 销毁时回收, 防不导航弹窗(window.open('')+document.write / postMessage SSO)泄漏 Activity 视图树
    // 登录写 cookie 后 3s 内落盘(web-to-app 经验: debounce flush), 自动化侧/进程重启后才可见
    private val flushCookies = Runnable { CookieManager.getInstance().flush() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 登录界面(密码/验证码)绝不进截图: droid.shot()/screencap(DEFAULT_DISPLAY) 会整屏截到并作为上下文发第三方 LLM,
        // 与"GA 不读取你输入的密码"披露承诺一致——把承诺写进代码而非仅文案。
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        val dark = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
        val fg = if (dark) 0xFFE6E6E6.toInt() else 0xFF1A1A1A.toInt()
        val barBg = if (dark) 0xFF1A1D21.toInt() else 0xFFF3F4F6.toInt()
        val d = resources.displayMetrics.density
        fun dp(v: Int) = (v * d).toInt()

        fun iconBtn(glyph: String, onClick: () -> Unit) = TextView(this).apply {
            text = glyph; textSize = 20f; setTextColor(fg); gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(dp(44), dp(44))
            setOnClickListener { onClick() }
        }
        addr = EditText(this).apply {
            hint = "输入网址 / Enter URL"; setTextColor(fg); setHintTextColor(0xFF8A8F98.toInt())
            textSize = 14f; background = null; imeOptions = EditorInfo.IME_ACTION_GO
            // 类位必须与变体位同或(裸 VARIATION_URI 类位=NULL, 部分 IME 出降级键盘/不提交); 单行由 inputType 隐含
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
            setOnEditorActionListener { _, id, _ -> if (id == EditorInfo.IME_ACTION_GO) { go(text.toString()); true } else false }
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; setBackgroundColor(barBg); gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48))
            addView(iconBtn("←") { if (web.canGoBack()) web.goBack() else finish() })
            addView(addr)
            addView(iconBtn("⟳") { web.reload() })
            addView(iconBtn("✕") { finish() })
        }
        web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.userAgentString = settings.userAgentString.replace("; wv", "")   // 对齐 WebController: 更像真实浏览器
            settings.setSupportMultipleWindows(true)                                  // SSO 弹窗(Continue with Google 等走 window.open)
            settings.javaScriptCanOpenWindowsAutomatically = true
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)        // SSO/OAuth 跳转链需要
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean =
                    req.url.scheme !in listOf("http", "https")   // 非 http(s)(intent://等)不跟随: 登录场景无需, 挡 scheme 劫持
                override fun onPageFinished(view: WebView, url: String) {
                    if (!addr.hasFocus()) addr.setText(url)
                    ui.removeCallbacks(flushCookies); ui.postDelayed(flushCookies, 3000)
                }
            }
            webChromeClient = object : android.webkit.WebChromeClient() {
                // 单 WebView 策略: 弹窗不真开新窗, 临时 WebView 只截获其首个导航 url 转回主视图
                override fun onCreateWindow(view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: android.os.Message): Boolean {
                    val tmp = WebView(this@BrowserActivity)
                    popups.add(tmp)
                    fun recycle() { popups.remove(tmp); ui.post { runCatching { tmp.destroy() } } }   // 不在自身回调栈内销毁
                    tmp.webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean {
                            if (r.url.scheme in listOf("http", "https")) web.loadUrl(r.url.toString())
                            recycle()
                            return true
                        }
                    }
                    // 不导航即收尾的弹窗(window.open('')+document.write / postMessage SSO 以 window.close() 结束):
                    // shouldOverrideUrlLoading 永不触发 → 靠 onCloseWindow 即时回收, 否则 tmp 持 Activity context 泄漏视图树 + 永留 devtools target
                    tmp.webChromeClient = object : android.webkit.WebChromeClient() {
                        override fun onCloseWindow(window: WebView?) { recycle() }
                    }
                    (resultMsg.obj as WebView.WebViewTransport).webView = tmp
                    resultMsg.sendToTarget()
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
        if (!dark) window.decorView.systemUiVisibility =            // 浅色栏配深色图标, 否则白底白图标不可见
            window.decorView.systemUiVisibility or android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR

        val prefs = getSharedPreferences("ga_browser", MODE_PRIVATE)
        if (!prefs.getBoolean("notice_shown", false)) {   // 强制性一次性披露: cookie 供自动化复用(Monitor 审查要求)
            prefs.edit().putBoolean("notice_shown", true).apply()
            AlertDialog.Builder(this).setTitle("登录态共享说明 / Session sharing")
                .setMessage("在此登录的网站会话(cookie)保存在 GAgent 内, 供 GA 自动化任务复用。GA 不读取你输入的密码, 只复用登录后的会话。\n\nSites you sign into here are stored in GAgent and reused by GA automation. GA never reads your password, only the signed-in session.")
                .setPositiveButton("知道了 / OK", null).show()
        }
        val u = intent.getStringExtra("url") ?: ""
        if (u.isNotBlank()) go(u) else addr.post {   // post: onCreate 时窗口未获焦, 直接 showSoftInput 常被 IME 丢弃
            addr.requestFocus()
            (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(addr, InputMethodManager.SHOW_IMPLICIT)
        }
    }

    private fun go(input: String) {
        val t = input.trim()
        if (t.isEmpty()) return
        val url = when {
            t.startsWith("http://") || t.startsWith("https://") -> t
            ' ' !in t && '.' in t -> "https://$t"
            else -> "https://www.bing.com/search?q=" + android.net.Uri.encode(t)
        }
        addr.clearFocus(); web.requestFocus()
        web.loadUrl(url)
    }

    override fun onBackPressed() { if (web.canGoBack()) web.goBack() else super.onBackPressed() }

    override fun onResume() { super.onResume(); secureForeground = true }   // 登录浏览器在前台=截图会被 FLAG_SECURE 涂黑, 供 shot() 显式报错

    override fun onPause() {
        super.onPause()
        secureForeground = false
        ui.removeCallbacks(flushCookies); CookieManager.getInstance().flush()   // 立即落盘: 用户随时可能切回对话让 GA 复用
    }

    companion object {
        // 本登录浏览器(FLAG_SECURE)是否在前台: 供 BusA11yService.shot 把"黑屏截图"换成可解释报错(不变量: secure⟺不可截图)。
        @Volatile var secureForeground = false
    }

    override fun onDestroy() {
        ui.removeCallbacks(flushCookies)
        popups.toList().forEach { runCatching { (it.parent as? ViewGroup)?.removeView(it); it.destroy() } }   // 未收尾的弹窗 WebView 随 Activity 一并销毁
        popups.clear()
        runCatching { (web.parent as? ViewGroup)?.removeView(web); web.destroy() }   // destroy 前先脱离视图树(WebView 文档要求)
        super.onDestroy()
    }
}
