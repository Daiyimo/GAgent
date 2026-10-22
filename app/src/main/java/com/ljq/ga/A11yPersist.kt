package com.ljq.ga

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Settings

/**
 * 无障碍持久化: MIUI/Flyme 等 OEM 在 force-stop/系统杀进程时会把本 app 的无障碍服务从
 * ENABLED_ACCESSIBILITY_SERVICES 摘除, 重开要走系统开关 + ~10s 强制倒计时; 进程保活救不了
 * (OEM 策略挂在 disable 事件上)。唯一稳妥修复 = 持有 WRITE_SECURE_SETTINGS(开发级权限,
 * `adb shell pm grant` 一次, 卸载前永久有效), app 启动时把服务静默写回系统列表。
 * 单一真相源: 用户开关 = SP("ga").a11y_persist; 生效态 = 系统 secure setting 本身(不镜像不缓存)。
 */
object A11yPersist {
    private const val SP_KEY = "a11y_persist"

    /** 设备侧 shell 命令(P0 电脑 adb / P1 自连均执行它); 完整命令行由前端拼 "adb shell " 前缀展示。 */
    fun grantCmd(ctx: Context) = "pm grant ${ctx.packageName} android.permission.WRITE_SECURE_SETTINGS"

    fun hasWriteSecure(ctx: Context): Boolean =
        ctx.checkSelfPermission(android.Manifest.permission.WRITE_SECURE_SETTINGS) ==
            PackageManager.PERMISSION_GRANTED

    fun persistEnabled(ctx: Context): Boolean =
        ctx.getSharedPreferences("ga", Context.MODE_PRIVATE).getBoolean(SP_KEY, false)

    fun setPersistEnabled(ctx: Context, on: Boolean) =
        ctx.getSharedPreferences("ga", Context.MODE_PRIVATE).edit().putBoolean(SP_KEY, on).apply()

    /**
     * 把本包的无障碍服务写回「已启用服务」列表(幂等): 只追加本包组件、保留其他 app 的服务, 绝不整表覆盖;
     * 已在表且总开关已开 → 零写入。返回写后是否在表。无权限/写失败 → false(best-effort, 失败半径=维持现状)。
     */
    fun reEnable(ctx: Context): Boolean {
        if (!hasWriteSecure(ctx)) return false
        return runCatching {
            val cr = ctx.contentResolver
            val list = (Settings.Secure.getString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "")
                .split(':').filter { it.isNotBlank() }
            if (list.none { it.substringBefore('/').equals(ctx.packageName, true) }) {   // 与 MainActivity.isA11yOn 同谓词(按包匹配, 兼容全称/缩写两种组件写法)
                val comp = ComponentName(ctx, BusA11yService::class.java).flattenToString()
                Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
                    (list + comp).joinToString(":"))
            }
            if (Settings.Secure.getInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 0) != 1)
                Settings.Secure.putInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
            true
        }.getOrDefault(false)
    }
}
