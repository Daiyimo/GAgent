package com.ljq.ga

import org.junit.Assert.assertEquals
import org.junit.Test

class VdHelperTest {
    @Test
    fun frameInsideThrottleWindowIsDeferredToWindowEndInsteadOfDropped() {
        assertEquals(300L, VdHelper.writeDelayMs(nowMs = 1_100L, lastWriteMs = 1_000L, intervalMs = 400L))
    }

    @Test
    fun frameAfterWindowIsWrittenImmediately() {
        assertEquals(0L, VdHelper.writeDelayMs(nowMs = 1_500L, lastWriteMs = 1_000L, intervalMs = 400L))
        assertEquals(0L, VdHelper.writeDelayMs(nowMs = 5_000L, lastWriteMs = 0L, intervalMs = 400L))
    }

    @Test
    fun clockSkewNeverDelaysLongerThanOneInterval() {
        assertEquals(400L, VdHelper.writeDelayMs(nowMs = 900L, lastWriteMs = 1_000L, intervalMs = 400L))
    }
}
