"""P1: canvas 页面视觉调用加速（通用机制 1+6，不针对具体 App）。

真机实证（羊了个羊 652s）：游戏段每步 1-2 次 ask_vision，全屏 320 万像素 + 长 prompt，
单次 25-50s；vision 超时后还拖垮 a11y。通用修法：
- roi（0-1000 归一化）裁剪后只送局部——像素量降 3-6 倍；
- 单次超时上限 30s（原 60s，超时一次烧一分钟）；
- 连续失败熔断：静默期内直接拒，不再反复烧超时。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid

IMG = np.zeros((2670, 1200, 3), dtype=np.uint8)


def _fake_vision(result="ok"):
    calls = []

    def invoke(image_input, prompt="", **kw):
        calls.append({"image": image_input, "prompt": prompt, "kw": kw})
        if isinstance(result, Exception):
            raise result
        return result
    invoke.calls = calls
    return invoke


class VisionRoiTest(unittest.TestCase):
    def setUp(self):
        droid._VISION_FAILS.update({"n": 0, "until": 0.0})
        self.addCleanup(lambda: droid._VISION_FAILS.update({"n": 0, "until": 0.0}))

    def _patch_vision(self, result="ok"):
        invoke = _fake_vision(result)
        mod = types.ModuleType("vision_api")
        mod.ask_vision = invoke
        patches = [patch.dict(sys.modules, {"vision_api": mod})]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        return invoke

    def test_roi_crops_before_send(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "棋盘", roi=[250, 200, 750, 550])
        img = invoke.calls[0]["image"]
        self.assertEqual(img.shape, (2670 * 35 // 100, 1200 * 50 // 100, 3))

    def test_no_roi_sends_full(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "全局")
        self.assertEqual(invoke.calls[0]["image"].shape, IMG.shape)

    def test_path_input_ignores_roi(self):
        invoke = self._patch_vision()
        droid.ask_vision("/sdcard/x.png", "棋盘", roi=[0, 0, 500, 500])
        self.assertEqual(invoke.calls[0]["image"], "/sdcard/x.png")

    def test_timeout_default_is_capped(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "x")
        self.assertEqual(invoke.calls[0]["kw"]["timeout"], 30)

    def test_caller_can_raise_timeout(self):
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "x", timeout=90)
        self.assertEqual(invoke.calls[0]["kw"]["timeout"], 90)


class VisionCircuitBreakerTest(unittest.TestCase):
    def setUp(self):
        droid._VISION_FAILS.update({"n": 0, "until": 0.0})
        self.addCleanup(lambda: droid._VISION_FAILS.update({"n": 0, "until": 0.0}))

    def _patch_vision(self, result):
        invoke = _fake_vision(result)
        mod = types.ModuleType("vision_api")
        mod.ask_vision = invoke
        p = patch.dict(sys.modules, {"vision_api": mod})
        p.start(); self.addCleanup(p.stop)
        return invoke

    def test_two_failures_open_breaker(self):
        invoke = self._patch_vision(TimeoutError("read timeout"))
        for _ in range(2):
            with self.assertRaises(TimeoutError):
                droid.ask_vision(IMG, "x")
        self.assertEqual(len(invoke.calls), 2)
        with self.assertRaises(RuntimeError) as ctx:
            droid.ask_vision(IMG, "x")
        self.assertIn("熔断", str(ctx.exception))
        self.assertEqual(len(invoke.calls), 2)          # 熔断后不再调用

    def test_error_string_counts_as_failure_but_is_returned(self):
        invoke = self._patch_vision("Error: upstream 503")
        out = droid.ask_vision(IMG, "x")
        self.assertTrue(out.startswith("Error:"))       # 可见失败原样回传
        self.assertEqual(droid._VISION_FAILS["n"], 1)   # 但计入熔断

    def test_success_resets_counter(self):
        self._patch_vision("Error: 503")
        droid.ask_vision(IMG, "x")                      # 可见失败: 原样返回但计入
        self.assertEqual(droid._VISION_FAILS["n"], 1)
        self._patch_vision("好的")
        droid.ask_vision(IMG, "x")
        self.assertEqual(droid._VISION_FAILS["n"], 0)

    def test_cooldown_expiry_closes_breaker(self):
        invoke = self._patch_vision(TimeoutError("t"))
        for _ in range(2):
            with self.assertRaises(TimeoutError):
                droid.ask_vision(IMG, "x")
        with patch.object(droid.time, "time", return_value=time_time() + 9999):
            with self.assertRaises(TimeoutError):
                droid.ask_vision(IMG, "x")              # 静默期已过: 放行重试
        self.assertEqual(len(invoke.calls), 3)


def time_time():
    import time
    return time.time()


if __name__ == "__main__":
    unittest.main()
