package com.ljq.ga

/** Main-thread leases: an old gesture's cancellation must not unlock a newer one. */
internal class OverlayGestureLeases(private val update: (Boolean) -> Unit) {
    private var active = 0

    fun acquire(): () -> Unit {
        if (active == 0) update(true)
        active++
        var released = false
        return {
            if (!released) {
                released = true
                active--
                if (active == 0) update(false)
            }
        }
    }
}
