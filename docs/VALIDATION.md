# Validation snapshot / 验收快照

**Date:** 2026-10-23

**Android baseline:** 2.33.3 / 136

**Open-source device-build commit:** `6c4683a1a36ccc7b3b9a121099b81ef2d1d75422`

This is a bounded engineering record, not a certification or overall accuracy
claim. Later commits need checks appropriate to their changes; they do not
automatically inherit complete device acceptance from this snapshot.

本页记录一次有边界的验收，不代表所有设备、模型或任务均通过。后续提交需按变化补充证据。

## Automated build / 自动构建

[Android CI run 39930370841](https://github.com/shenhao-stu/GAgent/actions/runs/39930370841)
passed source/archive and history scans, Python/UI regressions, Kotlin tests,
both APK builds and packaged-content checks. Actions artifact retention is limited; a release must preserve its
reviewed source and artifact metadata separately.

The focused Python regressions passed in both development trees. Geometry and
overlay decisions also have Kotlin unit coverage. These checks are not an
independent security audit; native dependency limitations remain in
[Dependency security](DEPENDENCY_SECURITY.md).

## Physical device / 实机

Device: Pixel 10, Android 16, default display. The tested OSS installation was
the debug variant, upgraded without clearing data. It had a separately installed
optional detector; task results therefore do not establish identical behavior for
an OCR-only fresh installation.

测试设备保留了用户自行安装的可选检测模型；不能把这组任务结果直接当成默认无 YOLO 包的效果。

| Check / 项目 | Observed result / 实际结果 |
| --- | --- |
| Phone-local GLM-5.3-flash transport | 3 text + 2 synthetic-image requests passed; 1.385–2.806 seconds, including droid.ask_vision |
| Background task → Home → app → Home | Overlay restored in both background transitions: 483 / 649 ms |
| WeChat with always-on enabled | Overlay remained visible through the nofloat launch path; no WeChat node-tree reads |
| Rotation 0° / 90° / 180° / 270° | Screenshot and display geometry agreed; stale and out-of-bounds coordinates were rejected |
| Fresh portrait/landscape gesture | Own-app input focused and keyboard appeared; no text submitted |
| Settings preservation | Rotation settings restored after testing; no ADB reverse transport used |

An earlier network probe observed a transient SSL EOF that recovered. A phone-local
proxy was configured for the tested provider. This does not establish stability
on every network. An actual ADB disconnection during a task did not stop the phone
session; the exact physical unplug interval was not measured.

此前出现过一次恢复后的 SSL EOF。无 USB 代理和一次断连继续运行，不等于所有网络均无超时。

## Representative task sample / 代表性任务

Eight original queries across six task families were attempted during candidate
iteration, with the same GLM model but evolving adapters/instructions. App history
was retained, so repeated runs were warm. The final overlay/geometry commit did
not receive a new full run of all eight queries.

| Task family / 任务 | Last attempt / 最后一次结果 | Limitation / 说明 |
| --- | --- | --- |
| System settings L1 | Passed | Verified final setting; restored original state |
| System settings L2 | Passed | Verified mode and value; restored original state |
| Bilibili L1 | Passed | GUI sort selection verified; filter drawer left open |
| Bilibili L2 | Partial | Date range broadened; combined duration selection not established |
| Used-goods search | Partial | Price ordering not established; accessory mistaken for the complete product |
| Meeting app | Blocked | Existing login expired; no login or meeting join |
| Route query | Passed | Route read back; matching history provided a warm-state advantage |
| Trending list | Partial | Pinned item confused with numbered rank |

Result: **4 passed, 3 partial, 1 blocked**. This is not a randomized A/B comparison,
a full benchmark, or evidence that a different historical model/version regressed.
Uninstrumented token fields must not be interpreted as zero use.

结果为4通过、3部分完成、1阻塞。保留失败，按实际状态而不是模型自述计分；
不同日期和模型的历史记录不能直接证明版本退化。

A separate WeChat mini-program task reached the phone-login boundary. Login was
deferred by the device owner; checkout, order submission and payment were not
completed. No full shopping-flow success is claimed.

## Meizu fresh-install follow-up / 魅族首次安装补充

**Date:** 2026-10-24. MEIZU 21, Android 16 / API 36, arm64, 1080 × 2340,
portrait. Release APK installed fresh at `4b33fb4`, then upgraded to `960edb1`
without clearing data; the separate closed-source package was preserved.
[CI for `960edb1`](https://github.com/shenhao-stu/GAgent/actions/runs/39996863082)
passed both jobs. Downloaded artifact hashes and inventories matched its source
and CI reports. No optional YOLO model, vision adapter or self-ADB was configured.

| Check / 项目 | Observed result / 实际结果 |
| --- | --- |
| Model setup / 模型配置 | Exact model ID saved without model discovery; GLM-5.3-flash, Anthropic protocol, proxy field empty |
| Text request / 文字请求 | Exact requested reply; UI duration 5 seconds |
| Upgrade / 覆盖升级 | Model, conversations and accessibility authorization retained; distinct GAgent OSS label visible |
| Unconfigured mesh / 未配置组网 | Initial startup error reproduced at 4b33fb4; not observed after 960edb1 upgrade |
| Background GUI / 后台 GUI | Settings launch, gestures and visible task overlay observed |
| Original navigation / 原始导航 | Did not reach the display page; stopped after 13 completed steps / 4:49 |
| Guided visual retry / 指引后视觉重试 | Screenshot/OCR with explicit small, slower gestures reached “显示和亮度”; independently checked by screenshot; 9 UI steps / 5:50 |
| Networking / 网络 | No ADB reverse or computer proxy configured; physical USB unplug not tested |

The successful retry used an explicit diagnostic prompt and warm Settings state.
It proves that this route can reach the page, **not fluent default navigation or
benchmark-wide accuracy**. The slower gestures moved through the list in smaller
increments; the earlier failure is retained. System settings were not changed.
Some initial permission state changed between observations, so this is not an
entirely unassisted setup. Microphone access was denied; voice was not tested.

魅族新装已跑通模型配置、文字回复和基本设备控制；保留原闭源版及数据。
原始导航失败，加入截图/OCR和小幅慢滑指引后到达目标，但耗时5分50秒，不能称为流畅。
这是带诊断指引、保留页面状态的重试，不是完整 benchmark。通知与文件权限部分状态可能有
机主协助；未实测物理拔线、语音、折叠屏或横屏。任务运行期间仅用被动截图观察，
UIAutomator 抑制无障碍的干扰另见 [Testing](TESTING.md#passive-observation)。

## Not established / 尚未证明

- Physical foldable behavior, broader OEM coverage, external displays and 16 KB page-size coverage.
- Correct complex filtering or ranking across arbitrary third-party apps.
- Production acceptance of every optional service, microphone path or server deployment.
- Complete native dependency remediation or an independent security audit.
- Equivalent task results with every model, protocol, network or OCR-only installation.

Follow [Testing](TESTING.md) for new evidence and [Roadmap](ROADMAP.md) for the
remaining engineering priorities. Personal device traces and screenshots are not
distributed in this repository.
