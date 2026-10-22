package com.ljq.ga

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        GaNet.initNetworkMonitoring(this)
        Bus.start(this)
        Analytics.init(this)
        Diag.init(this)   // 全局崩溃捕获 + 错误本地落盘（尽早安装，进程内任何未捕获异常都记 crash-*.log）
    }
}
