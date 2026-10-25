package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class AdbRepairTest {
    @Test fun revokedTrustAsksForRepairing() {
        assertTrue(adbNeedsRepair("io.github.muntashirakon.adb.AdbPairingRequiredException: ADB pairing is required."))
        assertTrue(adbNeedsRepair("connect 失败: ADB pairing is required"))
    }
    @Test fun otherFailuresAreNotRepairs() {
        for (e in listOf(null, "", "java.net.ConnectException: Connection refused", "shell 超时且传输已卡死"))
            assertFalse(e.toString(), adbNeedsRepair(e))
    }
}
