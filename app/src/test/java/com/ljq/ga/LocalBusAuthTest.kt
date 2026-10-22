package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class LocalBusAuthTest {
    @Test fun deniesMissingWrongAndPreviousProcessCapabilities() {
        val auth = LocalBusAuth.create()
        assertFalse(auth.accepts(null))
        assertFalse(auth.accepts(""))
        assertFalse(auth.accepts("Bearer ${LocalBusAuth.create().token}"))
        assertFalse(auth.accepts("Bearer ${auth.token}extra"))
        assertTrue(auth.accepts("Bearer ${auth.token}"))
    }
}
