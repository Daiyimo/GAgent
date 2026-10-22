package com.ljq.ga

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import java.io.File

// 无桥 HTML 预览容器(v2.19 预览框架): 生成的 html 产物(PPT/slides/网页)可能含不可信脚本。
// 主 WebView 的 addJavascriptInterface 对【所有 frame】生效, iframe sandbox 挡得住父 DOM 挡不住原生桥
// → 必须换进程隔离面: 独立 Activity + 裸 WebView, 零 JS 接口, 桥面=0(Monitor CONFIRMED must-fix)。
// 守卫: 只加载 filesDir/ga/temp 沙盒内文件(与 MainActivity.gaTempFile 同构); 外链一律交系统浏览器。
class HtmlPreviewActivity : Activity() {
    private var web: WebView? = null
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        title = intent.getStringExtra("name") ?: ""
        val path = intent.getStringExtra("path") ?: return finish()
        val root = File(File(filesDir, "ga"), "temp").canonicalFile
        val f = File(path).canonicalFile
        if (!f.path.startsWith(root.path + File.separator) || !f.isFile) return finish()
        val wv = WebView(this)
        wv.settings.javaScriptEnabled = true          // 脚本可跑(图表/动画), 但无任何桥可调
        wv.settings.allowFileAccess = true            // 同目录图片/CSS 相对引用; fromFileURLs 默认 false, JS 读不了别的 file://
        wv.settings.domStorageEnabled = false
        wv.webViewClient = object : WebViewClient() { // 导航锁 file://: 点外链交系统浏览器, 预览页不变浏览器
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean {
                if (r.url.scheme == "file") return false
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, r.url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                return true
            }
        }
        web = wv; setContentView(wv)
        wv.loadUrl("file://" + f.path)
    }
    override fun onDestroy() { web?.destroy(); web = null; super.onDestroy() }
}
