# Model networking / 模型网络

The model and image requests are sent from the phone. USB ADB is only a debugging/control connection; normal usage does not require `adb reverse` or a computer proxy.
模型与图像请求由手机发出。USB ADB只用于调试控制，日常运行不需要 `adb reverse` 或电脑代理。

## Provider proxy / 服务商代理

If your phone VPN excludes GAgent, requests may bypass that VPN even while its icon is visible. Check the VPN app access-control list for the exact installed package: OSS release `io.github.shenhaostu.gagent`, OSS debug `io.github.shenhaostu.gagent.debug`, closed app `com.ljq.ga`. They are different applications.
手机VPN图标亮起不等于GAgent正在使用VPN。访问控制名单按包名生效；开源正式版、调试版和闭源版是三个不同应用，需分别检查。

For a phone-local HTTP proxy, set the chosen provider's advanced **Proxy** field to the listener address shown by your phone VPN application, for example `http://127.0.0.1:7890` if that listener is enabled. This address refers to the phone itself; it must not be an ADB reverse port. Do not copy this example when your phone has no listener at that address. Both text and the Claude/OpenAI vision adapters honor the provider proxy. Leave the field empty when a proxy is unnecessary.
若手机代理工具启用了本地HTTP代理，可将指定服务商的高级「代理」字段设为它显示的监听地址，例如已启用的 `http://127.0.0.1:7890`。这里的localhost是手机，不是电脑；不要填USB反向端口。没有该监听服务时不要照抄示例。文本与Claude/OpenAI视觉适配器使用同一服务商代理；不需要代理则留空。

Keep certificate verification enabled. Test a short text request and an image request separately, then repeat after restarting the app. A successful text response does not prove image transport works. Network failures must be reported separately from task reasoning errors.
保持证书校验；分别测试短文本和图片请求，重启后再测。文本成功不能证明图像请求正常；网络错误与任务推理错误分别记录。

## Existing vision adapter / 已生成的视觉适配器

`memory/vision_api.py` is user-owned and is not overwritten wholesale by an app upgrade. If it was copied from an older template, migrate the Claude request in `_call_claude` to pass `proxies={"http": proxy, "https": proxy}` when `cfg.get("proxy")` is set, matching `memory/vision_api.template.py`. Preserve configuration-key names and user changes; never paste API keys into the adapter.
`memory/vision_api.py` 属于用户配置文件，升级不会整份覆盖。旧模板生成的文件需将 `_call_claude` 的请求更新为遵循 `cfg.get("proxy")`，参照新模板；保留配置变量名与用户修改，不将API密钥复制进适配器。

## Native tool calls / 原生工具调用

For providers that support Anthropic tool calls, use GA's existing native Claude profile. New providers added as Claude in the UI already use this path. A legacy `claude_api_*` configuration uses text-simulated tool calls; a variable containing both `native` and `claude` (for example `claude_native_api_glm`) selects the existing native adapter. Keep the provider display name, model, credentials and proxy unchanged, and update any vision-adapter reference to the renamed configuration. Back up the local configuration first; do not create duplicate providers.
支持Anthropic工具协议的服务商可使用GA已有的原生Claude配置；界面新建Claude服务商默认已走此路径。旧 `claude_api_*` 变量走文本模拟工具；变量名同时含 `native` 与 `claude`（例如 `claude_native_api_glm`）会选择现有原生适配器。迁移前备份本地配置，保留显示名、模型、凭据和代理，同步更新视觉适配器引用，避免重复添加服务商。

GLM-5.3-flash on the Z.ai Anthropic endpoint passed a native tool-call/result round trip and a Pixel route-query task. This removes a text-formatting dependency; it does not establish correct GUI reasoning or sorting. Validate tool execution, image requests and the actual task result separately.
Z.ai的Anthropic端点上，GLM-5.3-flash已通过原生工具调用与结果回传，以及Pixel路线查询。它减少了对文本格式的依赖；GUI理解、排序是否生效仍需独立验证，不能由接口成功推导任务成功。
