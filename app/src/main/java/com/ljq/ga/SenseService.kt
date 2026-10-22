package com.ljq.ga

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioRecordingConfiguration
import android.media.MediaRecorder
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.provider.CalendarContract
import androidx.core.content.PermissionChecker
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.sqrt

/**
 * L0 真实世界原子(Bus 的 /sense/ 路由族)。只负责「从系统拿到信号」, 不含任何语义。
 * (注: 这里不能写「/sense/」加星号 —— Kotlin 的块注释是**可嵌套**的, 那两个字符会开一个永不闭合的内层注释,
 *  整份文件随之被吃掉, 报错却只显示成文件末尾的 Unclosed comment。)
 *
 * 全层唯一不变量: 上层只看到 **统一形状 + granted/caps/degraded_to**。Android 版本差异、GMS 有无、
 * 厂商 ROM 差异全部吸收在本文件内 —— 这是 SOP 能适配尽可能多安卓系统的唯一实现方式。
 * 因此这里 **绝不抛异常、绝不崩**: 拿不到就如实标 granted:false / degraded_to, 而不是把异常甩给 L1。
 *
 * 隐私红线写进代码而非文档: 默认全关(会话必须由用户显式动作 start); 只读当前连接的 WiFi 不做全量扫描;
 * MAC/邮箱一律加盐 hash 后才落盘; 显式不申请 ACCESS_BACKGROUND_LOCATION。
 * 数据落 GA_DIR/temp/.sense/ —— '.' 前缀是仓库内部命名空间, 且在 gacore 树外(免 Evolution.pruneRemoved 误删)。
 */
object Sense {
    const val RATE = 16000
    private val SID_RE = Regex("^ses_[0-9a-z]{1,16}_[0-9]{3}$")   // sid 来自外部入参, 必须先验形再拼路径(防目录穿越)

    fun root(ctx: Context): File = File(ctx.filesDir, "ga/temp/.sense").apply { mkdirs() }
    fun dir(ctx: Context, sid: String): File = File(root(ctx), sid).apply { mkdirs() }
    private fun ptr(ctx: Context) = File(root(ctx), "current")

    /**
     * 用 PermissionChecker 而非 Context.checkSelfPermission: 前者连 appop 一起校验 —— 国产 ROM 的隐私管家
     * 常见做法是「权限还挂着但 appop 已撤」, 只看 checkSelfPermission 会误判为已授权, 然后拿到一片空数据。
     * 出异常一律当未授权: 出错时永远退向"采得更少"。(系统定位总开关是另一回事, 由 getProviders(true) 为空来体现)
     */
    fun granted(ctx: Context, p: String): Boolean =
        runCatching { PermissionChecker.checkSelfPermission(ctx, p) == PermissionChecker.PERMISSION_GRANTED }
            .getOrDefault(false)

    private fun locGranted(ctx: Context) =
        granted(ctx, Manifest.permission.ACCESS_FINE_LOCATION) || granted(ctx, Manifest.permission.ACCESS_COARSE_LOCATION)

    /** A12+ 蓝牙扫描走 BLUETOOTH_SCAN(neverForLocation, 免定位权限); A11- 只能靠 FINE_LOCATION */
    private fun scanPerm() =
        if (Build.VERSION.SDK_INT >= 31) Manifest.permission.BLUETOOTH_SCAN else Manifest.permission.ACCESS_FINE_LOCATION

    /** 每安装一枚随机盐: 无盐的 sha256(MAC) 因 OUI 公开只剩 2^24 空间可秒破, 有盐才谈得上「绝不存原始 MAC」 */
    private fun salt(ctx: Context): String {
        val sp = ctx.getSharedPreferences("ga", Context.MODE_PRIVATE)
        sp.getString("sense_salt", null)?.let { if (it.isNotEmpty()) return it }
        val s = ByteArray(16).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        sp.edit().putString("sense_salt", s).apply()
        return s
    }

    fun h(ctx: Context, v: String): String =
        MessageDigest.getInstance("SHA-256").digest((salt(ctx) + v).toByteArray())
            .take(8).joinToString("") { "%02x".format(it) }

    private fun ok() = JSONObject().put("ok", 1).put("degraded_to", "")
    private fun bad(code: String, extra: String = "") =
        JSONObject().put("ok", 0).put("error", code).put("detail", extra).put("degraded_to", "error")

    // ───────────────────────── 位置 ─────────────────────────

    /**
     * mode: stay=只吃缓存点(静止时零射频, 省电门控的落点) / move|once=拉一次新点, 超时回落缓存。
     * fix:null 仍然 ok:1 —— 「没拿到位置」是已知状态不是错误, 上层据 degraded_to 换别的证据。
     */
    fun loc(ctx: Context, mode: String, timeoutMs: Long): JSONObject {
        val fine = granted(ctx, Manifest.permission.ACCESS_FINE_LOCATION)
        val out = ok().put("granted", locGranted(ctx)).put("provider", "none").put("fix", JSONObject.NULL)
        if (!locGranted(ctx)) return out.put("degraded_to", "near_fingerprint")
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return out.put("degraded_to", "near_fingerprint")
        // A12+ LocationManager 自带 "fused"(免 GMS, 华为等无 GMS 机型同样可用); 没有则 network→gps→passive 逐个探。
        // 本仓不引 play-services-location, 故 provider 只有 fused(平台自带)/manager 两种真值, 不谎报。
        val avail = runCatching { lm.getProviders(true) }.getOrDefault(emptyList())
        val order = listOfNotNull(
            if (Build.VERSION.SDK_INT >= 31) LocationManager.FUSED_PROVIDER else null,
            LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER, LocationManager.PASSIVE_PROVIDER,
        ).filter { avail.contains(it) }
        if (order.isEmpty()) return out.put("degraded_to", "near_fingerprint")
        out.put("provider", if (order[0] == "fused") "fused" else "manager")
        val last = order.asSequence()
            .mapNotNull { p -> runCatching { lm.getLastKnownLocation(p) }.getOrNull() }.maxByOrNull { it.time }
        val fx = (if (mode == "stay") null else fresh(lm, order[0], timeoutMs)) ?: last
            ?: return out.put("degraded_to", "near_fingerprint")
        return out.put("fix", JSONObject()
            .put("lat", fx.latitude).put("lon", fx.longitude)
            .put("acc_m", if (fx.hasAccuracy()) fx.accuracy.toDouble() else -1.0)
            .put("ts", fx.time)
            .put("stale_ms", System.currentTimeMillis() - fx.time))   // getLastKnownLocation 可能是几小时前的老点, 新鲜度交上层判
            .put("degraded_to", if (fine) "" else "coarse_only")
    }

