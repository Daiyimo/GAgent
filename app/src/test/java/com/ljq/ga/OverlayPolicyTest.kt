package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class OverlayPolicyTest {
    @Test fun runningOrWaitingTasksRestoreOnManualBackgroundEvenWithoutAlwaysOn() {
        assertTrue(needsBackgroundOverlay(true, false, true, false, false))
        assertTrue(needsBackgroundOverlay(true, false, false, true, false))
        assertFalse(needsBackgroundOverlay(true, false, false, false, false))
    }

    @Test fun permissionForegroundAndSuppressionRemainIndependentGates() {
        assertFalse(needsBackgroundOverlay(false, false, true, true, false))
        assertFalse(needsBackgroundOverlay(true, true, true, true, false))
        assertFalse(needsBackgroundOverlay(true, false, true, false, true))
        assertTrue(needsBackgroundOverlay(true, false, true, true, true))
    }

    @Test fun rotationFoldAndFreeDragCannotLeaveTheHandleOutsideTheScreen() {
        for ((sw, sh) in listOf(320 to 480, 1080 to 2424, 2424 to 1080, 1840 to 2208)) {
            for ((x, y) in listOf(-80 to -90, 2200 to 2300, 800 to 1200)) {
                for (dock in listOf(true, false)) {
                    val (nextX, nextY) = overlayPosition(x, y, 90, 144, sw, sh, dock)
                    assertTrue(nextX >= 0 && nextX + 90 <= sw)
                    assertTrue(nextY >= 0 && nextY + 144 <= sh)
                    if (dock) assertTrue(nextX == 0 || nextX == sw - 90)
                }
            }
        }
    }
}
