package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class OwnWindowMaskTest {
    @Test fun rectsAreScaledPaddedClippedAndEmptyOnesDropped() {
        val out = frameMaskRects(listOf(intArrayOf(10, 20, 30, 40), intArrayOf(-50, -50, -10, -10),
            intArrayOf(1070, 2300, 1200, 2500)), 1080, 2340, 540, 1170, 2)
        assertEquals(2, out.size)
        assertArrayEquals(intArrayOf(3, 8, 17, 22), out[0])
        assertArrayEquals(intArrayOf(533, 1148, 540, 1170), out[1])
        assertTrue(frameMaskRects(listOf(intArrayOf(0, 0, 10, 10)), 0, 0, 10, 10, 0).isEmpty())
    }

    @Test fun rowsBlendOutsideNeighboursAndLeaveOtherPixelsUntouched() {
        val w = 6; val h = 3
        val black = 0xFF000000.toInt(); val white = 0xFFFFFFFF.toInt(); val text = 0xFF123456.toInt()
        val px = IntArray(w * h) { i -> when (i % w) { 0 -> black; 5 -> white; else -> text } }
        inpaintRect(px, w, h, 1, 0, 5, 2)
        for (y in 0 until 2) {
            val row = (0 until w).map { px[y * w + it] }
            assertEquals(black, row[0]); assertEquals(white, row[5])
            assertTrue(row.none { it == text })
            val greens = row.map { (it ushr 8) and 0xFF }
            assertEquals(greens, greens.sorted())
        }
        assertEquals(text, px[2 * w + 2])
    }

    @Test fun edgeAndFullWidthRectsUseTheAvailableNeighbours() {
        val w = 4; val h = 4
        val bg = 0xFF808080.toInt(); val text = 0xFF00FF00.toInt()
        val edge = IntArray(w * h) { if (it % w == 0) text else bg }
        inpaintRect(edge, w, h, 0, 0, 1, h)
        assertTrue(edge.all { it == bg })

        val band = IntArray(w * h) { if (it / w == 1) text else bg }
        inpaintRect(band, w, h, 0, 1, w, 2)
        assertTrue(band.all { it == bg })

        val all = IntArray(w * h) { text }
        inpaintRect(all, w, h, -5, -5, 10, 10)
        assertTrue(all.all { it == 0xFF000000.toInt() })
        inpaintRect(all, w, h, 3, 3, 3, 9)
    }
}
