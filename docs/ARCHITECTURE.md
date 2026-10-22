# Architecture / 架构

The framework has four boundaries: the WebUI describes intent; Kotlin grants
device capabilities; Python owns agent sessions and tools; optional service
adapters speak public protocols. Server business logic is a separate deployment.

框架分为四个边界：WebUI 表达用户意图，Kotlin 提供设备能力，Python 管理会话和
工具，可选客户端通过公开协议连接服务。服务端业务实现独立部署。

| Boundary | Responsibility | Invariant |
| --- | --- | --- |
| `provider_config.py` | Pure parsing and transformation | Caller input and unrelated provider blocks are preserved |
| `service_config.py` | Pure endpoint validation plus explicit atomic persistence | Unconfigured modules make no service request; changing a URL cannot retain its old token |
| `android_entry.py` | Command dispatch and per-conversation lifecycle | Unknown bridge commands never become model prompts; retired sessions reject work |
| `kernel_adapter/patches.py` | Thread/session association | Usage and output belong to their initiating session |
| `bus_auth.py` / `LocalBusAuth.kt` | Local device capability | Only the exact loopback origin receives the random capability |
| `VoiceClient.kt` | Streaming speech transport | TLS validation stays enabled; connection generations cannot publish stale results |
| `pclink.py` / `ganet.py` | Pairing and remote device transport | Explicit endpoints, pinned peer identities, no embedded service authority |

Variable inputs are provider URLs, models, user tokens, chosen tools and service
configuration. Invariants are origin binding, session ownership, authentication,
atomic persistence and explicit enablement. Separate these in code and tests.

变化点为模型、服务地址、用户令牌、工具和组件配置；不变量为来源绑定、会话归属、
鉴权、原子保存和主动启用。解析与校验优先使用纯函数，I/O 集中在边界。

The inherited runtime and WebUI still contain large modules. This release extracts
provider transformations and integration policy rather than claiming a complete
rewrite. Future extraction should follow behavior boundaries with regression
coverage, not create one wrapper per function.