    /** 一次性新点: requestLocationUpdates + 显式 Looper(全 API 可用, 避开 API30 才有的 getCurrentLocation) */
    private fun fresh(lm: LocationManager, p: String, timeoutMs: Long): Location? {
        val latch = CountDownLatch(1)
        val box = arrayOfNulls<Location>(1)
        // 另三个方法在 API<30 仍是抽象的: 只写 onLocationChanged 会在旧机上抛 AbstractMethodError
        @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
        val li = object : LocationListener {
            override fun onLocationChanged(location: Location) { box[0] = location; latch.countDown() }
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) { latch.countDown() }
        }
        return try {
            lm.requestLocationUpdates(p, 0L, 0f, li, Looper.getMainLooper())
            latch.await(timeoutMs.coerceIn(500L, 30_000L), TimeUnit.MILLISECONDS)
            box[0]
        } catch (e: Throwable) { null } finally { runCatching { lm.removeUpdates(li) } }
    }

    // ───────────────────────── 邻近/同场 ─────────────────────────

    /**
     * BLE 短扫 + 当前连接的 WiFi BSSID, 全部加盐 hash。**不做 getScanResults 全量 WiFi 扫描**:
     * 采集面大一个数量级、节流严重、耗电高, 而作为同场锚点的信息量几乎相同。
     * A12+ MAC 随机化 ⇒ ble 的 hash 只在单次会话内可比对, 跨天匹配无效(语义写在 ROUTE_DOCS 里)。
     */
    fun near(ctx: Context, ms: Long): JSONObject {
        val bleOk = granted(ctx, scanPerm())
        val caps = JSONObject().put("ble", if (bleOk) "ok" else "denied").put("wifi", "ok")
        val out = ok().put("granted", bleOk).put("caps", caps)
            .put("wifi", JSONObject.NULL).put("ble", JSONArray())
            // paired 恒为空数组: 读已配对设备名要 BLUETOOTH_CONNECT(又一个用户弹框), 而它只是个可选的跨天稳定锚点 —— 按"采得更少"取舍。
            //  连带后果: ble 条目没有 stable:true 的来源(A12+ MAC 随机化), 上层据此只能做单次会话内比对, 这正是要的语义。
            .put("paired", JSONArray())
        if (!granted(ctx, Manifest.permission.ACCESS_FINE_LOCATION)) caps.put("wifi", "needs_fine_loc")
        else runCatching {
            val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            @Suppress("DEPRECATION") val b = wm?.connectionInfo?.bssid
            // 02:00:.. 是系统在缺权限/缺定位服务时给的匿名占位, 当成"没拿到"而不是当成一个地点指纹
            if (b != null && b != "02:00:00:00:00:00" && b != "00:00:00:00:00:00")
                out.put("wifi", JSONObject().put("bssid_hash", h(ctx, b)))
        }
        val ad = runCatching { (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter }.getOrNull()
        val scanner = if (ad == null || !bleOk) null else runCatching { if (ad.isEnabled) ad.bluetoothLeScanner else null }.getOrNull()
        if (scanner == null) {
            caps.put("ble", if (ad == null) "unsupported" else if (!bleOk) "denied" else "off")
            return out.put("degraded_to", "no_ble")
        }
        val seen = LinkedHashMap<String, Int>()
        val fail = AtomicInteger(-1)
        val cb = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                // 整段进 runCatching: 回调跑在蓝牙线程, 这里漏一个异常没人接得住, 直接崩宿主 app
                val k = runCatching { result.device?.address?.let { h(ctx, it) } }.getOrNull() ?: return
                synchronized(seen) {   // 回调在蓝牙线程写、本函数在桥线程读 ⇒ 裸 HashMap 会并发损坏
                    val prev = seen[k]
                    if (prev == null || result.rssi > prev) seen[k] = result.rssi   // 同一设备留最强 rssi(最近的一次)
                }
            }
            // 不覆写就是彻底静默: 扫描起不来时 ble 照样是空数组、caps 照样报 ok, 「附近没人」与「根本没扫」就没法分。
            //  只记码不碰 caps: JSONObject 非线程安全, 跨线程改由下面桥线程统一落。
            override fun onScanFailed(errorCode: Int) { fail.set(errorCode) }
        }
        runCatching {
            scanner.startScan(null, ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), cb)
            Thread.sleep(ms.coerceIn(500L, 10_000L))
        }.onFailure { caps.put("ble", "denied"); out.put("degraded_to", "no_ble") }
        runCatching { scanner.stopScan(cb) }
        val arr = JSONArray()
        synchronized(seen) { seen.forEach { (k, v) -> arr.put(JSONObject().put("hash", k).put("rssi", v)) } }
        val err = fail.get()
        // A8.1+ 熄屏时无过滤扫描的结果被系统直接丢弃, 且不回调 onScanFailed —— 而熄屏正是采集期的常态,
        //  空结果不标出来就等于断言"附近没人"。读不到屏幕状态时按 interactive 处理: 宁可不解释, 也不编一个理由。
        if (err >= 0) { caps.put("ble", "scan_failed_$err"); out.put("degraded_to", "ble_scan_failed") }
        else if (arr.length() == 0 && !interactive(ctx)) { caps.put("ble", "screen_off"); out.put("degraded_to", "ble_screen_off") }
        return out.put("ble", arr)
    }

    private fun interactive(ctx: Context) =
        runCatching { (ctx.getSystemService(Context.POWER_SERVICE) as PowerManager).isInteractive }.getOrDefault(true)

    // ───────────────────────── 日历 ─────────────────────────

    /** 只按区间查 Instances(不做全量同步), 一条事件直接给出「时段+地点+参与者」且零推断 —— 最便宜的时空 ground truth */
    fun cal(ctx: Context, from: Long, to: Long, limit: Int): JSONObject {
        val g = granted(ctx, Manifest.permission.READ_CALENDAR)
        val arr = JSONArray()
        val out = ok().put("granted", g).put("events", arr)
        if (!g) return out.put("degraded_to", "no_calendar")
        if (to <= from) return out.put("degraded_to", "bad_range")
        runCatching {
            val b = CalendarContract.Instances.CONTENT_URI.buildUpon()
            ContentUris.appendId(b, from); ContentUris.appendId(b, to)
            val proj = arrayOf(
                CalendarContract.Instances.EVENT_ID, CalendarContract.Instances.TITLE,
                CalendarContract.Instances.BEGIN, CalendarContract.Instances.END,
                CalendarContract.Instances.EVENT_LOCATION, CalendarContract.Instances.ALL_DAY,
                CalendarContract.Instances.CALENDAR_DISPLAY_NAME,
            )
            ctx.contentResolver.query(b.build(), proj, null, null, CalendarContract.Instances.BEGIN + " ASC")?.use { c ->
                while (c.moveToNext() && arr.length() < limit.coerceIn(1, 200)) {
                    val id = c.getLong(0)
                    arr.put(JSONObject()
                        .put("id", id.toString())
                        .put("title", c.getString(1) ?: "")
                        .put("start", c.getLong(2)).put("end", c.getLong(3))
                        .put("location", c.getString(4) ?: "")
                        .put("allday", c.getInt(5) == 1)
                        .put("cal", c.getString(6) ?: "")
                        .put("attendees", attendees(ctx, id)))
                }
            }
        }.onFailure { return out.put("degraded_to", "query_failed") }
        return out
    }

    /** 参与者邮箱只留 hash: 同一人可跨事件归并, 原文不落盘。纯本地日历账户这张表常为空, 空即空, 不编 */
    private fun attendees(ctx: Context, eventId: Long): JSONArray {
        val arr = JSONArray()
        runCatching {
            ctx.contentResolver.query(CalendarContract.Attendees.CONTENT_URI,
                arrayOf(CalendarContract.Attendees.ATTENDEE_NAME, CalendarContract.Attendees.ATTENDEE_EMAIL),
                CalendarContract.Attendees.EVENT_ID + "=?", arrayOf(eventId.toString()), null)?.use { c ->
                while (c.moveToNext() && arr.length() < 20) {
                    val mail = c.getString(1) ?: ""
                    arr.put(JSONObject().put("name", c.getString(0) ?: "")
                        .put("email_h", if (mail.isEmpty()) "" else h(ctx, mail)))
                }
            }
        }
        return arr
    }

    // ───────────────────────── 运动 ─────────────────────────

    /**
     * 两级: 有 ACTIVITY_RECOGNITION 则加一路步检测器(区分 walking/vehicle), 否则只用加速度方差(**零权限, 最终兜底一定可用**)。
     * 用途二是位置的省电门控: still 就别开定位, 只留一条停留点(定时 GPS 是错解)。
     */
    fun motion(ctx: Context): JSONObject {
        val g = Build.VERSION.SDK_INT < 29 || granted(ctx, Manifest.permission.ACTIVITY_RECOGNITION)
        val out = ok().put("granted", g).put("state", "unknown").put("confidence", 0)
        val sm = ctx.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
        val acc = sm?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) ?: return out.put("degraded_to", "no_sensor")
        val step = if (g) sm.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR) else null
        val mags = ArrayList<Double>(96)
        val steps = AtomicInteger(0)
        val li = object : SensorEventListener {   // 回调在传感器线程, 与读取线程跨线程 ⇒ 必须同步/原子
            override fun onSensorChanged(event: SensorEvent) {
                if (event.sensor?.type == Sensor.TYPE_STEP_DETECTOR) { steps.incrementAndGet(); return }
                val v = event.values ?: return
                if (v.size >= 3) synchronized(mags) {
                    mags.add(sqrt((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).toDouble()))
                }
            }
            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
        }
        runCatching {
            sm.registerListener(li, acc, SensorManager.SENSOR_DELAY_GAME)
            if (step != null) sm.registerListener(li, step, SensorManager.SENSOR_DELAY_FASTEST)
            Thread.sleep(1200)   // 一个够算方差与迈步、又不至于让桥线程久等的窗口
        }
        runCatching { sm.unregisterListener(li) }
        val snap = synchronized(mags) { mags.toList() }
        if (snap.size < 8) return out.put("degraded_to", "no_sample")
        val mean = snap.average()
        val sd = sqrt(snap.sumOf { (it - mean) * (it - mean) } / snap.size)
        val (state, conf) = classify(sd, steps.get(), step != null)
        return out.put("state", state).put("confidence", conf)
            .put("src", if (step != null) "step_counter" else "accel_heuristic")
            .put("degraded_to", if (step != null) "" else "accel_heuristic")
    }

    /** 纯函数(可单测): sd=加速度模的标准差 m/s², steps=窗口内迈步数, trusted=步检测器可用。宁可 unknown 也不编 vehicle */
    fun classify(sd: Double, steps: Int, trusted: Boolean): Pair<String, Int> = when {
        sd < 0.25 -> "still" to 92                 // 静置/静坐: 方差近 0, 这一档最可信
        steps > 0 -> "walking" to 88               // 迈步是唯一强证据
        !trusted -> if (sd >= 1.5) "walking" to 55 else "unknown" to 30   // 无步检测器时大振动只能猜, 不敢报 vehicle
        sd < 1.5 -> "vehicle" to 45                // 有步检测器却零迈步 + 持续小振动 = 车厢典型形态(单窗口证据本就弱)
        else -> "unknown" to 25                    // 大振动却零迈步: 多半是手在晃
    }

    // ───────────────────────── 授权 ─────────────────────────

    private val PERM_KINDS = listOf("mic", "loc", "loc_fine", "near", "cal", "motion")

    /** kind → 这项能力真正需要的运行时权限(按 API level 收敛); 空表 = 本机压根不需要授权(如 A9- 的 motion) */
    private fun permsOf(kind: String): List<String> = when (kind) {
        "mic" -> listOf(Manifest.permission.RECORD_AUDIO)
        // COARSE 是默认档(manifest 同注); 要精确点才用 loc_fine —— A12+ 必须 FINE+COARSE 同一次请求, 只写 FINE 在部分机型静默不弹框
        "loc" -> listOf(Manifest.permission.ACCESS_COARSE_LOCATION)
        "loc_fine" -> listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        // A12+ 走 BLUETOOTH_SCAN(neverForLocation, 免定位); A11- 的 BLE 扫描是平台要 FINE, 不是我们多要
        "near" -> if (Build.VERSION.SDK_INT >= 31) listOf(Manifest.permission.BLUETOOTH_SCAN)
                  else listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        "cal" -> listOf(Manifest.permission.READ_CALENDAR)
        "motion" -> if (Build.VERSION.SDK_INT >= 29) listOf(Manifest.permission.ACTIVITY_RECOGNITION) else emptyList()
        else -> emptyList()
    }

    private fun askedKey(p: String) = "sense_perm_" + p.substringAfterLast('.')

    /** 用户答完一次就记一笔"问过了"(由 onRequestPermissionsResult 调用): 理由见 perm() 对 rationale 的说明 */
    fun markAsked(ctx: Context, ps: Array<out String>) {
        runCatching {
            val e = ctx.getSharedPreferences("ga", Context.MODE_PRIVATE).edit()
            for (p in ps) e.putBoolean(askedKey(p), true)
            e.apply()
        }
    }

    private fun asked(ctx: Context, p: String) = runCatching {
        ctx.getSharedPreferences("ga", Context.MODE_PRIVATE).getBoolean(askedKey(p), false)
    }.getOrDefault(false)

    /** 系统还会不会为这条权限弹框。读不到就按"还能弹"处理: 宁可多弹一次, 也不把用户误导成"只剩系统设置一条路" */
    private fun promptable(ui: MainActivity?, p: String): Boolean {
        val a = ui ?: return true
        return runCatching { a.shouldShowRequestPermissionRationale(p) }.getOrDefault(true)
    }

    /**
     * 按需授权。声明 ≠ 已授予: loc/near/cal 的 dangerous 权限只写在 manifest 里, 没有这条路径就装完包恒 denied,
     * 而 sense 在 WebUI 里不存在, 用户在应用内根本找不到地方开。
     * 三条约束写进结构而不是靠纪律: ① 只有 action=request 才弹框, 而它只由用户显式动作触发(/sense.session start 或显式调用);
     * ② 系统已不再弹框(用户选了"不再询问")时如实回 needs_settings, 绝不假装申请过; ③ 没有前台 Activity 就不申请(平台要求), 回 no_activity。
     */
    fun perm(ctx: Context, b: JSONObject): JSONObject {
        val act = b.optString("action").ifEmpty { "status" }
        if (act != "status" && act != "request" && act != "settings") return bad("unknown_action", act)
        val kj = b.optJSONArray("kinds")
        // request 必须点名要哪几项: 缺省成"全部"会在用户只想开位置时把精确定位/日历/运动一起弹出来 —— 申请面必须等于用户这次表达的意图
        if (act == "request" && kj == null) return bad("need_kinds", PERM_KINDS.joinToString(","))
        val ks = kj?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: PERM_KINDS
        ks.firstOrNull { !PERM_KINDS.contains(it) }?.let { return bad("unknown_kind", it) }
        val ui = MainActivity.live
        val st = JSONObject()
        val need = JSONArray(); val blocked = JSONArray(); val miss = LinkedHashSet<String>()
        for (k in ks) {
            val ps = permsOf(k)
            val no = ps.filter { !granted(ctx, it) }
            // 永久拒绝 = 问过了 + 仍未授 + 系统不再给 rationale。"问过没"必须自己记: rationale 在「从没问过」时同样是 false,
            //  只看它会把首次申请误判成"只剩系统设置一条路"。
            val hard = no.isNotEmpty() && ui != null && no.all { asked(ctx, it) && !promptable(ui, it) }
            st.put(k, JSONObject().put("granted", no.isEmpty()).put("blocked", hard).put("perms", JSONArray(ps)))
            if (no.isEmpty()) continue
            (if (hard) blocked else need).put(k)
            if (!hard) miss.addAll(no)
        }
        val out = ok().put("kinds", st).put("need", need).put("blocked", blocked)
            .put("can_prompt", ui != null && MainActivity.isForeground)
            .put("degraded_to", if (blocked.length() > 0) "needs_settings" else if (need.length() > 0) "needs_permission" else "")
        if (act == "settings") return out.put("opened", ui != null && ui.openSensePermSettings())
        if (act != "request" || miss.isEmpty()) return out
        if (ui == null || !MainActivity.isForeground) return out.put("degraded_to", "no_activity")
        ui.requestSensePerms(miss.toTypedArray(), b.optLong("wait_ms", 0L).coerceIn(0L, 8000L))
        // 申请之后重读一次真值再回: wait_ms 内用户点完的话回的就是翻转后的状态, 而不是申请之前的快照
        return perm(ctx, JSONObject().put("action", "status").put("kinds", JSONArray(ks)))
            .put("requested", JSONArray(miss.toList()))
    }

    // ───────────────────────── 保活自检(A16) ─────────────────────────

    /**
     * 全天/长时采集在国产 ROM 上活不下来的根因不是代码, 是系统杀后台 —— 这条 atom 把「本机此刻会不会被杀」
     * 探测成结构化事实(而不是让 SOP 去猜机型), 并给出**按 ROM 定制**的修复深链。上层只读三个布尔:
     *   ignoring_batt = 已加电池优化白名单; bg_restricted = 被系统标「后台受限」(必然被杀); needs_setup = 建议引导。
     * 一律不抛异常: 探测失败退向「建议引导」(宁可多提示一次, 不可假装一切正常然后静默中断采集)。
     */
    fun keepalive(ctx: Context, b: JSONObject): JSONObject {
        val act = b.optString("action").ifEmpty { "status" }
        if (act != "status" && act != "settings") return bad("unknown_action", act)
        val pm = runCatching { ctx.getSystemService(Context.POWER_SERVICE) as PowerManager }.getOrNull()
        val ignoringBatt = runCatching { pm?.isIgnoringBatteryOptimizations(ctx.packageName) == true }.getOrDefault(false)
        val bgRestricted = runCatching {
            Build.VERSION.SDK_INT >= 28 &&
                (ctx.getSystemService(Context.ACTIVITY_SERVICE) as android.app.ActivityManager).isBackgroundRestricted
        }.getOrDefault(false)
        val mfr = (Build.MANUFACTURER ?: "").lowercase()
        // ROM 专属自启动/后台管理页(随 HyperOS/ColorOS 版本改名, 打不开就回落到应用详情页, 由 needs_setup 兜底)。
        val vendorHint = when {
            mfr.contains("xiaomi") || mfr.contains("redmi") -> "小米/红米: 安全中心 > 应用管理 > GA > 自启动开、省电策略「无限制」"
            mfr.contains("oppo") || mfr.contains("realme") || mfr.contains("oneplus") ->
                "OPPO/一加: 设置 > 电池 > 后台耗电管理 > GA「允许后台运行」+ 允许自启动"
            mfr.contains("vivo") || mfr.contains("iqoo") -> "vivo/iQOO: i管家 > 应用管理 > 自启动 + 后台高耗电 允许 GA"
            mfr.contains("huawei") || mfr.contains("honor") -> "华为/荣耀: 设置 > 应用 > GA > 耗电详情 > 关闭「自动管理」并手动全允许"
            mfr.contains("samsung") -> "三星: 设置 > 电池 > 后台使用限制 > 从不休眠 App 加入 GA"
            mfr.contains("meizu") -> "魅族: 手机管家 > 权限 > 后台管理 > GA 保持运行"
            else -> "系统 > 应用 > GA > 电池 > 不受限制"
        }
        // needs_setup: 已被后台受限(最危险), 或还没进电池白名单。已豁免且未受限 = 达标, 不打扰。
        val needsSetup = bgRestricted || !ignoringBatt
        val out = ok()
            .put("ignoring_batt", ignoringBatt).put("bg_restricted", bgRestricted)
            .put("needs_setup", needsSetup).put("manufacturer", Build.MANUFACTURER ?: "")
            .put("vendor_hint", vendorHint)
        if (act == "settings") {
            val ui = MainActivity.live
            out.put("opened", ui != null && ui.openKeepaliveSettings(!ignoringBatt))
        }
        return out
    }

    // ───────────────────────── 会话 ─────────────────────────

    fun session(ctx: Context, b: JSONObject): JSONObject = when (val a = b.optString("action")) {
        "start" -> start(ctx, b)
        "stop" -> stop(ctx)
        "status" -> status(ctx)
        // 未知子命令必须就地失败(与桥命名空间同一条不变量): 否则调用方会把失败当成"已开始采集"
        else -> bad("unknown_action", a)
    }

    private fun start(ctx: Context, b: JSONObject): JSONObject {
        reconcile(ctx)
        if (SenseService.live != null) return status(ctx)   // 幂等: 已在跑就回真值, 重开会丢正在写的分片
        val want = b.optJSONArray("sources")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: listOf("mic")
        // 想采的源缺哪个权限就地申请一次: 用户刚做出"开始记录"这个显式动作, 正是唯一该弹框的时刻(启动时批量弹框是红线)。
        //  不等结果 —— 授权框是用户节奏, 等在这里 L1 必超时; 本次按当前已有权限起, need_perm 如实回上层, 授完再 start 一次。
        val pm = perm(ctx, JSONObject().put("action", "request").put("kinds", JSONArray(want.filter { PERM_KINDS.contains(it) })))
        fun withPerm(o: JSONObject) = o.put("need_perm", pm.optJSONArray("need") ?: JSONArray())
            .put("perm_blocked", pm.optJSONArray("blocked") ?: JSONArray())
        val mic = want.contains("mic") && granted(ctx, Manifest.permission.RECORD_AUDIO)
        val loc = want.contains("loc") && locGranted(ctx)
        // 没有任何"需要常驻才拿得到"的源 ⇒ 不起前台服务: near/cal/motion 都是拉取式, 起服务只是白耗电 + 多一条通知
        if (!mic && !loc) return withPerm(status(ctx).put("degraded_to", "no_source"))
        val sid = "ses_" + java.lang.Long.toString(System.currentTimeMillis(), 36) + "_" + (100 + SecureRandom().nextInt(900))
        SenseService.startErr = ""
        val i = Intent(ctx, SenseService::class.java)
            .putExtra("sid", sid).putExtra("label", b.optString("label"))
            .putExtra("want", want.joinToString(","))
            .putExtra("mic", mic).putExtra("loc", loc)
            .putExtra("policy", (b.optJSONObject("policy") ?: JSONObject()).toString())
        // A14: 后台起 microphone 型 FGS 直接抛 SecurityException(不是 A13 的"能建但静音") ⇒ 如实回 unsupported, 绝不假装启动成功
        runCatching { if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i) }
            .onFailure { return withPerm(status(ctx).put("degraded_to", "bg_start_blocked").put("detail", it.toString())) }
        val t0 = System.currentTimeMillis()
        runCatching {
            while (SenseService.live == null && SenseService.startErr.isEmpty() && System.currentTimeMillis() - t0 < 3000)
                Thread.sleep(20)
        }
        val st = status(ctx)
        return withPerm(if (SenseService.startErr.isEmpty()) st
                        else st.put("degraded_to", "start_failed").put("detail", SenseService.startErr))
    }

    private fun stop(ctx: Context): JSONObject {
        val sid = SenseService.live?.sid ?: ""
        runCatching { ctx.stopService(Intent(ctx, SenseService::class.java)) }
        // 等 onDestroy 把最后一片落完再回状态, 否则调用方紧接着取 segments 会少最后一段
        val t0 = System.currentTimeMillis()
        runCatching { while (SenseService.live != null && System.currentTimeMillis() - t0 < 2000) Thread.sleep(20) }
        return status(ctx).put("sid", sid)
    }

    fun status(ctx: Context): JSONObject {
        reconcile(ctx)
        val s = SenseService.live
        val micPerm = granted(ctx, Manifest.permission.RECORD_AUDIO)
        return ok()
            .put("sid", s?.sid ?: "").put("started_at", s?.startedAt ?: 0L).put("label", s?.label ?: "")
            .put("uptime_ms", if (s == null) 0L else System.currentTimeMillis() - s.startedAt)
            .put("sources", JSONObject()
                .put("mic", src(micPerm, s?.wants("mic") == true, s != null, s?.micErr ?: "", s?.silenced == true))
                .put("loc", src(locGranted(ctx), s?.wants("loc") == true, s != null, "", false))
                .put("near", src(granted(ctx, scanPerm()), s?.wants("near") == true, s != null, "", false)))
    }

    /**
     * 单源状态(纯函数), 顺序即优先级: 权限 > 是否请求/会话在跑 > 硬失败 > 被静音 > 在跑。
     * 语义: on = 该源当前能为本会话产出数据(mic=正在写分片; loc/near=已授权且前台服务在跑, 后台取数合法, 由 L1 按 policy 拉)。
     */
    fun src(perm: Boolean, wanted: Boolean, running: Boolean, err: String, silenced: Boolean): JSONObject {
        val state = when {
            !perm -> "denied"
            !wanted || !running -> "off"
            err.isNotEmpty() -> "unsupported"
            silenced -> "silenced"
            else -> "on"
        }
        return JSONObject().put("state", state).put("reason", if (state == "unsupported") err else "")
    }

    /**
     * 会话真值收敛: 有 current 指针却没有活服务(任务管理器手停 / OEM 杀后台 / 进程重启) ⇒ 补一条 gap 并清指针。
     * 绝不让上层看到"还在录"的幻影 —— 假数据比没数据危险得多。status/start/mic 三处入口都先跑它。
     */
    fun reconcile(ctx: Context) {
        if (SenseService.live != null) return
        val p = ptr(ctx)
        val sid = runCatching { p.readText().trim() }.getOrNull() ?: return
        if (SID_RE.matches(sid)) runCatching {
            append(ctx, sid, obs(sid, "audio.gap", "", lastEnd(ctx, sid), System.currentTimeMillis(), 0L, false, "service_gone", 0L))
        }
        runCatching { p.delete() }
    }

    private fun lastEnd(ctx: Context, sid: String): Long {
        var end = 0L
        runCatching { File(dir(ctx, sid), "segs.jsonl").forEachLine { l -> runCatching { end = maxOf(end, JSONObject(l).optLong("to")) } } }
        if (end == 0L) runCatching { end = JSONObject(File(dir(ctx, sid), "meta.json").readText()).optLong("started_at") }
        return end
    }

    private fun current(ctx: Context): String {
        runCatching { ptr(ctx).readText().trim() }.getOrNull()?.let { if (it.isNotEmpty()) return it }
        // 会话已停时取最近一次: "停止后立刻取分片"是主线路径, 不该要求调用方自己记 sid
        return runCatching {
            root(ctx).listFiles()?.filter { it.isDirectory }?.maxByOrNull { it.lastModified() }?.name
        }.getOrNull() ?: ""
    }

    // ───────────────────────── 分片 ─────────────────────────

    /** 观测记录(分片与缺口同一形状): id 由 sid+起点+种类派生 ⇒ 重复读取/重复上报天然幂等, 是断点续传的地基 */
    fun obs(sid: String, kind: String, path: String, from: Long, to: Long, bytes: Long,
            valid: Boolean, reason: String, speechMs: Long): JSONObject =
        JSONObject().put("id", "obs_${sid}_${from}_${kind.substringAfter('.')}")
            .put("sid", sid).put("kind", kind).put("path", path)
            .put("from", from).put("to", to).put("bytes", bytes)
            .put("valid", valid).put("reason", reason)
            .put("codec", "pcm16").put("rate", RATE).put("speech_ms", speechMs)

    /** segs.jsonl 是耐久真值(进程被杀也在): L0 只写不推, L1 靠 /sense/mic segments 拉 —— 少一条跨层耦合就少一类静默失败 */
    fun append(ctx: Context, sid: String, o: JSONObject) {
        runCatching { File(dir(ctx, sid), "segs.jsonl").appendText(o.toString() + "\n") }
    }

    fun mic(ctx: Context, b: JSONObject): JSONObject {
        val a = b.optString("action")
        if (a != "segments") return bad("unknown_action", a)
        reconcile(ctx)
        val sid = b.optString("sid").ifEmpty { current(ctx) }
        val arr = JSONArray()
        val out = ok().put("sid", sid).put("segments", arr)
        if (!SID_RE.matches(sid)) return out.put("degraded_to", "bad_sid")
        runCatching {
            File(dir(ctx, sid), "segs.jsonl").forEachLine { l ->
                runCatching { arr.put(JSONObject(l)) }   // 单行坏了只丢这一行, 不能让整段历史读不出来
            }
        }
        return out
    }
}

