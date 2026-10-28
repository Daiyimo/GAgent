# -*- coding: utf-8 -*-
"""YOLO 失败一律降级, 绝不外抛。

回归来源(真机 2026-10-28 10:22 那次 22 分钟的任务): 用户导入的 YOLO 模型在
user_models/, 而 detector_models.model_path() 做了 Path.resolve() —— Android 上
/data/user/0 是指向 /data/data 的符号链接, 路径因此落进 PC 映射分支被改成
models/ui_detect_v1/models/<name>, Kotlin 报 model not found。异常穿透
_yolo → detect → droid.look() → 整轮作废。

同一份代码里"没有注册表"时反而会静默降级成纯 OCR(if not os.path.isfile: return []),
即两种缺失状态行为相反。本组用例锁住统一后的降级契约。
"""
import sys
import unittest
from pathlib import Path

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
BUNDLE = CORE / 'models' / 'ui_detect_v1'
sys.path.insert(0, str(BUNDLE))
import ui_detect_lite


def _img():
    return np.zeros((64, 64, 3), dtype=np.uint8)


def _no_ocr(monkeypatch):
    monkeypatch.setattr(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([])))


class TestYoloDegrade(unittest.TestCase):
    def setUp(self):
        ui_detect_lite.LAST_YOLO_ERROR = None

    def test_registry_points_at_missing_file_degrades_to_ocr(self):
        import unittest.mock as mock
        import detector_models
        with mock.patch.object(detector_models, 'model_path',
                               side_effect=ValueError('Installed detector is missing or invalid')):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
        self.assertEqual(out, [])
        self.assertTrue(ui_detect_lite.LAST_YOLO_ERROR)
        self.assertIn('ValueError', ui_detect_lite.LAST_YOLO_ERROR)

    def test_onnx_session_failure_degrades(self):
        import unittest.mock as mock
        # 本机没有 YOLO 权重(.gitignore 排除), 先让 isfile 放行才能走到 _session 分支
        with mock.patch.object(ui_detect_lite.os.path, 'isfile', lambda p: True), \
             mock.patch.object(ui_detect_lite, '_session',
                               side_effect=RuntimeError('model not found: /data/x.onnx')):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
        self.assertEqual(out, [])
        self.assertIn('model not found', ui_detect_lite.LAST_YOLO_ERROR)

    def test_inference_failure_degrades(self):
        import unittest.mock as mock

        class _Boom:
            def run(self, *a, **k):
                raise RuntimeError('ORT: invalid tensor')

            def get_inputs(self):
                return [type('I', (), {'name': 'images'})()]

        with mock.patch.object(ui_detect_lite.os.path, 'isfile', lambda p: True), \
             mock.patch.object(ui_detect_lite, '_session', lambda p: _Boom()):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                out = ui_detect_lite.detect(_img(), yolo=True)      # 不得抛
        self.assertEqual(out, [])
        self.assertIn('invalid tensor', ui_detect_lite.LAST_YOLO_ERROR)

    def test_last_error_cleared_on_success(self):
        import unittest.mock as mock
        ui_detect_lite.LAST_YOLO_ERROR = 'stale from a previous call'
        with mock.patch.object(ui_detect_lite, '_yolo', lambda img, conf: ([], None)):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                ui_detect_lite.detect(_img(), yolo=True)
        self.assertIsNone(ui_detect_lite.LAST_YOLO_ERROR)

    def test_ocr_only_path_reports_no_yolo_error(self):
        import unittest.mock as mock
        with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
            ui_detect_lite.detect(_img(), yolo=False)
        self.assertIsNone(ui_detect_lite.LAST_YOLO_ERROR)

    def test_failed_session_is_not_cached(self):
        """失败会话不进 _SESSIONS: 否则下次 detect 直接拿坏会话, 连原因都读不到。"""
        import unittest.mock as mock
        ui_detect_lite._SESSIONS.clear()
        with mock.patch.object(ui_detect_lite, '_session',
                               side_effect=RuntimeError('model not found: /x')):
            with mock.patch.object(ui_detect_lite, '_ocr_engine', lambda: (lambda img: iter([]))):
                ui_detect_lite.detect(_img(), yolo=True)
        self.assertEqual(ui_detect_lite._SESSIONS, {})


if __name__ == '__main__':
    unittest.main()
