# Changelog / 变更记录

Entries describe repository candidates, not an assertion that every version was
publicly released. Exact artifacts and acceptance belong to their release records.

本页记录源码候选的变化，不表示各版本均已公开；制品与验收以对应发布记录为准。

## Unreleased / 未发布变更

- Vision: whether a turn may carry a screenshot is now decided by a capability bit
  (`supports_images`) instead of a hard-coded list of class names. The old check
  compared `type(backend).__name__` against three names, which silently skipped
  `NativeOAISession` — the class the device actually runs — because its conversion
  path (`_msgs_claude2oai`) turns image blocks into `image_url` perfectly well; the
  exemption it was given ("it stringifies every message into the prompt") describes
  `ToolClient`/`BaseSession.ask`, not it. The cost was invisible: in a real 25-turn
  session not a single image ever reached the model (0 occurrences of the image
  caption, 0 image blocks in the transcript) while `obs_note` told the model
  "screenshot attached" 8 times, so it kept hunting coordinates blind. `obs_note` and
  `turn_content_blocks` now share one predicate, and the text-protocol case says the
  truth ("this session cannot receive images") instead of lying.
  看图与否改由能力位 `supports_images` 决定，不再比对类名白名单：旧判据漏掉了真机
  实际在跑的 `NativeOAISession`（它的转换路径完全能带图，被排除的理由描述的其实是
  `ToolClient`/`BaseSession.ask`）。代价是隐形的——真机 25 轮会话一帧图都没发出去，
  而 `obs_note` 还说了 8 次"截图已附"。现在两处共用一个谓词，文本协议会话如实告知。
- Search: `gui_act action='search_app'` performs "open the app → tap its search entry
  → type the keyword → read it back" as one step with a per-step verdict. The entry
  anchor is a 0-1000 relative coordinate (resolution independent); nothing in the
  business flow is hard-coded. In the real session the model spent a `see` call
  (16.3s) to rediscover the magnifier position that `phone_use.md` had already
  recorded (returned rx=830, ry=79 — the documented value). `recipe_list()` also
  advertises the builtin entry path now, and tolerates a missing `memory/recipes/`
  directory instead of always returning an empty list.
  `gui_act action='search_app'` 把"打开 App→点搜索入口→输入关键词→回读"做成一步，
  每步都有判据。入口锚点是 0-1000 相对坐标（与分辨率无关），业务页坐标一个都不写死。
  真机里模型为了让视觉重新发现文档里早写好的放大镜位置，花了一次 16.3s 的 see。
- Actions: an action now counts as "proved" only by evidence about *that* action.
  `launch` requires the foreground to be the requested package (it used to accept any
  non-empty foreground, so a failed launch looked successful and skipped
  `wait_stable`); the post-action frame is tagged with its package and is never
  reused across apps; and a large screen change (diff ≥ 30%) re-takes a frame after a
  short settle instead of reusing the pending one, which is a transition frame.
  动作核验改成"只认这个动作自己的证据"：launch 要求前台确实是要拉起的包；动作后验帧
  带包名，跨 App 不复用；大跳变（≥30%）重新截一帧而不是复用过渡帧。
- Observability: read-only tools (`see`/`ocr`/`observe`) now write to the phone
  ledger, and repeating the same channel on an unchanged screen raises `[OBS-GUARD]`.
  The ledger only ever recorded actions, so a session that burned 11 `see` calls
  (164s) circling the same screen was invisible to both `[LOOP-GUARD]` and the
  every-7-turns strategy warning. `see` keeps the cheaper gates first (cache hit,
  once-per-turn) and this one last, so a cached answer is never turned into a refusal.
  只读工具（see/ocr/observe）开始记入账本，同屏同通道重复会给出 `[OBS-GUARD]`；
  see 保留"缓存命中→每轮一次"这两档在前，本档在最后，避免把已有答案变成拒绝。
