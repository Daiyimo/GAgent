package com.ljq.ga

import com.chaquo.python.Python

object Py {
    @Volatile var ready = false
    @Synchronized fun boot(gaDir: String, packageName: String): String =
        Python.getInstance().getModule("bootstrap").callAttr("init", gaDir, packageName).toString().also { ready = true }
    fun call(fn: String, vararg a: Any?): String =
        Python.getInstance().getModule("bootstrap").callAttr("call", fn, *a).toString()
}
