package com.ljq.ga

// 脱敏正则与函数集中点：Analytics(track 事件) 与 Diag(日志/上传) 两处口径合一。
// pii()  —— 仅抹 email/手机号（Analytics.sanitize 口径：字符串上报值宽松一档）。
// full() —— 抹 email/手机号/sk-令牌/Bearer/KV 键值（Diag 上传前口径：完整错误日志/文件更严）。
// 两口径差异是既有设计（Diag.uploadLogs 注释明确指出 Analytics 队列不覆盖 sk-/Bearer/KV），本次合并不改字节、不收紧也不放松。
object Scrub {
    val RE_EMAIL = Regex("""[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}""")
    val RE_PHONE_CN = Regex("""(?<!\d)1[3-9]\d{9}(?!\d)""")
    val RE_SK = Regex("""sk-[A-Za-z0-9_\-]{6,}""")
    val RE_BEARER = Regex("""(?i)(Bearer\s+)[A-Za-z0-9._\-]+""")
    val RE_KV = Regex("""(?i)((?:api[_-]?key|key|token|secret|password|authorization)["'\s]*[=:]\s*["']?)[^\s,;"']+""")

    fun pii(s: String): String =
        RE_PHONE_CN.replace(RE_EMAIL.replace(s, "[email]"), "[phone]")

    fun full(s: String): String {
        var r = RE_EMAIL.replace(s, "[email]")
        r = RE_PHONE_CN.replace(r, "[phone]")
        r = RE_SK.replace(r, "sk-***")
        r = RE_BEARER.replace(r) { m -> m.groupValues[1] + "***" }
        r = RE_KV.replace(r) { m -> m.groupValues[1] + "***" }
        return r
    }
}