- Anchor prompt: the original task statement is re-injected every turn as `[GOAL]`,
  with `[DONE]` milestones and the last `[UNMET]` expectation. A real run drifted from
  "look at the ladder inside the deck" to "find the ladder" before it had even entered
  the deck, because `<history>` only keeps the last 30 lines (older lines fold into
  summaries) and nothing restated the goal. Turns that made GUI actions without a
  verifiable result also can no longer end silently — the model must call
  `finish_task` (done/blocked) or `ask_user` instead of stopping with a checkpoint
  note, which is how a 25-turn run ended with the user receiving nothing.
  锚点每轮重注原始任务（`[GOAL]`+`[DONE]`+`[UNMET]`）；有 GUI 动作但没有可核验结果的
  轮次不再允许静默退出，必须 `finish_task`(done/blocked) 或 `ask_user`。
- Structured actions: `gui_act` now accepts pixel coordinates as well as 0-1000
  normalized ones — any value over 1000 can only be a pixel, since the normalized
  ceiling is exactly 1000, so the reading is unambiguous. A real 46-turn session
  wasted 7 whole turns on `ValueError: point must be 0-1000 normalized, got
  [752, 2512]` — half of every error in 145 tool results, and the single largest
  failure source. The cause was a contract contradiction: the schema told the
  model the point "must come from the current observation (dump bounds or
  look() box)", but both report pixels while the tool demanded 0-1000, so
  following the instruction guaranteed the error. The schema and `phone_use.md`
  §0.2 now state the conversion (`rx = round(x * 1000 / screen_w)`) and say that
  raw dump/look coordinates are accepted too.
  结构化动作现在同时收像素与 0-1000 归一化坐标（>1000 只可能是像素，无歧义）。
  真机 46 轮会话有 7 个轮次整个废在坐标单位报错上，占 145 个 tool_result 里全部
  错误的一半，是最大的单一失败源。根因是契约矛盾：schema 让模型"point 取自 dump
  bounds 或 look() box"，而那两处给的是像素，与 0-1000 的要求自相矛盾。schema 与
  phone_use.md §0.2 现在写明换算公式，并说明原始 dump/look 坐标也可直接传入。
- Structured actions: `phone_use.md` §1 now documents `ocr(img)` — it needs the
  image argument, and a bare `droid.ocr()` raises `TypeError: missing 1 required
  positional argument: 'img'` (observed on a real device). §0.1 already told the
  model to use `droid.ocr()`, but only `ocr_text` was documented.
  §1 补齐 `ocr(img)` 文档：它必须传图片参数，裸调会 TypeError（真机中过）。
- Latency: `BaseSession.history` is now capped by message count
  (`max_history_msgs`, default 20) before the size-based trim runs. Every turn
  re-sends the whole history, so an uncapped count makes per-turn cost grow
  linearly and total time quadratically: a real 19-turn run went from 829 to
  50017 re-sent characters (60x) and `model_wait` from 3.1s to 32.5s, and the
  user cancelled it for being too slow. The size cap (`context_win * 3`, up to
  90k characters) was never reached, because compression only shrinks each
  message, not the number of them. The head (task description) and the most
  recent turns are kept; older turns are covered by the working memory the anchor
  prompt injects each turn.
  每轮重发全部历史，条数不封顶则单轮成本线性涨、总时间平方涨。真机 19 轮 resend
  829→50017 字符（60x）、model_wait 3.1s→32.5s，用户因太慢取消。体积上限高达 9 万
  字符根本等不到——压缩只压单条长度，压不掉条数。保留首条与最近轮次。
- Diagnostics: an aborted or failed run now gets a backfilled
  `end_reason='unfinished'` summary. `agent_after` is not in a `finally`, so it
  never fires when the loop raises, and the previous backfill read the recorder
  from thread-local storage — but each task runs on its own thread, so the dead
  task's recorder was unreachable and the backfill could never run. Five
  consecutive aborted runs left no summary at all on a real device. The backfill
  now re-checks the previous run's file, which works across threads and
  processes, and the regression test drives the next task on a real second
  thread — the original single-threaded test could not catch this.
  中止/异常时 agent_after 不触发；原补写读线程局部的 recorder，而每个任务独立线程，
  上个任务的 recorder 谁也读不到，真机连续 5 次中止全无汇总行。改为按文件复查，
  跨线程/跨进程都生效；回归测试改用真实第二线程复现。
