package com.ljq.ga

import java.util.concurrent.ConcurrentHashMap

/** Package names come from events only, never from another app's node tree. */
internal class WindowPackages {
    private val packages = ConcurrentHashMap<Int, String>()

    fun record(id: Int, pkg: String) {
        if (id >= 0 && pkg.isNotBlank()) packages[id] = pkg
    }
    fun removed(id: Int) { packages.remove(id) }

    fun current(windowId: Int?): String = windowId?.let { packages[it] } ?: ""
}