/**
 * 采集会话前台服务。**独立于 FloatService**: 后者是 specialUse 型(A14 按声明类型校验, 拿不住后台麦克风),
 * 且生命周期被"悬浮窗常开"开关绑死(PermissionCoordinator 在开关关闭时无条件 stopService)。
 *
 * 产品形态是「明示的随身记录仪」: A12+ 状态栏麦克风指示 / FGS 常驻通知 / A13+ 任务管理器条目三处露出
 * 均为平台强制且不可隐藏 —— 不做任何低调化, 通知带"停止记录"动作。
 * START_NOT_STICKY: 被杀就是被杀, 不假装拉回(A14 也禁止后台重建 microphone 型 FGS), 缺口由 Sense.reconcile 补齐。
 */
class SenseService : Service() {
    companion object {
        @Volatile var live: SenseService? = null      // 唯一"确实在跑"的信号(startForeground 成功后才赋值)
        @Volatile var startErr = ""                   // 前台化失败原因: 上层据此回 unsupported 而不是假装成功
        private const val CH = "ga_sense"
        private const val NOTIF_ID = 8801
        const val ACTION_STOP = "com.ljq.ga.SENSE_STOP"
    }

    @Volatile var sid = ""
    @Volatile var micErr = ""
    @Volatile var silenced = false
    @Volatile var startedAt = 0L
    var label = ""
    private var want = ""
    private var micWanted = false
    private var locWanted = false
    private var segMs = 300_000L
    private var maxBytes = 512L * 1024 * 1024
    private var vadRms = 0
    @Volatile private var running = false
    private var thread: Thread? = null
    private var wake: PowerManager.WakeLock? = null
    private var am: AudioManager? = null
    private var recCb: AudioManager.AudioRecordingCallback? = null

