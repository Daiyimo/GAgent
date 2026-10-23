package com.ljq.ga

import org.junit.Assert.assertEquals
import org.junit.Test

class WindowPackagesTest {
    @Test fun systemPanelTemporarilyOverridesTheApplication() {
        val packages = WindowPackages()
        packages.record(6, "com.tencent.mm")
        packages.record(7, "com.android.systemui")
        assertEquals("com.android.systemui", packages.current(7))
        assertEquals("com.tencent.mm", packages.current(6))
    }

    @Test fun unknownSystemWindowDoesNotExposeTheApplicationUnderIt() {
        val packages = WindowPackages()
        packages.record(6, "com.tencent.mm")
        assertEquals("", packages.current(9))
    }

    @Test fun removedWindowIdentityCannotBeReused() {
        val packages = WindowPackages()
        packages.record(7, "com.android.systemui")
        packages.removed(7)
        assertEquals("", packages.current(7))
        packages.record(7, "new.system.window")
        assertEquals("new.system.window", packages.current(7))
    }

    @Test fun eventCanArriveBeforeWindowAndInactiveEventsCannotReplaceForeground() {
        val packages = WindowPackages()
        packages.record(11, "app.new")
        assertEquals("", packages.current(null))
        assertEquals("app.new", packages.current(11))
        packages.record(12, "app.background")
        assertEquals("app.new", packages.current(11))
        assertEquals("", packages.current(13))
    }

    @Test fun unresolvedEventDoesNotAuthorizeAnUnknownWindow() {
        val packages = WindowPackages()
        packages.record(-1, "app.unknown")
        packages.record(7, " ")
        assertEquals("", packages.current(-1))
        assertEquals("", packages.current(7))
    }
}
