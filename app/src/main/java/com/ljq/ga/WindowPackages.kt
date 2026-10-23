package com.ljq.ga

import java.util.concurrent.ConcurrentHashMap

/** Package names come from events only, never from another app's node tree. */
internal class WindowPackages {
    @Volatile private var application = ""
    private val system = ConcurrentHashMap<Int, String>()

    fun applicationChanged(pkg: String) { application = pkg }
    fun systemChanged(id: Int, pkg: String) { system[id] = pkg }
    fun retainSystem(ids: Set<Int>) { system.keys.retainAll(ids) }

    fun current(systemWindowId: Int?): String =
        if (systemWindowId == null) application else system[systemWindowId] ?: ""
}
