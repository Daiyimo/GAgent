# GAgent

[English](README.md) · [架构与不变量](docs/ARCHITECTURE.md) · [构建说明](docs/BUILD.md)

GAgent 把 Python 智能体运行在 Android 手机上：规划任务、调用工具、读屏操作应用、
浏览网页、管理文件，并保存本地记忆。模型服务商、接口和密钥由用户自己配置。

本版整合原 Android beta 的 2.33.0 / 133 与原 main 较新的 PC Link 修复，
以 2.33.1 / 134 建立全新的仓库历史；当前 2.33.3 / 136 包含微信纯 GUI、
GLM 工具解析与视觉响应修复。仓库何时公开，由仓库所有者决定。

## 保留的能力

- Kotlin 原生壳、Chaquopy 内嵌 CPython、Python 智能体内核和中英文 WebUI。
- 无障碍操作、截图、带校验的应用导航、可选无线 ADB 与浏览器工具。
- 多服务商配置、明确的模型选择、会话隔离、流式输出与本地记忆。
- 本地 PaddleOCR。旧版含 AGPL 声明的 YOLO 权重不随仓库分发；OCR 和无障碍识别保留。
- PC Link、GAnet 配对、流式语音与 APK 构建客户端，通过显式配置连接兼容的可选组件。

已剥离套餐、订单支付、积分、强制托管账号、托管遥测、提问上传、服务密钥注入与源码加密。
商业后端、生产部署脚本、账号资料和旧仓库历史不属于本仓库。

[功能去留清单](docs/FEATURE_SCOPE.md)逐项区分保留能力、已剥离流程、未纳入的服务端实现和待验收事项。

## 开始使用

1. 自行构建 APK，或在仓库 Releases 提供后下载安装包。
2. 设备要求：**Android 7.0 / API 24 及以上，arm64-v8a**；截图能力取决于系统版本和授权。
3. 在「设置 → 服务商与模型」填写服务商 URL、API Key 和模型。
4. 根据需要授予无障碍、截图、悬浮窗、麦克风和文件等权限。
5. 可选能力在「设置 → 可选组件」配置。客户端要求兼容服务已经可用，不会自动部署服务端。

正式版应用 ID 为 `io.github.shenhaostu.gagent`，调试版增加 `.debug`。
这是独立安装，签名和数据目录均与旧应用分离，不会静默迁移密钥、账号或会话。
调试版与正式版也各自保存数据；迁移时只导出自己确实需要的内容。

密钥保存在应用私有存储，调用时用于向你选择的服务商认证。任务文本、截图和必要工具结果
可能随模型请求发送。应用不自动上传遥测或提问。智能体生成的代码和设备操作具有真实副作用，
运行权限来自你的授权；本应用并不是隔离沙箱。

## 开发

[构建说明](docs/BUILD.md)列出固定工具链、本地命令和 CI。新仓库 `main` 构建调试版及正式版；
编译不需要模型密钥、商业服务凭据或源码加密密钥。贡献者可以构建未签名正式包，
维护者签名私钥放在 Git 之外。

```bash
python -m pip install -r requirements-test.txt
python -m playwright install chromium
python tools/audit_source.py
python -m pytest -q
bash tools/build_tsbridge.sh
python tools/build_pure_wheels.py
gradle :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease
```

修改前请阅读[贡献说明](CONTRIBUTING.md)、[代码审查记录](docs/REVIEW.md)和
[安全说明](SECURITY.md)。变量、不变量和副作用边界在[架构文档](docs/ARCHITECTURE.md)中说明。

## 许可证与来源

主代码采用 [Apache-2.0](LICENSE)。本项目源自 Liang Jiaqing 及贡献者的 GenericAgent / GAndroid，
保留原作者署名。第三方库、模型与字体沿用各自许可证，详见 [NOTICE](NOTICE) 与
[第三方清单](THIRD_PARTY.md)。

iOS 与 ESP32 的开发继续留在原工作目录，本次 Android 分发不包含它们。

[官方组件与密钥边界方案](docs/OFFICIAL_MODULES.md)

[公开前的依赖安全审查](docs/DEPENDENCY_SECURITY.md)

可选 YOLO 按钮/图标检测支持用户自行下载、核验和安装，详见 [安装与许可说明](docs/OPTIONAL_YOLO.md)。默认包保留 OCR。

[手机模型接口与代理排障](docs/NETWORK.md)
