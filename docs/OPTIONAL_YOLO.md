# 可选 Android UI 检测模型 / Optional Android UI detector

默认 APK 只包含 PaddleOCR；YOLO 不自动下载。YOLO 能为无文字图标、输入框和弹窗补充候选框，但不能保证每个按钮都识别正确，操作后仍需观察确认。

The default APK includes PaddleOCR and does not download YOLO automatically. The optional detector adds boxes for icons, inputs and dialogs; verify the resulting screen after every action.

## 来源与许可 / Source and licensing

- 模型 / Model: [yasirfaizahmed/android_ui_detection_yolov8](https://huggingface.co/yasirfaizahmed/android_ui_detection_yolov8), YOLOv8 Nano, 21 Android UI classes.
- 固定来源版本 / Pinned source revision: `f692e68a3d7c92d51b5e94bba2fc13196a280e18`.
- 模型卡标注 Apache-2.0；旧 ONNX 导出元数据标注 Ultralytics / AGPL-3.0。此差异尚未由权利方澄清。GAgent 框架的 Apache-2.0 不会覆盖第三方模型；使用、修改和再分发须遵守适用模型条款，商业授权须另行取得，不能把本说明视作已取得授权。
- The model card says Apache-2.0, while the previous ONNX export embeds Ultralytics / AGPL-3.0 metadata. These conflicting notices remain unresolved. The framework license does not relicense model weights; obtain the applicable rights separately before redistribution.
- [Ultralytics licensing](https://www.ultralytics.com/license), [ONNX export documentation](https://docs.ultralytics.com/modes/export/).

## 自行下载、导出 / Download and export yourself

在独立桌面 Python 环境安装你已接受条款的 Ultralytics 导出工具，下载固定版本的 [best.pt](https://huggingface.co/yasirfaizahmed/android_ui_detection_yolov8/resolve/f692e68a3d7c92d51b5e94bba2fc13196a280e18/best.pt)。不要把 `.pt` 直接放进 APK。

In an isolated desktop Python environment, obtain the export tools under their applicable terms and download the pinned `best.pt` above. The APK requires ONNX, not PyTorch weights.

```python
from ultralytics import YOLO
YOLO("best.pt").export(format="onnx", imgsz=640, dynamic=True,
                       nms=True, opset=19, half=False, simplify=True)
```

输出契约必须是 float32 RGB `[1,3,H,W]`，输出 `[1,300,6]`，每行 `x1,y1,x2,y2,confidence,class_id`，包含 NMS，21 类顺序见 `ui_detect_lite.NAMES`。不同导出器版本可能产生不兼容图；先验证，不直接替换线上模型。上述命令是复现配方，本次并未重新运行桌面导出。

Required contract: float32 RGB `[1,3,H,W]`, NMS output `[1,300,6]` with `x1,y1,x2,y2,confidence,class_id`, and the 21 classes in `ui_detect_lite.NAMES` order. Exporter versions may differ; validate compatibility first. The recipe was not re-exported in this release.

## 安装到自己的手机 / Install on your phone

将兼容的 ONNX 重命名为 `ui_detect_yolo.onnx`，记录其 SHA-256，并通过 USB/系统文件选择放到手机 Download 目录。让 GAgent 在本机执行以下代码（把摘要替换为你实际核验的值），或 debug 安装使用 `adb shell run-as` 写入相同私有路径。无需官方账号、订阅或密钥。

Rename a compatible ONNX file to `ui_detect_yolo.onnx`, record its SHA-256, and transfer it to Downloads. With file access granted, run the following inside your own GAgent. No official account, subscription, or key is required.

```python
from pathlib import Path
import hashlib, shutil, droid
src = Path('/sdcard/Download/ui_detect_yolo.onnx')
expected = 'REPLACE_WITH_YOUR_VERIFIED_SHA256'
assert hashlib.sha256(src.read_bytes()).hexdigest() == expected
out = Path(droid.BUNDLE) / 'models/ui_detect_yolo.onnx'
shutil.copyfile(src, out)
print({'installed': out.exists(), 'bytes': out.stat().st_size})
```

重启 GAgent 后运行 `print(droid.look(cache=False))`。`droid.ping()['loaded']` 应包含 `ui_detect_yolo.onnx`，检测项应有 `Icon`/`TextButton` 等类别。不要仅凭文件存在宣称模型工作。

Restart GAgent, then run `print(droid.look(cache=False))`. Confirm the detector appears in `droid.ping()['loaded']` and that actual predictions contain UI classes such as `Icon` or `TextButton`.

删除这个可选文件并重启即可退回 OCR。模型安装仅作用于 App 私有数据，不会加入 Git 源码历史或默认发布包。
Delete the optional file and restart to return to OCR. Device installation does not add the model to Git history or default release artifacts.
