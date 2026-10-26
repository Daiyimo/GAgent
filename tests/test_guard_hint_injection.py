"""turn_end_callback 的循环守卫注入（SPEC 赋能 W3c 提示级）。

契约：anchor prompt 每轮带上 [LOOP-GUARD] 文案（仅在有信号时）；
无信号零注入（不浪费 token、不改变既有 [DANGER] 行为）。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import ga_android
import phone_ledger


def _handler():
    h = object.__new__(ga_android.GenericAgentHandler)
    h.history_info = []
    h.working = {}
    h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
    h.current_turn = 3
    return h


def _seed_repetition():
    phone_ledger.ACTIVE.clear()
    for _ in range(5):
        phone_ledger.ACTIVE.append(phone_ledger.ActionRecord(
            kind="tap", point=(500, 1000), screen=(1200, 2670),
            outcome={"verdict": "settled", "screenshot_exactly_same": True, "diff_pct": 0.0}))


class GuardHintInjectionTest(unittest.TestCase):
    def setUp(self):
        phone_ledger.ACTIVE.clear()
        self.addCleanup(phone_ledger.ACTIVE.clear)

    def _run(self, turn=3):
        h = _handler()
        response = types.SimpleNamespace(content="<summary>读取前三项</summary>")
        return h.turn_end_callback(response, [{"tool_name": "no_tool", "args": {}}], [],
                                   turn, "BASE_PROMPT", {})

    def test_no_signal_no_injection(self):
        out = self._run()
        self.assertNotIn("[LOOP-GUARD]", out)
        self.assertIn("BASE_PROMPT", out)

    def test_repetition_signal_injects_guard_block(self):
        _seed_repetition()
        out = self._run()
        self.assertIn("[LOOP-GUARD]", out)
        self.assertIn("没有产生可观察效果", out)

    def test_existing_danger_behavior_unchanged(self):
        out = self._run(turn=7)
        self.assertIn("[DANGER]", out)          # 既有轮数告警不受影响


if __name__ == "__main__":
    unittest.main()
