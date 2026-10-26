"""droid 执行边界的循环守卫（SPEC 赋能 W3b）：落账 + 恢复/拒绝。

契约：
- 只有带证据的动作才落账（verify=True 的 tap/swipe、scroll 聚合、paste 验证后）；
  verify=False 无证据不落账——守卫只判断已证明的事实（SPEC 铁律）。
- 恢复级在 tap 内把动作换成 WAIT→BACK→HOME（有界），拒绝级直接不下发；
  两者都如实结算（恢复后重新截图算 diff），屏幕一变等价尾即断。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid
import phone_ledger


def _settled(kind="tap", point=(500, 1000), point2=(), value="", exact=True, pct=0.0):
    return phone_ledger.ActionRecord(
        kind=kind, point=point, point2=point2, value=value, screen=(1200, 2670),
        outcome={"verdict": "settled", "screenshot_exactly_same": exact, "diff_pct": pct})


class _BusCase(unittest.TestCase):
    diff = "0.000% changed"

    def setUp(self):
        droid._LEDGER = phone_ledger.Ledger()
        self.acts = []
        patches = [
            patch.object(droid, 'ping', return_value={"w": 1200, "h": 2670, "rot": 0, "pkg": "com.android.settings"}),
            patch.object(droid, 'shot', return_value=np.zeros((2670, 1200, 3), dtype=np.uint8)),
            patch.object(droid, '_fg', return_value="com.android.settings"),
            patch.object(droid, '_track'),
            patch.object(droid.time, 'sleep'),
            patch.object(droid, '_img_diff_str', lambda a, b: self.diff),
            patch.object(droid, '_act', side_effect=lambda **kw: self.acts.append(kw) or {}),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def seed(self, records):
        for r in records:
            droid._LEDGER.append(r)


class TapLedgerTest(_BusCase):
    def test_tap_records_settled_with_exact_evidence(self):
        droid.tap(500, 1000)
        r = droid._LEDGER.recent()[-1]
        self.assertEqual((r.kind, r.point), ("tap", (500, 1000)))
        self.assertEqual(r.outcome["verdict"], "settled")
        self.assertTrue(r.outcome["screenshot_exactly_same"])

    def test_tap_with_visible_change_records_diff(self):
        self.diff = "5.000% changed"
        droid.tap(500, 1000)
        r = droid._LEDGER.recent()[-1]
        self.assertFalse(r.outcome["screenshot_exactly_same"])
        self.assertEqual(r.outcome["diff_pct"], 5.0)

    def test_unverified_tap_is_not_recorded(self):
        droid.tap(500, 1000, verify=False)
        self.assertEqual(droid._LEDGER.recent(), [])

    def test_third_equivalent_no_effect_tap_is_replaced_by_wait(self):
        self.seed([_settled(), _settled()])
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "WAIT")
        self.assertNotIn("tap", [a.get("op") for a in self.acts])
        r = droid._LEDGER.recent()[-1]
        self.assertEqual(r.outcome.get("recovery"), "WAIT")

    def test_fourth_equivalent_no_effect_tap_escalates_to_back(self):
        waited = phone_ledger.ActionRecord(
            kind="tap", point=(500, 1000), screen=(1200, 2670),
            outcome={"verdict": "recovered", "recovery": "WAIT",
                     "screenshot_exactly_same": True, "diff_pct": 0.0})
        self.seed([_settled(), _settled(), waited])
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "BACK")
        self.assertIn("back", [a.get("op") for a in self.acts])

    def test_fifth_equivalent_no_effect_tap_escalates_to_home(self):
        # tap 有恢复阶梯: 第 5 次等价点击=HOME 改写(拒绝级是无阶梯种类如 swipe 的兜底)
        self.seed([_settled() for _ in range(4)])
        ret = droid.tap(500, 1000)
        self.assertEqual(ret.get("recovered"), "HOME")
        self.assertIn("home", [a.get("op") for a in self.acts])

    def test_sixth_equivalent_no_effect_tap_aborts_bounded(self):
        self.seed([_settled() for _ in range(5)])
        ret = droid.tap(500, 1000)
        self.assertTrue(ret.get("aborted"))
        self.assertEqual(self.acts, [])
        self.assertEqual(droid._LEDGER.recent()[-1].outcome["verdict"], "aborted")

    def test_productive_tap_breaks_the_ladder(self):
        self.seed([_settled(), _settled(), _settled(exact=False, pct=8.0)])
        ret = droid.tap(500, 1000)
        self.assertNotIn("recovered", ret)
        self.assertNotIn("rejected", ret)
        self.assertIn("tap", [a.get("op") for a in self.acts])

    def test_recovery_returns_hint_telling_model_to_reobserve(self):
        self.seed([_settled(), _settled()])
        ret = droid.tap(500, 1000)
        self.assertIn("重新观察", ret.get("hint", ""))


class SwipeLedgerTest(_BusCase):
    def test_swipe_records_both_endpoints(self):
        droid.swipe(600, 2000, 600, 800)
        r = droid._LEDGER.recent()[-1]
        self.assertEqual((r.kind, r.point, r.point2), ("swipe", (600, 2000), (600, 800)))

    def test_swipe_has_no_recovery_ladder_but_rejects_on_fifth(self):
        self.seed([_settled(kind="swipe", point=(600, 2000), point2=(600, 800)) for _ in range(4)])
        ret = droid.swipe(600, 2000, 600, 800)
        self.assertEqual(ret.get("rejected"), "repeated_no_effect")
        self.assertEqual(self.acts, [])

    def test_swipe_recovery_not_substituted(self):
        self.seed([_settled(kind="swipe", point=(600, 2000), point2=(600, 800)) for _ in range(3)])
        ret = droid.swipe(600, 2000, 600, 800)
        self.assertNotIn("recovered", ret)
        self.assertIn("swipe", [a.get("op") for a in self.acts])

    def test_uncertain_swipe_recorded_as_uncertain(self):
        with patch.object(droid, '_shape_changed', return_value=True):
            droid.swipe(600, 2000, 600, 800)
        self.assertEqual(droid._LEDGER.recent()[-1].outcome["verdict"], "uncertain")


class LedgerResetTest(unittest.TestCase):
    def test_clear_empties_records(self):
        led = phone_ledger.Ledger()
        led.append(_settled())
        led.clear()
        self.assertEqual(led.recent(), [])


if __name__ == "__main__":
    unittest.main()
