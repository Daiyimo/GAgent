package com.ljq.ga

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

class JobRegistry {
    private val seq = AtomicInteger(0)
    private val results = ConcurrentHashMap<String, String>()

    fun newId(prefix: String): String {
        val id = prefix + seq.incrementAndGet()
        results[id] = "pending"
        return id
    }

    fun set(id: String, v: String) { results[id] = v }

    fun resultOnce(id: String): String {
        val v = results[id] ?: return "err:unknown-id"
        if (v != "pending") results.remove(id)
        return v
    }
}
