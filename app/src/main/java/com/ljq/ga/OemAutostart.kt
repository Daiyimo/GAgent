package com.ljq.ga

import android.content.ComponentName
import android.content.Intent
import java.util.Locale

object OemAutostart {
    // 厂商「自启动管理」页(无障碍持久化 P2 引导, 尽力而为): 安全中心组件名随 OEM 版本漂移,
    // 调用方 resolveActivity+runCatching 逐个尝试, 失败自然落到通用应用详情页, 失败半径为零。
    fun oemAutostartIntents(): List<Intent> {
        val m = android.os.Build.MANUFACTURER.lowercase(Locale.ROOT)
        val comp = when {
            "xiaomi" in m || "redmi" in m -> "com.miui.securitycenter" to "com.miui.permcenter.autostart.AutoStartManagementActivity"
            "meizu" in m -> "com.meizu.safe" to "com.meizu.safe.permission.SmartBGActivity"
            "huawei" in m || "honor" in m -> "com.huawei.systemmanager" to "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"
            "oppo" in m || "realme" in m -> "com.coloros.safecenter" to "com.coloros.safecenter.permission.startup.StartupAppListActivity"
            "vivo" in m -> "com.vivo.permissionmanager" to "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"
            else -> return emptyList()
        }
        return listOf(Intent().setComponent(ComponentName(comp.first, comp.second)))
    }
}
