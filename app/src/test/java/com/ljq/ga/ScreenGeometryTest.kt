package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class ScreenGeometryTest {
    @Test fun safeSwipesStayInsideEveryScreenAndPreserveDirection() {
        for ((w, h) in listOf(320 to 480, 1080 to 2424, 2424 to 1080, 1840 to 2208, 2208 to 1840)) {
            val frame = ScreenGeometry(w, h, 0)
            val (left, top) = frame.swipePoint(0, 0)
            val (right, bottom) = frame.swipePoint(w - 1, h - 1)
            frame.requirePoint(left, top)
            frame.requirePoint(right, bottom)
            assertTrue(left < right && top < bottom)
        }
    }

    @Test fun tinyScreensCannotProduceAnInvertedClampRange() {
        for (side in listOf(1, 2, 24, 48, 60)) {
            val frame = ScreenGeometry(side, side, 0)
            val (x, y) = frame.swipePoint(side - 1, side - 1)
            frame.requirePoint(x, y)
        }
    }

    @Test fun rotationChangesIdentityEvenWithoutResizingPixels() {
        assertNotEquals(ScreenGeometry(1080, 2400, 0), ScreenGeometry(1080, 2400, 2))
        assertNotEquals(ScreenGeometry(1800, 1800, 0), ScreenGeometry(1800, 1800, 1))
    }

    @Test fun invalidTargetsAreRejectedRatherThanClampedToAnUnrelatedControl() {
        val frame = ScreenGeometry(1080, 2400, 0)
        for ((x, y) in listOf(-1f to 0f, 1080f to 0f, 0f to 2400f, Float.NaN to 1f)) {
            assertThrows(IllegalArgumentException::class.java) { frame.requirePoint(x, y) }
        }
    }
}
