package com.ljq.ga

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

/**
 * 通知监听服务: 读取系统通知、支持回复与取消操作。
 * 由 MainActivity 桥接方法调用，提供给 Python/WebUI。
 * 规则触发已迁移: 匹配/去重/冷却在 NativeNotifTrigger, 命中经 WorkManager → Python call_once。
 */
class NotifService : NotificationListenerService() {
    companion object {
        var instance: NotifService? = null
        
        // 缓存当前活跃通知 (key -> StatusBarNotification)
        private val cache = ConcurrentHashMap<String, StatusBarNotification>()
    }

    override fun onListenerConnected() {
        instance = this
        // Initial active notifications are a baseline, never retroactive tasks.
        refreshCache()
        NativeNotifTrigger.onListenerConnected(applicationContext, snapshotActiveNotifications())
    }

    override fun onListenerDisconnected() {
        if (instance == this) { instance = null; cache.clear() }   // Guard against a late old-service disconnect.
        super.onListenerDisconnected()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        cache[sbn.key] = sbn
        NativeNotifTrigger.onNotificationPosted(applicationContext, sbn)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        sbn ?: return
        cache.remove(sbn.key)
        NativeNotifTrigger.onNotificationRemoved(applicationContext, sbn)
    }

    /** Snapshot is used by start/reconnect baseline code, never as task input. */
    internal fun snapshotActiveNotifications(): List<StatusBarNotification> {
        return try {
            activeNotifications?.toList() ?: cache.values.toList()
        } catch (e: Exception) {
            Log.w("GA", "NotifService.snapshotActiveNotifications failed: ${e.message}")
            cache.values.toList()
        }
    }

    private fun refreshCache() {
        cache.clear()
        try {
            activeNotifications?.forEach { sbn ->
                cache[sbn.key] = sbn
            }
        } catch (e: Exception) {
            // 权限未授予时 activeNotifications 可能抛异常
            Log.w("GA", "NotifService.refreshCache failed: ${e.message}")
        }
    }

    /**
     * 获取当前所有通知列表，返回 JSON 数组字符串
     * 格式: [{"key":"...", "pkg":"...", "title":"...", "text":"...", "time":1234567890, "canReply":true}, ...]
     */
    fun getNotifications(): String {
        val arr = JSONArray()
        try {
            // 确保使用最新数据
            val current = activeNotifications ?: emptyArray()
            current.forEach { sbn ->
                cache[sbn.key] = sbn  // 同步到缓存
            }
            
            current.forEach { sbn ->
                val n = sbn.notification ?: return@forEach
                val extras = n.extras ?: return@forEach
                
                val obj = JSONObject()
                obj.put("key", sbn.key)
                obj.put("pkg", sbn.packageName)
                obj.put("title", extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: "")
                obj.put("text", extras.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: "")
                obj.put("time", sbn.postTime)
                
                // 检测是否可回复 (Android 7.0+)
                val canReply = if (android.os.Build.VERSION.SDK_INT >= 24) {
                    n.actions?.any { action ->
                        action.remoteInputs?.isNotEmpty() == true
                    } == true
                } else false
                obj.put("canReply", canReply)
                
                arr.put(obj)
            }
        } catch (e: Exception) {
            // 返回空数组而非抛异常
            Log.w("GA", "NotifService.getNotifications failed: ${e.message}")
        }
        return arr.toString()
    }

    /**
     * 回复通知 (仅对支持 RemoteInput 的通知有效)
     * @param key 通知的唯一标识 (StatusBarNotification.key)
     * @param text 回复内容
     * @return "ok" 或 "err:..."
     */
    fun replyNotification(key: String, text: String): String {
        if (android.os.Build.VERSION.SDK_INT < 24) return "err:api_level_too_low"
        
        return try {
            val sbn = cache[key] ?: return "err:notification_not_found"
            val n = sbn.notification ?: return "err:no_notification_object"
            
            // 找到第一个支持 RemoteInput 的 Action
            val action = n.actions?.firstOrNull { it.remoteInputs?.isNotEmpty() == true }
                ?: return "err:no_reply_action"
            
            val remoteInput = action.remoteInputs?.firstOrNull()
                ?: return "err:no_remote_input"
            
            // 构造回复 Intent
            val intent = android.content.Intent()
            val bundle = android.os.Bundle()
            bundle.putCharSequence(remoteInput.resultKey, text)
            android.app.RemoteInput.addResultsToIntent(arrayOf(remoteInput), intent, bundle)
            
            // 发送回复
            action.actionIntent.send(applicationContext, 0, intent)
            "ok"
        } catch (e: Exception) {
            "err:${e.message ?: e.javaClass.simpleName}"
        }
    }

    /**
     * 取消/清除通知
     * @param key 通知的唯一标识
     * @return "ok" 或 "err:..."
     */
    fun dismissNotification(key: String): String {
        return try {
            cancelNotification(key)
            cache.remove(key)
            "ok"
        } catch (e: Exception) {
            "err:${e.message ?: e.javaClass.simpleName}"
        }
    }

    /**
     * 清除指定应用的所有通知
     * @param pkg 应用包名
     * @return 清除数量
     */
    fun dismissByPackage(pkg: String): Int {
        var count = 0
        try {
            cache.values.filter { it.packageName == pkg }.forEach { sbn ->
                cancelNotification(sbn.key)
                cache.remove(sbn.key)
                count++
            }
        } catch (e: Exception) {
            // 部分清除成功也返回计数
            Log.w("GA", "NotifService.dismissByPackage failed: ${e.message}")
        }
        return count
    }
}
