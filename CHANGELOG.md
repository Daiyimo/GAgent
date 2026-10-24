# Changelog / 变更记录

Entries describe repository candidates, not an assertion that every version was
publicly released. Exact artifacts and acceptance belong to their release records.

本页记录源码候选的变化，不表示各版本均已公开；制品与验收以对应发布记录为准。

## Unreleased / 未发布变更

- PC Link no longer ships a build-injected relay default. CI stops writing
  `pclink_defaults.json`, the APK audit rejects that asset, and runtime ignores a
  stale copy from older builds; configure your own relay URL and credential in
  Optional modules. PC Link 不再在构建中注入默认中继凭据：CI 不写入、APK 审计拒绝该文件、
  运行时忽略旧版残留，请在可选组件填写自己的中继地址与凭据。
  Optional modules no longer claim a blank PC Link URL restores a default; an
  unconfigured PC Link tap opens its relay fields. 可选组件页去掉“清空恢复默认”的旧说明。
- System back closes only the topmost layer, ordered by the layers' own stacking:
  dialogs and the detector close before the page beneath, stacked sheets step back
  one level, and back on the first-run consent leaves the app instead of dismissing
  it (which left a blank window). Settings sub-pages open at the top and restore the
  parent position on back, with an interruptible enter that is instant under reduced
  motion; fading scrims no longer swallow taps. 系统返回只关最上层；首启同意页不再被返回关掉；
  设置子页还原父页位置，遵守减少动态效果。
- Streaming voice checks its configuration before asking for the microphone and
  opens the voice settings when unset. 语音未配置时不再先申请麦克风。
- A local bus start failure no longer stops the app from opening, and crash capture
  starts first. 本机总线启动失败不再导致应用打不开。
- Detector boxes are clipped to the observed screen. Main-model requests and
  observation hops record timing for slow-task attribution (observe-only).
  检测框限制在屏幕内；记录主模型请求与观察步骤耗时（只观察，不改行为）。

- The floating capsule and task-end notification no longer report a user-stopped
  or failed task as "✔ Done": the core now exposes an `end` reason
  (`done`/`stopped`/`error`) and the capsule shows "■ 已停止" (no alert) or a red
  "⚠ 出错". 悬浮胶囊不再把用户中止或出错的任务显示为「完成」。
- Rebuild optional-module settings (PC Link, mesh, GAnet, streaming voice, APK
  build service) as a themed settings page with labelled fields, status chips and
  inline errors; settings secondary text now meets WCAG AA in light and dark.
  可选组件设置改为统一主题的设置子页；设置页次要文字在浅/暗色下满足对比度要求。
- Configured provider rows show their model names in readable secondary text.
  服务商列表中的模型名改用可读的次要文字颜色。
- Placeholder hints (chat composer, drawer search, optional-module `wss://`
  examples and the saved-token hint) now meet WCAG AA; the contrast test checks
  `::placeholder` of empty fields. 输入框占位提示在浅/暗色下达到对比度要求。
- The floating capsule's transparency preference now fades only the capsule
  body; status text stays opaque (white with a dark halo when the body is too
  transparent), so "✔ 完成" stays readable at 30%. 悬浮胶囊透明度只淡化底色，文字保持可读，偏好值不变。
- Exclude GAgent's own overlay windows from `droid.shot()` frames so OCR, the UI
  detector and vision models no longer read the status capsule's text.
  截图抹平 GA 自身悬浮窗区域，避免 OCR/视觉模型读到自己的状态文字。
- Virtual display: refuse to move a task the user has in the foreground, reject
  points outside the display, require frames newer than the last input and write
  a trailing frame after motion stops (frame metadata includes size and PID).
  离屏虚拟屏：拒绝抢占用户前台同一 App、坐标越界拒绝、帧须新于最近输入并补尾帧。
- Agent guidance uses view-direction `scroll_view()` consistently and warns that
  `back()` may leave the page instead of closing an in-page drawer.
- Destroy the previous chat WebView when the system theme, locale or font size
  recreates the main screen, so stale pages stop polling in the background.
  系统深浅色等配置变更重建主界面时销毁旧 WebView，避免旧页面继续后台轮询。
- Document why YOLO weights stay user-installed and the permissive alternatives
  for a bundled detector. 说明 YOLO 不内置的原因及可再分发的替代路线。

- Fix virtual-display adapter import: load `os` before reading the installation's
  package identity; cover default and debug identities without device access.
- Present the public source preview with a sourced DeepSeek Android comparison,
  scoped core-size claims, memory/token guidance and optional workflow setup.

- Add the GAgent logo, redesigned bilingual landing pages, ecosystem/download
  navigation, practical case guides and evidence-linked development milestones.
- Add a complete capability setup matrix and importable service-profile example;
  clarify YOLO installation, visual-model setup and independent verification.
- Permit reviewed public website navigation in source docs while retaining
  credential, runtime-endpoint and APK/archive checks; add focused regressions.
- Rewrite English and Chinese READMEs around actual capabilities, setup and limits.
- Add first-run, development, testing, troubleshooting, validation and release guides.
- Define contribution/review requirements, bilingual PR and issue templates,
  project decisions and community conduct.
- Correct provider-settings copy: keys are stored locally and sent to the chosen
  provider for authentication.
- Document unresolved native dependencies, physical-device coverage and optional
  module/YOLO licensing boundaries without treating them as completed work.

## 2.33.3 / 136 — 2026-10-23 candidate

- Honor provider proxy configuration in visual requests and expose one lazy
  `droid.ask_vision` entry.
- Request correction for malformed text tool calls instead of silently ending;
  reject malformed mixed batches without partial execution.
- Observe active system panels correctly and expose slider bounds/current values.
- Validate visual detector arguments and clarify GUI selection/clipboard feedback.
- Bind gestures to explicit observed display geometry; reject stale or
  out-of-bounds coordinates, including same-size 180° rotation.
- Restore task overlays when the app moves to the background, honor always-on
  in visual-only apps and constrain overlay placement after display changes.

See [Validation](docs/VALIDATION.md): the representative task sample still has
partial and blocked outcomes. Real foldable/OEM coverage and native dependency
migration remain open.

## Earlier extraction / 早期剥离

The initial repository combined Android beta 2.33.0 / 133 with later PC Link
changes, starting a clean source history at 2.33.1 / 134. The 2.33.2 / 135 candidate
established the visual-only WeChat policy and optional detector guidance.
Mandatory commercial/account flows, bundled service authority and source
encryption were removed from this distribution; original attribution and necessary
Kotlin device code remain. See [Feature scope](docs/FEATURE_SCOPE.md) and
[Extraction review](docs/REVIEW.md).
