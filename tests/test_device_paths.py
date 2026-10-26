"""设备路径解析修复（2026-10-26 实证）。

根因：`GA_PACKAGE` 全仓只有 Python 读、无人设置（Kotlin/gradle 均无）——debug 包里它取默认值
`io.github.shenhaostu.gagent`（正式包名），`_remote_model_path` 又把调用方传来的设备绝对路径
扔掉目录、用默认包名重建 → App 内 ONNX 模型全部 "model not found"，本地视觉(YOLO+OCR)整条链
死在 debug 包（16MB PP-OCR 成死重），视觉任务只能退云端 ask_vision（实测单次 17.7s）。
同一缺陷还让 `_SELF_PKG` 指向正式包名，debug 包把自身当前台（launch 后 ping 异常的历史根因）。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid


class RemoteModelPathTest(unittest.TestCase):
    def test_device_absolute_path_passes_through(self):
        # App 内 ppocr_engine/detector_models 传的就是设备绝对路径——包名在路径里, 禁重建
        p = "/data/user/0/io.github.shenhaostu.gagent.debug/files/ga/models/ui_detect_v1/models/ch_PP-OCRv4_det_infer.onnx"
        self.assertEqual(droid._remote_model_path(p), p)

    def test_user_models_path_passes_through(self):
        # 用户经设置导入的检测器在 user_models/——旧实现只留 basename 会指错目录
        p = "/data/user/0/io.github.shenhaostu.gagent.debug/files/ga/user_models/my_detector.onnx"
        self.assertEqual(droid._remote_model_path(p), p)

    def test_backslash_device_path_normalized(self):
        p = "\\data\\user\\0\\io.github.shenhaostu.gagent.debug\\files\\ga\\models\\ui_detect_v1\\models\\x.onnx"
        self.assertEqual(droid._remote_model_path(p), p.replace("\\", "/"))

    def test_pc_path_reconstructed_from_ga_package(self):
        # PC 侧调试: 路径是仓库路径, 按 GA_PACKAGE 重建成设备路径(保持旧行为)
        with patch.object(droid.os, 'environ', {'GA_PACKAGE': 'io.github.shenhaostu.gagent.debug'}):
            out = droid._remote_model_path("E:/repo/gacore/models/ui_detect_v1/models/x.onnx")
        self.assertEqual(out, "/data/user/0/io.github.shenhaostu.gagent.debug/files/ga/models/ui_detect_v1/models/x.onnx")

    def test_empty_path_still_rejected(self):
        with self.assertRaises(ValueError):
            droid._remote_model_path("")


class SelfPackageTest(unittest.TestCase):
    def test_debug_package_derived_from_module_dir(self):
        with patch.object(droid, '_DIR', "/data/user/0/io.github.shenhaostu.gagent.debug/files/ga"):
            self.assertEqual(droid._self_package(), "io.github.shenhaostu.gagent.debug")

    def test_release_package_derived_from_module_dir(self):
        with patch.object(droid, '_DIR', "/data/user/0/io.github.shenhaostu.gagent/files/ga"):
            self.assertEqual(droid._self_package(), "io.github.shenhaostu.gagent")

    def test_pc_side_falls_back_to_env(self):
        with patch.object(droid, '_DIR', "E:/repo/gacore"), \
             patch.object(droid.os, 'environ', {'GA_PACKAGE': 'io.github.shenhaostu.gagent.debug'}):
            self.assertEqual(droid._self_package(), "io.github.shenhaostu.gagent.debug")


if __name__ == "__main__":
    unittest.main()
