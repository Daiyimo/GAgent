package com.ljq.ga

import java.security.MessageDigest
import java.security.SecureRandom

/** Process-scoped capability; never embedded in an APK or sent to a remote host. */
class LocalBusAuth private constructor(val token: String) {
    fun accepts(header: String?): Boolean = header != null && MessageDigest.isEqual(
        "Bearer $token".toByteArray(Charsets.UTF_8), header.toByteArray(Charsets.UTF_8))

    companion object {
        fun create(): LocalBusAuth {
            val bytes = ByteArray(32).also { SecureRandom().nextBytes(it) }
            return LocalBusAuth(bytes.joinToString("") { "%02x".format(it) })
        }
    }
}
