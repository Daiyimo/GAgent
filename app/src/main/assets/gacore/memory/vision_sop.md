# Vision SOP (Android端)

## 前置规则
1. **能不用 vision 就不用**：droid.dump()(a11y树) / droid.ui_detect()(检测框+OCR) 能解决就不调 vision API。Vision 是最后手段(看图答疑/验证上屏/OCR搞不定的版式)。
2. 截图用 `droid.shot()`(返回BGR ndarray, 直接传给ask_vision) 或 `droid.shot(path)`。

## 用法
```python
from vision_api import ask_vision
ask_vision(droid.shot(), '描述当前界面')  # 返回str; 失败为 'Error: ...'
```

## 没有 memory/vision_api.py 时(初次自建)
按 `memory/vision_api.template.py` 头部三步说明操作：复制为 vision_api.py → 扫 mykey 配置变量名(禁止输出key值)填头部 → 小图实测。