- Diagnostics: each session now appends a per-turn run record to
  `temp/model_responses/sessions/metrics_<id>.jsonl` — model wait, tool execution and
  post-action verification time, input/output tokens, re-sent history size, and the
  verifier that produced each verdict, plus a run summary with P50/P95 and five mutually
  exclusive verdict counters. Recording is observation only: it adds no model calls and no
  device operations, and a failed write never affects the task. The structured action
  channel (`gui_act`) made tool-level verdicts attributable: `extract_verdict` now parses
  its JSON-string result and `attrib_verifier` maps it back to the existing droid verifier
  (`_img_diff_str` / `_scroll_verdict` / `_classify_paste_rows`). `layer` is still the
  single existing `L4` with no router behind it.
  每个会话追加一份按 turn 的记录：模型等待、工具执行与动作后验耗时、输入输出 token、
  重发历史大小与每轮判定来源，附 P50/P95 与五个互斥的判定计数器。只观察，不增加模型调用与
  设备操作，写盘失败不影响任务。结构化动作通道（gui_act）落地后工具级判定已可归因：
  `extract_verdict` 解析它的 JSON 字符串结果，`attrib_verifier` 归回 droid 侧既有判定函数。
  `layer` 仍只有现存的 L4，背后还没有路由器。
- Run metrics: the verdict counters are now five mutually exclusive buckets —
  `tools_verified`, `tools_uncertain`, `tools_negative`, `tools_pixel_evidence`,
  `tools_no_verdict` — with precedence `uncertain > verified > negative > pixel > none`.
  A record carrying only `diff_pct` used to fall through every boolean test and land in
  `tools_no_verdict`, which reported 42/45 "no verdict" and a 0% verified-action rate for a
  real 46-turn run in which 16 `gui_act` actions had pixel evidence. Those records now go to
  `tools_pixel_evidence`: a changed screen proves neither success nor failure, so it is
  neither counted as success nor as a silent failure. Precedence also fixes a latent
  double count — `{'hit': True, 'uncertain': True}` was tallied as both verified and
  uncertain, pushing the sum past `tools_total` and driving `tools_no_verdict` negative.
  判定计数器改为五个互斥桶，优先级 uncertain > verified > negative > pixel > none。
  只带 `diff_pct` 的记录原先穿透所有布尔判定落进 `tools_no_verdict`，导致真机 46 轮运行
  报出 42/45"无判定"、verified-action rate 显示 0%（其中 16 次 gui_act 其实有像素证据）。
  这类记录现在进 `tools_pixel_evidence`：屏幕变了证不出成功也证不出失败，既不算成功也不算
  静默失败。优先级同时修掉一处潜在双记——`{'hit': True, 'uncertain': True}` 曾同时计入
  verified 与 uncertain，使五桶相加越过 `tools_total`、把 `tools_no_verdict` 算成负数。
- Device observation: `droid.dump_state()` returns `{nodes, degraded, pkg}` so an empty
  tree can be told apart from a policy blank (sensitive app) and an unresolved foreground;
  `dump()` delegates to it and keeps its list contract, and the `droid_dump_blank` metric
  event is unchanged. SPEC W5.
  树观测带降级原因码：`dump_state()` 区分策略置空/前台未解析/真空树；`dump()` 契约不变。
- Loop guard (SPEC W3): a process-wide action ledger (`phone_ledger`) records verified
  tap/swipe/paste/scroll outcomes; the execution boundary substitutes bounded recoveries
  (tap: WAIT→BACK→HOME→ABORT; input: REFOCUS→RETRY→ABORT), refuses repeated no-effect
  actions from the fifth equivalent attempt, and each turn injects a `[LOOP-GUARD]` hint
  when equivalence or a stuck screen is detected. Only verified facts are recorded;
  productive scrolls and screen changes reset the counters. The ledger is cleared at every
  task boundary, recovery is skipped under a policy-sensitive foreground, and "no
  observable change" uses the same ≤0.05% band as the existing miss hint.
  循环守卫：动作账本 + 三档干预（提示/改写/拒绝），全部有界；只落已验证事实；任务边界清账。

