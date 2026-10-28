# -*- coding: utf-8 -*-
"""pytest 全局夹具。

phone_ledger.ACTIVE 是进程级单例(droid 执行边界落账/守卫 与 ga_android 每轮提示注入共用),
必须跨用例重置: 否则动作账本在用例间累积, 会触发循环守卫并改变既有行为测试的预期(SPEC W3)。
本夹具对 tests/ 与 apk_factory/tests/ 全部用例生效(根目录 conftest)。
"""
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parent / "app" / "src" / "main" / "assets" / "gacore"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


@pytest.fixture(autouse=True)
def _reset_module_state():
    """重置 gacore 的模块级可变状态, 防止跨用例泄漏:
    phone_ledger.ACTIVE(守卫账本) / droid._TRACE+_LAST_OBS(录制痕跡) / droid._VISION_FAILS(视觉熔断) /
    droid._OBS_CACHE(观测缓存) / ui_detect_lite.LAST_YOLO_ERROR(YOLO 降级原因)。

    后两者是本轮新引入的: LAST_YOLO_ERROR 一旦被某个降级用例设上且不清, 之后任何
    observe() 都会读到陈旧原因 → 静默剥掉 YOLO 项。按文件名字母序它恰好跑在后面,
    换并行执行或改个文件名就会炸, 所以在这里显式清。"""
    import phone_ledger
    import droid
    phone_ledger.ACTIVE.clear()
    droid._TRACE.clear()
    droid._LAST_OBS = None
    droid._VISION_FAILS.update({"n": 0, "until": 0.0})
    droid._OBS_CACHE.update(thumb=None, roi=None, pkg=None, rot=None, res=None)
    try:
        from models.ui_detect_v1 import ui_detect_lite
        ui_detect_lite.LAST_YOLO_ERROR = None
    except Exception:
        pass
    yield
    phone_ledger.ACTIVE.clear()
    droid._TRACE.clear()
    droid._LAST_OBS = None
    droid._VISION_FAILS.update({"n": 0, "until": 0.0})
    droid._OBS_CACHE.update(thumb=None, roi=None, pkg=None, rot=None, res=None)
    try:
        from models.ui_detect_v1 import ui_detect_lite
        ui_detect_lite.LAST_YOLO_ERROR = None
    except Exception:
        pass
