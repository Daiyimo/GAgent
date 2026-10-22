package com.ljq.ga

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Handler
import android.os.HandlerThread
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface
import tsbridge.Tsbridge

/**
 * GA 门控入网 (tsnet 嵌入): 薄封装 tsbridge.aar (Go/gomobile 产物)。
 * 职责边界: 这里只管「拿着 preauthkey 入网 + 本地端口转发」；
 * 换 key 的授权链(GAuth JWT -> provision)在 Python 侧 ganet.py 完成, Kotlin 不碰凭据。
 */
object GaNet {
    private const val NETWORK_REFRESH_DELAY_MS = 250L
    private val networkLock = Any()
    private val networkThread = HandlerThread("ganet-network").apply { start() }
    private val networkHandler = Handler(networkThread.looper)
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var selectedNetwork: Network? = null
    private var selectedLinkProperties: LinkProperties? = null
    private val availableNetworks = linkedSetOf<Network>()
    private val refreshNetwork = Runnable { publishNetworkSnapshot() }

    fun initNetworkMonitoring(ctx: Context) {
        synchronized(networkLock) {
            if (networkCallback != null) return
            val cm = ctx.applicationContext.getSystemService(ConnectivityManager::class.java) ?: return
            val callback = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    synchronized(networkLock) { availableNetworks.add(network) }
                    updateNetwork(cm, network)
                }

                override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                    synchronized(networkLock) { availableNetworks.add(network) }
                    if (capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
                        updateNetwork(cm, network)
                    }
                }

                override fun onLinkPropertiesChanged(network: Network, linkProperties: LinkProperties) {
                    synchronized(networkLock) { availableNetworks.add(network) }
                    updateNetwork(cm, network)
                }