## 2.33.8 / 141 — 2026-10-25 (open-source prerelease / 开源预发布)

- Web tool: the foreground browser's screenshot no longer times out on Android WebView,
  so `open_url` works on the first try (on a MEIZU 21 every web task used to lose about
  45 s and two failed calls); a failed screenshot no longer discards an opened page.
  前台浏览器截图不再超时，网页任务不再先失败两次。
- Privacy: images in model replies are not fetched from the network (a prompt-injected
  reply could carry chat text in an image URL), and the quick-record activity is no
  longer exported, so other apps cannot make GAgent start the microphone. The launcher
  shortcuts now target this app. 回复中的远程图片不再自动加载；其他 App 不能再让 GAgent 开麦；
  桌面快捷方式改为指向本应用。
- A finished task posts one notification instead of two; idle shows “待命/Idle” instead
  of “idle”; “1 step” instead of “1 steps”; the placeholder translate button is hidden.
  完成只发一条通知；待命状态本地化；单数步数；隐藏未实现的翻译键。

## 2.33.7 / 140 — 2026-10-25 (open-source prerelease / 开源预发布)

- A task whose last model call failed (for example HTTP 429 when a provider quota runs
  out) is reported as “Error” on the floating capsule, in the task status and in the
  chat's end-of-task divider (“Task failed”), not as a green “Done”.
  末轮模型请求失败（如额度用尽返回 429）的任务在浮窗、状态和会话结尾都显示“出错”，不再显示绿色完成。
- Wireless ADB: when the phone no longer trusts GAgent's key, `droid.adb_connect()` now
  says re-pairing is needed instead of “wireless debugging may be off”, and Settings
  shows “Re-pair needed” as soon as it opens. 手机撤销信任时自连报错改为明确提示重新配对；
  设置页打开即刷新“需重新配对”状态。

## 2.33.6 / 139 — 2026-10-25 (open-source prerelease / 开源预发布)

- PC Link offers an explicit **Use the public GenericAgent relay** preset in Optional
  modules. It fills the form only after you confirm its note (the access value is the
  one already public in the GenericAgent desktop client and is not a password) and is
  used only after Save; there is still no default. PC Link 新增需确认的公共中继预设，不是默认值。
- Reasoning-effort and provider changes now reach every open conversation instead of
  only the first one. 推理强度等服务商变更会同步到所有会话。
- A task that ends by asking you shows “Reply needed” on the floating capsule instead
  of a green “Done”. 以提问结束的任务，浮窗显示“需要你回复”而不是绿色完成。
- Wireless ADB shows “Re-pair needed” when the phone no longer trusts GAgent's key.
  手机撤销无线调试信任后显示“需重新配对”。
- Troubleshooting explains that some OEMs turn accessibility off after a force stop
  and how to restore it automatically. 说明部分厂商强制停止后会关闭无障碍及自动恢复方法。

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
  motion; fading scrims no longer swallow taps. Scrims use one theme token (darker in
  dark mode) and a re-opened lower sheet is drawn on top. 系统返回只关最上层；首启同意页不再被返回关掉；
  设置子页还原父页位置，遵守减少动态效果；遮罩改用主题色值，暗色更深。
- PC Link reconnects that finish after unlinking, or during a new pairing, are
  discarded, and unlinking during a pending pairing cancels it, so an unpaired phone
  does not reconnect. 解除配对后或新配对期间迟到的重连会被丢弃，配对进行中解除会先取消配对。
- Choosing the default reasoning effort removes a previously saved level instead of
  keeping it while the UI shows the default. 推理强度切回默认时会真正清除已保存的档位。
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
