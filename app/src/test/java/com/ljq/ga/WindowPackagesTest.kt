package com.ljq.ga

import org.junit.Assert.assertEquals
import org.junit.Test

class WindowPackagesTest {
    @Test fun systemPanelTemporarilyOverridesTheApplication() {
        val packages = WindowPackages()
        packages.applicationChanged("com.tencent.mm")
        packages.systemChanged(7, "com.android.systemui")
        assertEquals("com.android.systemui", packages.current(7))
        assertEquals("com.tencent.mm", packages.current(null))
    }

    @Test fun unknownSystemWindowDoesNotExposeTheApplicationUnderIt() {
        val packages = WindowPackages()
        packages.applicationChanged("com.tencent.mm")
        assertEquals("", packages.current(9))
    }

    @Test fun removedWindowIdentityCannotBeReused() {
        val packages = WindowPackages()
        packages.systemChanged(7, "com.android.systemui")
        packages.retainSystem(emptySet())
        assertEquals("", packages.current(7))
        packages.systemChanged(7, "new.system.window")
        assertEquals("new.system.window", packages.current(7))
    }
}
