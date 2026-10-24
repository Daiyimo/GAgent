package com.ljq.ga

/*
 * Screen observation must describe the app under automation, not GAgent's own overlay.
 * Invariant: every pixel drawn by this app's overlay windows is replaced by a blend of the
 * pixels just outside it, so OCR and the UI detector cannot read our own status text.
 * Geometry is sampled by the window owner; this file only contains pure pixel math.
 */

/** Map window rects from display space to frame space, pad them, clip to the frame, drop empties. */
internal fun frameMaskRects(rects: List<IntArray>, displayWidth: Int, displayHeight: Int,
                            frameWidth: Int, frameHeight: Int, pad: Int): List<IntArray> {
    if (displayWidth <= 0 || displayHeight <= 0 || frameWidth <= 0 || frameHeight <= 0) return emptyList()
    val sx = frameWidth.toDouble() / displayWidth
    val sy = frameHeight.toDouble() / displayHeight
    return rects.mapNotNull { r ->
        val l = (Math.floor(r[0] * sx).toInt() - pad).coerceIn(0, frameWidth)
        val t = (Math.floor(r[1] * sy).toInt() - pad).coerceIn(0, frameHeight)
        val rr = (Math.ceil(r[2] * sx).toInt() + pad).coerceIn(0, frameWidth)
        val b = (Math.ceil(r[3] * sy).toInt() + pad).coerceIn(0, frameHeight)
        if (rr > l && b > t) intArrayOf(l, t, rr, b) else null
    }
}

private fun blend(a: Int, b: Int, num: Int, den: Int): Int {
    fun ch(shift: Int): Int {
        val x = (a ushr shift) and 0xFF
        val y = (b ushr shift) and 0xFF
        return (x + (y - x) * num / den) and 0xFF
    }
    return (ch(24) shl 24) or (ch(16) shl 16) or (ch(8) shl 8) or ch(0)
}

/**
 * In-place fill of [l,r)x[t,b) inside a bw*bh ARGB buffer.
 * Rows blend their left/right outside neighbours; a rect spanning the full width blends
 * the rows above/below; a rect covering the whole buffer becomes opaque black.
 */
internal fun inpaintRect(px: IntArray, bw: Int, bh: Int, l: Int, t: Int, r: Int, b: Int) {
    require(px.size >= bw * bh) { "buffer smaller than bw*bh" }
    val x0 = l.coerceIn(0, bw); val x1 = r.coerceIn(0, bw)
    val y0 = t.coerceIn(0, bh); val y1 = b.coerceIn(0, bh)
    if (x1 <= x0 || y1 <= y0) return
    val horizontal = x0 > 0 || x1 < bw
    val vertical = y0 > 0 || y1 < bh
    for (y in y0 until y1) for (x in x0 until x1) {
        px[y * bw + x] = when {
            horizontal -> {
                val left = if (x0 > 0) px[y * bw + x0 - 1] else px[y * bw + x1]
                val right = if (x1 < bw) px[y * bw + x1] else left
                blend(left, right, x - x0 + 1, x1 - x0 + 1)
            }
            vertical -> {
                val top = if (y0 > 0) px[(y0 - 1) * bw + x] else px[y1 * bw + x]
                val bottom = if (y1 < bh) px[y1 * bw + x] else top
                blend(top, bottom, y - y0 + 1, y1 - y0 + 1)
            }
            else -> 0xFF000000.toInt()
        }
    }
}
