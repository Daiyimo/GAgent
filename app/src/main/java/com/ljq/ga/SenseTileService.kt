package com.ljq.ga

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import androidx.annotation.RequiresApi

/**
 * 快捷设置磁贴 = mic 采集在现代安卓上「无感开启」的合规天花板。
 *
 * A34+ 铁律: microphone 型 FGS 只能在 app 持有可见 Activity 时创建, 任何后台启动豁免
 * (FCM/exact-alarm/geofence/CDM)都启不动 mic 类型。故最短的合规链是:
 *   用户下拉状态栏点磁贴 → startActivityAndCollapse(透明 Activity) → 该 Activity 起 mic FGS → 立即 finish。
 * 体感 ~1.5s, 全程用户交互驱动, 不依赖任何保活。比「常驻 FGS + 通知按钮」少一个必须活着的前提。
 *
 * 磁贴只负责「把 GA 拉到前台并带上开录意图」, 真正的会话开启在 SenseQuickActivity ——
 * TileService 自身是后台上下文, 在这里直接起 mic FGS 同样会被 A34 拒绝。
 */
class SenseTileService : TileService() {

    override fun onStartListening() {
        qsTile?.let {
            it.state = if (SenseService.live != null) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
            it.label = if (SenseService.live != null) "GA 记录中" else "GA 记一下"
            it.updateTile()
        }
    }

    override fun onClick() {
        val running = SenseService.live != null
        val i = Intent(this, SenseQuickActivity::class.java)
            .setAction(if (running) SenseQuickActivity.ACTION_STOP else SenseQuickActivity.ACTION_START)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        if (Build.VERSION.SDK_INT >= 34) startWithPendingIntent(i) else startActivityAndCollapseLegacy(i)
    }

    @RequiresApi(34)
    private fun startWithPendingIntent(i: Intent) {
        // A34 起 startActivityAndCollapse(Intent) 抛 UnsupportedOperationException, 必须传 PendingIntent
        val pi = PendingIntent.getActivity(
            this, 0, i,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        startActivityAndCollapse(pi)
    }

    @Suppress("DEPRECATION")
    private fun startActivityAndCollapseLegacy(i: Intent) {
        startActivityAndCollapse(i)
    }
}