    fun wants(n: String) = want.split(",").contains(n)

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null || intent.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        // 幂等闸: 并发两次 start 会同时通过 Sense.start 的 live==null 检查(startMic 要等 1.5s), 第二趟将再开一路
        //  AudioRecord、顶掉 thread/wake 引用(锁泄漏), 且被顶掉的旧线程会把分片写进新 sid。已在跑就丢弃重复请求。
        if (live != null) return START_NOT_STICKY
        sid = intent.getStringExtra("sid") ?: ""
        label = intent.getStringExtra("label") ?: ""
        want = intent.getStringExtra("want") ?: ""
        micWanted = intent.getBooleanExtra("mic", false)
        locWanted = intent.getBooleanExtra("loc", false)
        // policy 由 L1 下发(kv 可热更, 改采集参数不发版); 读不到/越界一律夹回保守区间
        val pol = runCatching { JSONObject(intent.getStringExtra("policy") ?: "{}") }.getOrDefault(JSONObject())
        segMs = pol.optLong("seg_ms", 300_000L).coerceIn(30_000L, 900_000L)
        maxBytes = pol.optLong("max_bytes", 512L * 1024 * 1024).coerceIn(16L * 1024 * 1024, 4096L * 1024 * 1024)
        vadRms = pol.optInt("vad_rms", 0).coerceIn(0, 8000)   // 0=不门控: 默认宁可多存也不静默丢掉可能的人声
        startedAt = System.currentTimeMillis()
        micErr = ""; silenced = false
        am = getSystemService(AudioManager::class.java)
        // startForeground 必须先于一切: A14 上类型与权限不匹配会抛, 抛了就得自杀, 否则 5s 后被系统按 ANR 处理
        val err = startFg()
        if (err.isNotEmpty()) { startErr = err; stopSelf(); return START_NOT_STICKY }
        runCatching { File(Sense.dir(this, sid), "meta.json").writeText(meta().toString()) }
        if (micWanted) startMic()
        // 唯一的源起不来就别留着服务: 否则通知栏挂着"正在记录环境音"而其实什么都没录 —— 通知本身就成了假数据
        if (micErr.isNotEmpty() && !locWanted) { startErr = "mic:$micErr"; stopSelf(); return START_NOT_STICKY }
        live = this
        // current 指针必须在 live 之后写: 反过来就留出「指针已在、live 还没置」的 1.5s 窗口(startMic 要等录音真起来),
        //  期间任一次 status / onResume 触发的 reconcile 都会把正在启动的会话误判成异常死亡 —— 删掉指针还补一条假 gap。
        runCatching { File(Sense.root(this), "current").writeText(sid) }
        return START_NOT_STICKY
    }

    private fun meta() = JSONObject().put("sid", sid).put("label", label)
        .put("started_at", startedAt).put("want", want).put("seg_ms", segMs)

    private fun zh() = java.util.Locale.getDefault().language == "zh"

    /** 返回空串=成功, 否则=如实的失败原因(绝不静默吞)。整段都进 try: 服务里漏一个异常就崩宿主 app, 而建通知/PendingIntent 同样会抛 */
    private fun startFg(): String = try {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) runCatching {
            // IMPORTANCE_LOW: 不响铃但常驻可见 —— 采集期的通知是合规明示, 不做低调化
            nm.createNotificationChannel(NotificationChannel(CH,
                if (zh()) "GA 环境记录" else "GA ambient capture", NotificationManager.IMPORTANCE_LOW))
        }
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CH)
        else @Suppress("DEPRECATION") Notification.Builder(this)
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java).putExtra("ga_src", "sense").addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), flags)
        val stopPi = PendingIntent.getService(this, 1,
            Intent(this, SenseService::class.java).setAction(ACTION_STOP), flags)
        val n = b.setContentTitle(
                if (micWanted) (if (zh()) "GA 正在记录环境音" else "GA is recording ambient audio")
                else (if (zh()) "GA 正在记录位置" else "GA is recording location"))
            .setContentText(label.ifEmpty { if (zh()) "点此返回 GA, 可随时停止" else "Tap to open GA; stop anytime" })
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true).setContentIntent(open)
            .addAction(Notification.Action.Builder(
                Icon.createWithResource(this, android.R.drawable.ic_media_pause),
                if (zh()) "停止记录" else "Stop", stopPi).build())
            .build()
        // A14 起类型必须 ⊆ manifest 声明且对应权限齐备, 故按"实际拿得到什么"选型而不是按"想要什么";
        // A13 及以下无 FGS 类型概念, 走无类型 startForeground —— 降级发生在 L0 内部, 上层无感。
        var t = 0
        if (micWanted) t = t or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        if (locWanted) t = t or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        if (Build.VERSION.SDK_INT >= 29 && t != 0) startForeground(NOTIF_ID, n, t) else startForeground(NOTIF_ID, n)
        ""
    } catch (e: Throwable) { e.toString() }

    private fun startMic() {
        val minBuf = AudioRecord.getMinBufferSize(Sense.RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minBuf <= 0) { micErr = "no_min_buffer"; return }
        // 16k/单声道/PCM16 = 全机型最低公倍数, 也正是下游 STT 所需
        val rec = try {
            AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.MIC)
                .setAudioFormat(AudioFormat.Builder().setSampleRate(Sense.RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(minBuf * 4)
                .also { if (Build.VERSION.SDK_INT >= 30) it.setPrivacySensitive(true) }
                .build()
        } catch (e: Throwable) { micErr = e.toString(); return }
        if (rec.state != AudioRecord.STATE_INITIALIZED) { micErr = "uninitialized"; runCatching { rec.release() }; return }
        watchSilence(rec)   // 必须在 startRecording 之前注册: 抢麦是"启动成功但只给静音帧", 回调是唯一权威信号
        wake = runCatching {
            (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ga:sense").also { it.acquire(12 * 3600_000L) }
        }.getOrNull()   // 带超时自释: 极端情况下也不会永久持锁
        running = true
        val ready = CountDownLatch(1)
        thread = Thread { loop(rec, ready) }.also { it.isDaemon = true; it.start() }
        runCatching { ready.await(1500, TimeUnit.MILLISECONDS) }   // 等真正 startRecording 完再返回, status 才不会先报 on 再翻脸
    }

    /** isClientSilenced() 是"被抢麦"的唯一权威信号(API29+); 低版本靠采集循环里的"连续全 0"启发式兜底 */
    private fun watchSilence(rec: AudioRecord) {
        val a = am ?: return
        val cb = object : AudioManager.AudioRecordingCallback() {
            override fun onRecordingConfigChanged(configs: MutableList<AudioRecordingConfiguration>) {
                val mine = configs.firstOrNull { it.clientAudioSessionId == rec.audioSessionId } ?: return
                silenced = Build.VERSION.SDK_INT >= 29 && mine.isClientSilenced
            }
        }
        runCatching { a.registerAudioRecordingCallback(cb, Handler(Looper.getMainLooper())) }.onSuccess { recCb = cb }
    }

    /**
     * 采集主循环: 一片一文件。四种"拿不到真音频"的静默故障(被抢麦/通话中/配额满/写不进磁盘)一律写成显式 gap(valid=false),
     * **绝不丢弃、也绝不把全 0 帧当成真音频喂给下游** —— 假录音会污染整个记忆库, 是最恶心的静默故障。
     * 分片的 bytes 一律取 close 后的磁盘真实长度: 累加器只是"意图", 只有磁盘能证明音频真的在。
     */
    private fun loop(rec: AudioRecord, ready: CountDownLatch) {
        val buf = ShortArray(2048)   // 128ms/次
        var out: FileOutputStream? = null
        var segFrom = 0L; var segBytes = 0L; var segSpeech = 0L; var segPath = ""
        var gapFrom = 0L; var gapWhy = ""
        var zeroFrom = 0L; var total = 0L; var iter = 0; var callActive = false
        var ioAt = 0L   // 最近一次写失败: 磁盘满/介质错是持续态, 靠它退避, 免得每帧都新建一个必然再失败的文件

        fun closeSeg(now: Long) {
            val o = out ?: return
            out = null
            val closed = runCatching { o.close() }.isSuccess
            // 磁盘长度是唯一真值, segBytes 只是"我以为写进去了多少": 两者对不上(或 close 失败=缓冲没落地)就说明这段
            //  没真落盘, 只能记成显式 io 缺口。留一个"看着正常、内容缺失"的分片, 下游会拿它当"那段没聊过"的证据。
            val real = runCatching { File(segPath).length() }.getOrDefault(0L)
            if (!closed || real < segBytes)
                Sense.append(this, sid, Sense.obs(sid, "audio.gap", segPath, segFrom, now, real, false, "io", 0L))
            else if (real > 0L)
                Sense.append(this, sid, Sense.obs(sid, "audio.seg", segPath, segFrom, now, real, true, "", segSpeech))
            else
                runCatching { File(segPath).delete() }   // 一个字节都没写进去(全 0 帧/VAD 全程门控): 空文件不登记也不留
        }
        fun closeGap(now: Long) {
            if (gapFrom == 0L) return
            Sense.append(this, sid, Sense.obs(sid, "audio.gap", "", gapFrom, now, 0L, false, gapWhy, 0L))
            gapFrom = 0L; gapWhy = ""
        }
        try {
            rec.startRecording()
            if (rec.recordingState != AudioRecord.RECORDSTATE_RECORDING) micErr = "not_recording"
        } catch (e: Throwable) { micErr = e.toString() }
        ready.countDown()
        if (micErr.isNotEmpty()) { runCatching { rec.release() }; return }
        try {
            while (running) {
                val n = rec.read(buf, 0, buf.size)
                val now = System.currentTimeMillis()
                if (n < 0) { micErr = "read_$n"; break }
                var peak = 0; var sum = 0.0
                for (i in 0 until n) {
                    val v = buf[i].toInt()
                    val a = if (v < 0) -v else v
                    if (a > peak) peak = a
                    sum += v.toDouble() * v
                }
                val rms = if (n > 0) sqrt(sum / n).toInt() else 0
                if (iter++ % 16 == 0) callActive = inCall()   // getMode 是 binder 调用, ~2s 一次足够
                zeroFrom = if (peak == 0) (if (zeroFrom == 0L) now else zeroFrom) else 0L
                val why = when {
                    silenced -> "silenced"
                    callActive -> "in_call"                                    // 通话中普通 App 必然拿不到音频
                    total >= maxBytes -> "quota"                               // 为什么没有原文要可解释, 而不是静默消失
                    zeroFrom != 0L && now - zeroFrom >= 5000 -> "all_zero"     // 无 isClientSilenced 版本的兜底启发式
                    ioAt != 0L && now - ioAt < 5000 -> "io"                    // 写失败退避: 磁盘满是持续态, 每帧重试只刷出一堆空文件
                    else -> ""
                }
                if (why.isNotEmpty()) {
                    closeSeg(now)
                    if (gapFrom == 0L) gapFrom = now
                    gapWhy = why
                    continue
                }
                // io 缺口只能由"真的写进去了一帧"来结束, 不能由"又新建了一个文件"来结束: 磁盘满时后者每次都成立
                if (gapWhy != "io") closeGap(now)
                if (out == null) {
                    segFrom = now; segBytes = 0L; segSpeech = 0L
                    segPath = File(Sense.dir(this, sid), "a$now.pcm").absolutePath   // 文件名只有时间戳, 不含任何内容线索
                    out = runCatching { FileOutputStream(segPath) }.getOrNull()
                    if (out == null) { ioAt = now; if (gapFrom == 0L) gapFrom = now; gapWhy = "io"; continue }
                }
                // 数字全 0 帧一律不落盘: 它零信息量, 却会在被抢麦的前 5s(判定延迟内)混进 valid 分片, 下游 ASR 对纯静音最爱幻觉。
                //  跳过写入 ⇒ 分片里永远没有假音频; 若持续 ≥5s 上面的 all_zero 会补出 valid=false 的缺口, 不会假装那段是"安静"。
                if (peak > 0 && (vadRms == 0 || rms >= vadRms)) {
                    val b = ByteArray(n * 2)
                    for (i in 0 until n) {
                        val v = buf[i].toInt()
                        b[2 * i] = (v and 0xff).toByte(); b[2 * i + 1] = ((v shr 8) and 0xff).toByte()
                    }
                    // 写失败(ENOSPC/EIO)当场收口: 已落盘的部分按真实长度结成分片, 之后如实是 io 缺口。
                    //  吞掉异常再照记 segBytes, 产出的就是"看起来正常但内容缺失"的分片 —— 假录音比没录音危险得多。
                    if (runCatching { out!!.write(b) }.isFailure) {
                        ioAt = now
                        closeSeg(now)
                        if (gapFrom == 0L) gapFrom = now
                        gapWhy = "io"
                        continue
                    }
                    closeGap(now)   // 真写进去了才算缺口结束
                    segBytes += b.size; total += b.size
                }
                if (rms >= 500) segSpeech += n * 1000L / Sense.RATE
                if (now - segFrom >= segMs) closeSeg(now)
            }
        } catch (e: Throwable) { micErr = e.toString() }
        finally {
            val now = System.currentTimeMillis()
            runCatching { closeSeg(now) }
            runCatching { closeGap(now) }
            runCatching { rec.stop() }
            runCatching { rec.release() }
        }
    }

    /** 零电话权限即可读 */
    private fun inCall(): Boolean {
        val m = runCatching { am?.mode }.getOrNull() ?: return false
        return m == AudioManager.MODE_IN_CALL || m == AudioManager.MODE_IN_COMMUNICATION
    }

    override fun onDestroy() {
        running = false
        runCatching { thread?.join(800) }
        runCatching { recCb?.let { am?.unregisterAudioRecordingCallback(it) } }
        runCatching { wake?.let { if (it.isHeld) it.release() } }
        // 指针只在正常销毁时清: 清了 reconcile 就不补 gap(正常停止不是缺口); 被强杀时指针还在, 由 reconcile 兜底
        runCatching { File(Sense.root(this), "current").delete() }
        live = null   // 必须是最后一步: 在此之前 live 仍非空, reconcile 才不会把"正在正常收尾"误判成异常死亡而补出假 gap
        // 磁贴刷新(Monitor r14 C-5): 会话从磁贴以外的路径结束(通知停止/maxBytes 截断/mic 失败自杀)时,
        // 已展开的快设面板不会自己重问状态 —— 不主动请求就一直显示「录制中」。
        runCatching {
            android.service.quicksettings.TileService.requestListeningState(
                this, android.content.ComponentName(this, SenseTileService::class.java))
        }
        super.onDestroy()
    }
}
