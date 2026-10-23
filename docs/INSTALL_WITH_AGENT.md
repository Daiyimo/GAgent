# Install with your agent / 让 Agent 帮你安装

For **GenericAgent, Codex and Claude Code**, or a human following the same steps.
[Manual installation / 手动安装](GETTING_STARTED.md) · [Build](BUILD.md) · [Troubleshooting](TROUBLESHOOTING.md)

Give your agent the prompt from the [English](../README.md#start) or
[Chinese README](../README.zh-CN.md#start). This guide is a setup procedure, not
permission to alter unrelated applications, accounts or services. Follow the
user's chosen device and scope, and the agent's own execution/approval rules.

把 README 中的提示词交给你的 Agent 即可。下文按「识别环境 → 最小依赖 → 安装 → 配置 → 验收」执行；
只在必要信息确实缺失时询问。它不授权修改无关应用、账号或服务器。

## 1. Choose the smallest installation path / 先选最短路径

Inspect OS, CPU, available tools and any existing GAgent install. Do not assume
`brew`, `apt`, `winget`, `sudo`, an Android SDK or a logged-in GitHub session exists.
Prefer the **APK path** unless the user requests source changes or builds.

| Path / 路径 | Required on the host / 电脑所需 | Not needed / 不需要 |
| --- | --- | --- |
| Phone-only / 仅手机 | Nothing; download/extract with the phone browser and Files app / 无，用手机浏览器与文件应用 | ADB, Python, Java, Gradle, Go |
| Agent-assisted APK / Agent 辅助安装 | Browser or authenticated `gh`; optional Android **platform-tools** for ADB installation / 浏览器或已登录的 gh，选择 ADB 安装才需 platform-tools | Full Android SDK/NDK, Java, Gradle, Go |
| Source build / 源码构建 | The pinned toolchain in [Build](BUILD.md) and the checked-out workflow / 构建文档与所选提交的 CI 工具链 | Model keys or optional-service credentials for compilation / 编译无需模型与组件密钥 |

Reuse installed tools. If a tool is missing, explain what it enables and install
only that dependency within the user's authorization, using its official source
and a project-local environment where possible. Do not pipe remote scripts into
a shell, replace global language runtimes, or enable all optional modules.
For a phone-only user, guide the taps instead of building a desktop environment.

复用已装工具；缺什么只补什么，并说明用途。不要为安装 APK 建一整套开发环境，也不要替换全局运行时。
首次登录 GitHub、手机授权或系统信任确认由用户完成；登录失败不等于下载成功。

<a id="artifact"></a>
## 2. Select and verify an APK / 选择与校验制品

Canonical source: [shenhao-stu/GAgent](https://github.com/shenhao-stu/GAgent).
Use **main**, the **Android** workflow (`android.yml`) and a run where **both jobs
completed successfully**. Pin its full commit before downloading. If current main
is still running or failed, report that; do not call an older successful build
“latest main”. Artifacts expire after 14 days; fall back to an explicitly selected
verified commit or source build, not an arbitrary mirror.

Commands below use **placeholders** `RUN_ID` and `COMMIT`. Replace them with values
inspected from GitHub. The examples use POSIX line continuations; in PowerShell,
put each `gh` command on one line. Do not print auth tokens or provider keys.

```sh
gh auth status
gh api repos/shenhao-stu/GAgent/commits/main --jq .sha
gh run list --repo shenhao-stu/GAgent --workflow android.yml --branch main \
  --event push --limit 5 --json databaseId,headSha,status,conclusion
gh run view RUN_ID --repo shenhao-stu/GAgent \
  --json headSha,headBranch,status,conclusion,jobs
gh run download RUN_ID --repo shenhao-stu/GAgent \
  --name GAgent-android-COMMIT --dir gagent-download
```

If `gh` is unavailable, the browser path in [Get started](GETTING_STARTED.md#download)
works without installing it. GitHub requires sign-in to download Actions artifacts.
Use an empty download directory; do not merge files from different runs.

下载前核对完整提交、分支与两个 job 的结果，使用空目录，避免混入不同构建的文件。
浏览器下载和 `gh` 二选一，不必同时配置；制品下载需登录 GitHub。

Inside the extracted directory, compare `SOURCE_COMMIT` with the chosen commit
and verify **every APK** in `SHA256SUMS`:

```sh
# Linux
sha256sum -c SHA256SUMS
# macOS — use this instead of the Linux command
shasum -a 256 -c SHA256SUMS
```

On Windows PowerShell, use `Get-Content SOURCE_COMMIT`, `Get-Content SHA256SUMS`
and `Get-FileHash .\GAgent-release.apk -Algorithm SHA256`; compare the result with
that file's entry, and repeat for any other APK. A mismatch stops installation.
If Android build-tools are already installed, independently verify a signed APK:

```sh
apksigner verify --verbose --print-certs GAgent-release.apk
```

`SIGNATURES.txt` contains CI's verification; it does not replace a local signature
check. Compare signer identities before upgrading an installed variant. An
unsigned release needs the user's own signing setup from [Build](BUILD.md); never
silently sign it with a new identity over an existing installation.

SHA-256 校验不通过就停止；首次安装核实仓库来源，更新还须核对签名连续性。
CI 的 `SIGNATURES.txt` 是构建记录，不冒充本地签名验证结果。

## 3. Install without replacing user data / 保留数据安装

For a phone-only path, follow [Files-app installation](GETTING_STARTED.md#download).
For an already authorized ADB device, inspect first:

```sh
adb devices -l
adb -s DEVICE_SERIAL shell getprop ro.build.version.sdk
adb -s DEVICE_SERIAL shell getprop ro.product.cpu.abilist
adb -s DEVICE_SERIAL shell pm list packages io.github.shenhaostu.gagent
adb -s DEVICE_SERIAL install -r gagent-download/GAgent-release.apk
```

Replace `DEVICE_SERIAL` with the **selected** device; if several devices are
attached, ask which one. `unauthorized` needs the owner's phone confirmation;
`offline` is not connected. Require API 30+ and arm64-v8a for the documented GUI
path. Also check the old app's package identity if the user wants to preserve it.
Do not run uninstall, `pm clear`, downgrade flags or permission-grant commands to
make installation “succeed”. On a conflict, report the exact category, preserve
the old install and obtain a compatible build or a deliberate migration plan.

多台设备必须确认目标；USB「未授权」由本人在手机上确认。仅安装所选变体，不卸载旧版、不清数据、
不强行降级、不顺手授予所有权限。安装成功后从手机图标打开，核对显示版本与安装身份。

## 4. Configure on the phone / 在手机上配置

Follow [provider fields](GETTING_STARTED.md) and [permissions](GETTING_STARTED.md#permissions).
Collect only protocol, URL and model ID in chat; let the user enter the key locally,
or use an explicitly authorized local secret source without printing it. A key is
not a prerequisite for downloading or building the APK.

**Do not require model discovery.** A known model ID can be saved directly in
**Default model ID**. `/models` failure does not prove generation fails. Test a
short request, then tool execution. Keep Proxy empty unless the phone needs a
reachable proxy; do not create a persistent USB reverse tunnel as normal setup.

只询问协议、URL、模型名等非敏感信息，密钥在手机本地填写。已知模型名可直接保存；
列表接口失败不应卡住配置。不要用电脑代理或 USB 转发掩盖手机自身的连通性问题。

For vision, paste the [vision setup prompt](CONFIGURATION.md#models) into GAgent
after text/tool use works. The phone agent can create `memory/vision_api.py` from
the bundled template. Use the **mykey configuration variable name**, not the
provider's display label or literal key. Confirm the referenced provider accepts
images and the template's protocol (OpenAI uses Chat Completions). If no such
provider is configured, explain that missing prerequisite; do not invent one.
Preserve and back up existing user adapters before adapting their URL handling.

看图适配器由手机内的 Agent 按模板生成，引用 `mykey` 的配置变量名，不是界面显示名或密钥。
没有支持图片的模型就说明缺项；已有用户适配器先备份。YOLO 是可选增强，不是首次配置的前置依赖。

## 5. Demonstrate completion / 给出可复核结果

Run the five checks in [First-run acceptance](GETTING_STARTED.md#acceptance): text,
harmless tool action, synthetic-image vision, background overlay/stop, independent
phone networking. Ask before an additional chargeable or account-changing action
if not already within the user's scope. Leave orders, login, messages and payments
out of a basic install test. Physical USB unplug is only passed after observation.

Observe running tasks with passive `adb screencap` / read-only `dumpsys`, not
UIAutomator-based `inspect` or `uiautomator dump`: their default automation session
can suppress GAgent's accessibility service. Stop the task first, or use an
observer that preserves other services from its first connection.
[Observation requirements](TESTING.md#passive-observation).

任务运行中只用被动截图和只读状态检查，不要同时运行 UIAutomator 的 `inspect` 或 `dump`。
其默认连接会抑制 GAgent 无障碍；先停任务，或确保观察器从首次连接起就保留其他服务，避免误报故障。

交付时记录：提交和 CI、APK 摘要与签名验证来源、包名、设备/Android/方向、各项通过或未测、
下一步最小修复。未连接设备就明确只完成了下载与静态检查，不宣称安装或使用通过。

## If the user chooses a source build / 如果选择源码构建

Clone the repository into a new user-approved directory, pin the selected commit,
read its `AGENTS.md`, [Build](BUILD.md), [Testing](TESTING.md) and
[workflow](../.github/workflows/android.yml). The tested CI host is **Ubuntu 24.04**.
For macOS, adapt paths/tool discovery; for Windows, a user-approved WSL2 Linux
build environment is a practical path. Neither is a claim that every local host
combination has been validated.

Build pins and commands come from that commit, not remembered “latest” versions.
There is **no Gradle wrapper**: use the documented Gradle installation. Build the
mesh AAR and portable wheels before Gradle. Use a Python virtual environment;
prefer an existing compatible browser for UI tests. Run the source audit and tests,
then assemble/sign as documented. Do not disable TLS verification, skip dependency
security gates or copy a maintainer's signing secrets to resolve build failures.

源码构建以所选提交的 CI 为准；Windows/WSL 与 macOS 适配不能写成已完成的跨平台实测。
先生成 AAR 与 wheels，再运行 Gradle。依赖错误按责任层修复，不关闭 TLS、不跳安全检查，
不读取或复制维护者私钥。构建通过后仍须完成手机端验收。

## System labels / 系统名称

Choose **GAgent OSS** for the release APK and **GAgent OSS Debug** for the debug APK
in the launcher, app permissions and accessibility list. The package IDs remain
`io.github.shenhaostu.gagent` and `io.github.shenhaostu.gagent.debug`; existing data
and signing requirements are unchanged. On Flyme, follow the additional
[accessibility navigation](GETTING_STARTED.md#permissions). Do not enable a different
installation just because its name is similar.

启动器及系统权限中，正式变体显示 **GAgent OSS**，调试变体显示 **GAgent OSS Debug**。
包名不变；保留原有闭源版本，不替它修改权限。Flyme 的额外入口见安装指南。

When installations coexist, check the owner of each visible overlay before
diagnosing duplicate windows. Each package can run its own floating service.
Use one controller for acceptance; within the user's authorized scope, turn off
the unused app's **Always-on floating window** setting. Preserve its data and
permissions. Verify only the selected controller's overlay remains after Home,
during a task and after completion.

并装时先核对每个悬浮窗所属包名：两版各显示一个，与同一服务重复创建窗口是不同故障。
验收只运行一个控制器；在用户授权范围内关闭闲置版本的「悬浮窗常开」，保留数据和权限。
回桌面、任务运行中和完成后，分别确认只剩当前测试版本的悬浮窗。
