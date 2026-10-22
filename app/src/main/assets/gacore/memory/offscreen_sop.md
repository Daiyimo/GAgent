# offscreen_sop — 离屏模式速查(关键点+坑点)

「离屏」是两条不同链路, 先分清(词义对照唯一正文=phone_use.md §2, 本文不复制):
- **网页离屏** = `webcdp.open_url(url, background=True)`: 离屏 WebView, 不遮对话页。仅当用户明确说「后台/别占屏/不打扰」才用; 没说后台一律 L1 前台任务浏览器。
- **App 离屏** = `import vdisplay`(docstring=完整 SOP): 第三方 App 跑在虚拟屏。前置=self-adb 已连(memory/adb_self_setup.md)。

## 网页离屏(webcdp L2)
- 只驱动 GA 自建哨兵 tab(白名单 fail-closed); 失败显式 raise→按 phone_use §2 降级, ⚠禁 role='raw'(会连系统 Chrome)。
- 与前台/登录 WebView 共享 cookie, 登录态自动复用; 截图用 web_shot(离屏页默认持续光栅化, v2.19 已修)。

## App 离屏(vdisplay)生命周期
- 开工先 `vd_status()`; alive=True=上一会话遗留活屏, 先 `vd_shot()` 认清现状再决定复用/重启, 勿假设在主页。
- 收工必 `vd_stop()`(关持有流=确定性回收; 遗留屏会把下一会话 resume 到旧页面, 诱发多轮误诊)。
- 虚拟屏模式下主屏 tap/launch/home=破坏用户意图; 仅 vd 明确不可用且已告知用户才降级前台。
- launch 后 fg 未变≠失败: app 可能被 resume 到遗留虚拟屏, 看 `vd_status()`/`dumpsys activity` 的 display 归属再诊断。

## 坑点(细则=vdisplay docstring, 设备端唯一细则源, 勿凭印象)
- `vd_text` 仅 ASCII 可靠; 中文一律 app scheme 深链 `am start --display <vid> -a android.intent.action.VIEW -d '<scheme>://…'`(URL 编码), 失效再退 vd_tap。
- FLAG_SECURE App 在虚拟屏同样黑帧; droid.shot/vd_shot 拿黑帧按报错提示降级, 勿盲目重截。
- vd_shot 无帧/超时: 走 `screencap -d <SF物理id>` 落文件直读, 勿 base64 走文本 bus(大帧超时)。