                override fun onLost(network: Network) {
                    synchronized(networkLock) {
                        availableNetworks.remove(network)
                        if (selectedNetwork == network) {
                            selectedNetwork = null
                            selectedLinkProperties = null
                            chooseNetworkLocked(cm, excluded = network)
                        }
                    }
                    scheduleNetworkRefresh()
                }
            }
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
            try {
                cm.registerNetworkCallback(request, callback)
                connectivityManager = cm
                networkCallback = callback
                chooseNetworkLocked(cm)
            } catch (e: Exception) {
                android.util.Log.w("GA", "GaNet register network callback failed", e)
            }
        }
        scheduleNetworkRefresh()
    }

    /** 从持久 state 恢复节点；authKey 只在首次登记或 state 失效后提供。 */
    fun join(ctx: Context, controlUrl: String, authKey: String, hostname: String,
             forwardPort: Int, remoteAddr: String): String {
        val dir = File(ctx.filesDir, "tsnet").apply { mkdirs() }
        val durable = File(dir, ".durable-v1")
        if (authKey.isEmpty() && (!File(dir, "tailscaled.state").isFile || !durable.isFile)) {
            // Older builds registered an ephemeral node. Its state cannot become a
            // durable identity merely by changing the next Server config, so rotate it once.
            if (!durable.isFile) dir.deleteRecursively()
            throw IllegalStateException("ganet_state_missing")
        }
        publishNetworkSnapshot() // SDK30+ 禁 netlink；同时在 Up 前提供默认路由信息
        try {
            Tsbridge.up(dir.absolutePath, controlUrl, authKey, hostname)
        } catch (e: Exception) {
            // Only tsbridge's explicit diagnostic proves the server discarded this
            // identity. Transient network/control-plane failures keep the state intact.
            if (authKey.isEmpty() && e.message?.contains("tsbridge_auth_required") == true) {
                dir.deleteRecursively()
                throw IllegalStateException("ganet_state_missing")
            }
            throw e
        }
        if (authKey.isNotEmpty()) File(dir, ".durable-v1").writeText("1")
        if (forwardPort > 0 && remoteAddr.isNotEmpty()) {
            Tsbridge.forward(forwardPort.toLong(), remoteAddr)
        }
        return Tsbridge.statusJSON()
    }

    fun forward(forwardPort: Int, remoteAddr: String): String {
        Tsbridge.forward(forwardPort.toLong(), remoteAddr)
        return Tsbridge.statusJSON()
    }

    fun status(): String = Tsbridge.statusJSON()

    fun dialTest(remoteAddr: String): String = Tsbridge.dialTest(remoteAddr)

    fun down() = Tsbridge.down()

    private fun updateNetwork(cm: ConnectivityManager, network: Network) {
        synchronized(networkLock) {
            chooseNetworkLocked(cm, network)
        }
        scheduleNetworkRefresh()
    }

    private fun chooseNetworkLocked(cm: ConnectivityManager, candidate: Network? = null,
                                    excluded: Network? = null) {
        val networks = buildList {
            if (candidate != null && candidate != excluded) add(candidate)
            cm.activeNetwork?.takeIf { it != candidate && it != excluded }?.let(::add)
            addAll(availableNetworks.filter { it != candidate && it != excluded && it != cm.activeNetwork })
        }
        val active = cm.activeNetwork
        val chosen = networks
            .mapNotNull { network ->
                val caps = cm.getNetworkCapabilities(network) ?: return@mapNotNull null
                if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) ||
                    !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) return@mapNotNull null
                Triple(network, caps, cm.getLinkProperties(network))
            }
            .maxByOrNull { (network, caps, links) ->
                var score = 0
                if (network == active) score += 8
                if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) score += 4
                if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) score += 2
                if (!links?.interfaceName.isNullOrEmpty()) score += 1
                score
            }
        selectedNetwork = chosen?.first
        selectedLinkProperties = chosen?.third
    }

    private fun scheduleNetworkRefresh() {
        networkHandler.removeCallbacks(refreshNetwork)
        networkHandler.postDelayed(refreshNetwork, NETWORK_REFRESH_DELAY_MS)
    }

    private fun publishNetworkSnapshot() {
        val interfacesJSON = enumerateInterfacesJSON()
        val links = synchronized(networkLock) {
            val cm = connectivityManager
            if (cm != null && selectedNetwork == null) chooseNetworkLocked(cm)
            selectedLinkProperties
        }
        val defaultInterface = links?.interfaceName.orEmpty()
        val defaultGateway = links?.routes
            ?.asSequence()
            ?.filter { it.isDefaultRoute && it.gateway != null }
            ?.sortedBy { if (it.gateway is Inet4Address) 0 else 1 }
            ?.mapNotNull { it.gateway?.hostAddress?.substringBefore('%') }
            ?.firstOrNull()
            .orEmpty()
        try {
            Tsbridge.networkChanged(interfacesJSON, defaultInterface, defaultGateway)
        } catch (e: Exception) {
            android.util.Log.w("GA", "GaNet network snapshot update failed", e)
        }
    }

    /**
     * 用 Java NetworkInterface(系统对 app 放行)枚举网卡 → JSON → 喂给 Go 侧
     * (tsbridge.SetInterfacesJSON, 经 netmon.RegisterInterfaceGetter 替代 net.Interfaces())。
     * 绕开 Android SDK30+ 的 netlink 禁令("route ip+net: netlinkrib: permission denied")。
     * schema 与官方 tailscale-android libtailscale/ifaceparse 对齐: [{name,index,mtu,up,...,addrs:[{ip,prefixLen}]}]
     */
    private fun enumerateInterfacesJSON(): String {
        val arr = JSONArray()
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces() ?: return arr.toString()
            for (ni in interfaces) {
                val o = JSONObject()
                try {
                    o.put("name", ni.name)
                    o.put("index", ni.index)
                    o.put("mtu", ni.mtu)
                    o.put("up", ni.isUp)
                    o.put("broadcast", !ni.isLoopback && !ni.isPointToPoint)
                    o.put("loopback", ni.isLoopback)
                    o.put("pointToPoint", ni.isPointToPoint)
                    o.put("multicast", ni.supportsMulticast())
                    val addrs = JSONArray()
                    for (ia in ni.interfaceAddresses) {
                        val ip = ia.address.hostAddress ?: continue
                        addrs.put(JSONObject()
                            .put("ip", ip.substringBefore('%'))   // 去掉 IPv6 zone 后缀(如 %wlan0), Go 侧按纯地址解析
                            .put("prefixLen", ia.networkPrefixLength.toInt()))
                    }
                    o.put("addrs", addrs)
                    arr.put(o)
                } catch (_: Exception) { /* 单网卡读取失败跳过, 不影响其余 */ }
            }
        } catch (e: Exception) {
            android.util.Log.w("GA", "GaNet enumerate interfaces failed", e)
        }
        return arr.toString()
    }
}
