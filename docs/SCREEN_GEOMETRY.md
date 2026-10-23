# Screen geometry / 屏幕几何契约

The planner stays independent of device size. Android observation and gesture adapters own physical pixels, rotation and platform APIs; geometry validation and safe swipe margins are pure functions. This change does not alter the GA planning loop.

规划器不依赖机型分辨率；Android观察与手势适配层负责物理像素、旋转和平台API，几何校验与滑动安全边界用纯函数计算。本次不修改GA规划主循环。

| Variable / 变量 | Invariant / 不变量 |
| --- | --- |
| Width, height, rotation / 宽高、旋转 | Coordinates belong to the observed physical display; 0 ≤ x < width, 0 ≤ y < height / 使用当帧物理坐标且不得越界 |
| Orientation or fold resize / 旋转、折叠引起的尺寸变化 | Reject stale geometry before dispatch; observe again instead of scaling old coordinates / 派发前拒绝旧几何，重新观察，不缩放旧坐标猜测 |
| OEM bars, cutouts, keyboard, dialogs, split screens / 厂商栏、刘海、键盘、弹窗、分屏 | Locate the visible target again; matching geometry alone does not prove the same UI / 重新定位可见目标，几何相同不等于页面相同 |
| Detection backend / OCR、YOLO、视觉模型 | Restore any crop/resize transform to full-screen physical pixels / 裁剪或缩放坐标必须还原到整屏像素 |
| Gesture result / 手势返回值 | Accepted dispatch is not task success; verify the resulting state / 派发被接受不等于任务成功，需核验结果 |

```python
frame = droid.capture()
detections = droid.ui_detect(frame['image'])
# Select a target from this frame; do not guess coordinates from an older screen.
# 从当帧检测结果选择目标，不使用历史坐标。
droid.tap(target_x, target_y, screen=frame['screen'])
```

`capture()` checks display metadata before and after the screenshot, including 180° rotation with unchanged width/height. `tap` and `swipe` accept an explicit `screen` and the Android service rechecks geometry before dispatch. Multi-segment `scroll` retains its initial geometry and stops if it changes. Legacy `tap(x, y)` remains supported and validates current bounds, but cannot bind a caller's earlier screenshot automatically.

`capture()`检查截图前后的屏幕元数据，包括宽高不变的180°旋转。`tap`和`swipe`接收显式`screen`，Android服务在派发前再次校验。多段`scroll`沿用最初几何，发生变化即停止。旧`tap(x,y)`仍可用并检查当前边界，但无法自动绑定调用者更早的截图。

This is a geometry guard, not an atomic UI transaction. Content can change without resizing; Android cannot atomically capture and tap. Re-observe after keyboard, dialog, navigation or app changes. The adapter currently targets the default display and screenshot support requires Android API 30+. Physical fold hinges, external displays, different OEM systems and every accessibility implementation require their own device acceptance; synthetic dimension tests do not establish that coverage. Swipe margins are a conservative proportional heuristic, not measured OEM insets.

这是几何防护，不能保证截图与点击原子执行；内容可能在宽高不变时变化。键盘、弹窗、导航或App变化后必须重新观察。当前适配默认显示屏，截图要求Android API30+。真实折叠铰链、外接屏、其他厂商系统与无障碍实现仍需各自实机验收，模拟尺寸测试不能代替；滑动边距是保守比例规则，并非所有系统的实测安全区。

## Floating task status / 任务悬浮窗

Running or waiting tasks restore the status overlay when the Activity moves to the background, provided overlay permission is granted. An explicit “always on” preference takes precedence over an app-specific automatic hide request. When the preference is off, existing visual-only app hide behavior remains. Overlay placement is clamped to the current display after drag, window resize or rotation. These decisions and placement calculations are pure functions; lifecycle callbacks and WindowManager perform the effects.

运行中或等待回复的任务在Activity切后台时恢复状态悬浮窗，前提是已授予悬浮窗权限。用户明确开启“悬浮窗常开”后，该偏好优先于App自动隐藏策略；关闭常开时保留原有特定App自动隐藏行为。拖动、窗口大小或旋转变化后，把手约束在当前显示屏内。显示决策和位置计算使用纯函数，生命周期回调与WindowManager负责副作用。
