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


def _boom_module():
    mod = types.ModuleType("vision_api")

    def _raise(*a, **k):
        raise RuntimeError('视觉不可用')
    mod.ask_vision = _raise
    return mod


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

    def test_band_names_crop_to_the_measured_system_ui(self):
        """roi='title' 必须裁到 geom 实测的标题行(1200x2670 上 y 146..320),
        且与 look(roi='title') 裁的是同一块——否则"OCR 在标题行没看到图标, 用
        ask_vision 看同一块"就落空, 模型得重新描述位置。"""
        import geom
        invoke = self._patch_vision()
        droid.ask_vision(IMG, "放大镜在哪", roi='title')
        img = invoke.calls[0]["image"]
        x1, y1, x2, y2 = geom.band('title', 1200, 2670)
        # _crop_roi 按 0-1000 比例切, 与 geom.band 的像素值有 1px 取舍差
        self.assertLessEqual(abs(img.shape[0] - (y2 - y1)), 2)
        self.assertLessEqual(abs(img.shape[1] - (x2 - x1)), 2)
        self.assertLess(img.shape[0], IMG.shape[0] * 0.2)      # 裁到 <20% 高度才叫"快"

    def test_unknown_roi_name_lists_the_available_bands(self):
        with self.assertRaises(ValueError) as cm:
            droid.ask_vision(IMG, "x", roi='nope')
        for name in ('title', 'status', 'navbar', 'top'):
            self.assertIn(name, str(cm.exception))

    def test_look_and_ask_vision_agree_on_the_same_band(self):
        import geom
        from_vision = droid._resolve_roi('title')
        from_look = tuple(int(round(v * geom.NORM)) for v in droid._ROI_NAMES['title'])
        self.assertEqual(from_vision, from_look)
        self.assertEqual(from_vision, geom.band_norm('title'))

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


class StabilityWaitTest(unittest.TestCase):
    """F1: 动作后等页面稳定再决策(替代固定 sleep)。

真机实证(对比方案): 固定 action_sleep=5 让 30 步白睡 150s; 而"立刻决策"在
加载页上会点到未完成的界面。本方案: diff 持续 >阈值=还在动, 等到稳定或超时。
经实测对比选择此方案效果更佳: 阈值 1.5%(与 scroll verdict 一致)、
轮询 250ms、上限 3s——静态页几乎不花时间, 加载页不抢跑。
"""
    def setUp(self):
        droid._VISION_FAILS.update({"n": 0, "until": 0.0})
        self.addCleanup(lambda: droid._VISION_FAILS.update({"n": 0, "until": 0.0}))

    def test_static_page_returns_immediately(self):
        calls = {'n': 0}
        def shot():
            calls['n'] += 1
            return np.full((100, 100, 3), 128, dtype=np.uint8)
        with patch.object(droid, 'shot', side_effect=shot), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable()
        self.assertTrue(r['stable'])
        self.assertEqual(calls['n'], 2)          # 首帧 + 一次确认
        self.assertLessEqual(r['waited_s'], 0.5)

    def test_animating_page_waits_until_timeout(self):
        frames = [np.full((100, 100, 3), v, dtype=np.uint8) for v in range(0, 255, 25)]
        box = {'it': iter(frames)}
        def shot():
            # 无限交替: 永不用尽(用尽后帧相同会被判 stable, 那不是被测行为)
            try: return next(box['it'])
            except StopIteration:
                box['it'] = iter(frames); return next(box['it'])
        with patch.object(droid, 'shot', side_effect=shot), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable(max_wait=1.0, poll=0.25)
        self.assertFalse(r['stable'])
        self.assertGreaterEqual(r['waited_s'], 1.0)

    def test_change_then_stable_returns_stable(self):
        seq = [np.full((100, 100, 3), 0, dtype=np.uint8),
               np.full((100, 100, 3), 255, dtype=np.uint8),
               np.full((100, 100, 3), 255, dtype=np.uint8)]
        it = iter(seq)
        def shot():
            try: return next(it)
            except StopIteration: return seq[-1]
        with patch.object(droid, 'shot', side_effect=shot), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable(max_wait=3.0, poll=0.25)
        self.assertTrue(r['stable'])

    def test_shot_failure_degrades_to_stable(self):
        # 截图失败不阻塞: 当作"无法判定", 返回 stable=True 让上层继续(uncertain 由上层判)
        with patch.object(droid, 'shot', side_effect=RuntimeError('secure')), \
             patch.object(droid.time, 'sleep'):
            r = droid.wait_stable()
        self.assertTrue(r['stable'])
        self.assertTrue(r.get('uncertain'))


class VisionFuseResetTest(unittest.TestCase):
    """回归: 熔断是跨任务存活的进程级状态。上个任务早期连撞两次失败(最常见成因=任务页
    选中的模型不支持图片, 2.4s就连错两次)会让新任务在整个游戏阶段——唯一需要视觉
    grounding 的阶段——连续 120s 拿不到任何观察。任务边界必须清零。"""

    def setUp(self):
        droid._VISION_FAILS.update({"n": 0, "until": 0.0})
        self.addCleanup(lambda: droid._VISION_FAILS.update({"n": 0, "until": 0.0}))

    def _fail_vision(self):
        """让真实 ask_vision 走一遍失败分支(计数在它内部), 不打桩 ask_vision 本身。"""
        class _Ctx:
            def __enter__(self):
                self.a = patch.dict(sys.modules, {"vision_api": _boom_module()}); self.a.start()
                self.b = patch.object(droid, 'shot', lambda *a, **k: IMG); self.b.start()
                return self

            def __exit__(self, *exc):
                self.b.stop(); self.a.stop()
        return _Ctx()

    def test_two_failures_open_the_fuse(self):
        with self._fail_vision():
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    droid.ask_point('放大镜')
        self.assertGreaterEqual(droid._VISION_FAILS['n'], 2)
        self.assertGreater(droid._VISION_FAILS['until'], 0)
        # 熔断期内 ask_point 直接拒, 不再烧超时
        with self._fail_vision():
            with self.assertRaises(RuntimeError) as cm:
                droid.ask_point('放大镜')
        self.assertIn('熔断', str(cm.exception))

    def test_reset_clears_both_counter_and_window(self):
        droid._VISION_FAILS.update({"n": 2, "until": __import__('time').time() + 120})
        droid.reset_vision_fuse()
        self.assertEqual(droid._VISION_FAILS, {"n": 0, "until": 0.0})
