package com.ljq.ga

/** Physical pixels of the default display, including its current rotation. */
data class ScreenGeometry(val w: Int, val h: Int, val rot: Int) {
    init { require(w > 0 && h > 0 && rot in 0..3) { "invalid screen geometry" } }

    fun requirePoint(x: Float, y: Float) {
        require(x.isFinite() && y.isFinite() && x >= 0 && x < w && y >= 0 && y < h) {
            "coordinate outside the current screen"
        }
    }

    fun swipePoint(x: Int, y: Int): Pair<Float, Float> {
        val mx = maxOf(w * 0.04f, 24f).coerceAtMost((w - 1) / 2f)
        val mt = maxOf(h * 0.05f, 48f).coerceAtMost((h - 1) / 2f)
        val mb = maxOf(h * 0.06f, 60f).coerceAtMost((h - 1) / 2f)
        return x.toFloat().coerceIn(mx, w - 1 - mx) to y.toFloat().coerceIn(mt, h - 1 - mb)
    }
}
