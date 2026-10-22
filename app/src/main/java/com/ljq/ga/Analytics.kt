package com.ljq.ga

import android.content.Context

/** Compatibility boundary for existing event call sites. No collection or transport. */
@Suppress("UNUSED_PARAMETER")
object Analytics {
    fun init(ctx: Context) = Unit
    fun track(eventJson: String) = Unit
    fun trackSync(eventJson: String) = Unit
    fun setUser(uid: String?) = Unit
    fun clearUser() = Unit
    fun flush() = Unit
    fun drainAgentEvents() = Unit
}
