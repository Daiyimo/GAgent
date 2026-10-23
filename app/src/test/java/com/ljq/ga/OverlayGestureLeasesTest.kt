package com.ljq.ga

import org.junit.Assert.assertEquals
import org.junit.Test

class OverlayGestureLeasesTest {
    @Test fun cancellationAndTimeoutCannotReleaseANewerGesture() {
        val updates = mutableListOf<Boolean>()
        val leases = OverlayGestureLeases { updates.add(it) }
        val first = leases.acquire()
        val second = leases.acquire()
        first()
        first() // callback and timeout may both arrive
        assertEquals(listOf(true), updates)
        second()
        second()
        assertEquals(listOf(true, false), updates)
        leases.acquire()()
        assertEquals(listOf(true, false, true, false), updates)
    }

    @Test fun failedPreparationDoesNotLeaveAPhantomLease() {
        val updates = mutableListOf<Boolean>()
        var fail = true
        val leases = OverlayGestureLeases {
            if (fail) throw IllegalStateException("window unavailable")
            updates.add(it)
        }
        try { leases.acquire() } catch (_: IllegalStateException) { }
        fail = false
        leases.acquire()()
        assertEquals(listOf(true, false), updates)
    }
}
