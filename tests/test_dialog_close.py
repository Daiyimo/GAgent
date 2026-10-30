"""关一层弹层: 只在弹层范围内找「关闭窗口/取消/×」, 标题带(y<10%)一律不碰。

为什么单独钉住: 真机 2026-10-30 10:06 的三角洲会话里,「今日密码」是 canvas 里的一个小弹窗,
它自己的关闭控件是图标型 ×(OCR 读不出文字)。模型把「关闭窗口」当文字找(target_miss),
退回自己目测的 (906,205) —— 那是小程序标题栏右上角的分享/更多, 一下把分享面板点开,
之后 6 轮都在关分享、找返回。所以: 关弹层不给坐标, 由本地按弹层范围找。
"""
import json
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


def _box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class CloseDialogTest(unittest.TestCase):
    def _run(self, ocr_items, tap_diffs, bbox=None,
             back_diff='diff: 12.000% bbox=(0,0,1200,2670)'):
        calls = {'tap': [], 'back': 0}

        def fake_tap(x, y, **kw):
            calls['tap'].append((x, y))
            d = tap_diffs.pop(0) if len(tap_diffs) > 1 else tap_diffs[0]
            return {'diff': d}

        def fake_back():
            calls['back'] += 1
            return {'diff': back_diff}

        with patch.object(droid, 'shot', lambda *a, **k: IMG), \
             patch.object(droid, 'ocr', lambda img: ocr_items), \
             patch.object(droid, 'tap', fake_tap), \
             patch.object(droid, 'longpress', fake_tap), \
             patch.object(droid, 'back', fake_back):
            res = droid.close_dialog(bbox=bbox)
        return res, calls

    def test_close_window_text_in_the_dialog_is_used(self):
        res, calls = self._run([(_box(880, 380, 990, 430), '关闭窗口', 0.95)],
                               ['diff: 63.400%'])
        self.assertTrue(res['ok'])
        self.assertEqual(res['via'], 'button')
        self.assertEqual(res['text'], '关闭窗口')
        self.assertEqual(calls['tap'], [(935, 405)])
        self.assertEqual(calls['back'], 0)

    def test_title_band_is_never_a_close_control(self):
        # 标题带(y<10% = 267px)的「×」是分享/更多所在的位置, 没有 bbox 时禁止碰
        res, calls = self._run([(_box(900, 180, 960, 240), '×', 0.9)],
                               ['diff: 0.000%'])
        self.assertEqual(calls['tap'], [])            # 一个都不点
        self.assertEqual(calls['back'], 1)            # 退系统返回
        self.assertEqual(res['via'], 'system')

    def test_bbox_limits_the_search_scope(self):
        # 弹层之外的「取消」(底栏) 不是这一层的按钮
        res, calls = self._run([(_box(540, 2420, 660, 2490), '取消', 0.9)],
                               ['diff: 0.000%'], bbox=[80, 320, 1120, 2300])
        self.assertEqual(calls['tap'], [])
        self.assertEqual(calls['back'], 1)

    def test_right_top_corner_inside_the_dialog_is_tried_first(self):
        res, calls = self._run([(_box(200, 1500, 340, 1560), '取消', 0.9),
                                (_box(1020, 380, 1090, 440), '关闭', 0.9)],
                               ['diff: 55.000%'], bbox=[80, 320, 1120, 2300])
        self.assertEqual(calls['tap'], [(1055, 410)])   # 弹层内靠右上角的先试
        self.assertEqual(res['text'], '关闭')

    def test_long_sentence_is_not_a_button(self):
        res, calls = self._run([(_box(200, 1500, 900, 1560),
                                 '关闭窗口后今日密码将不再显示', 0.9)], ['diff: 0.000%'])
        self.assertEqual(calls['tap'], [])
        self.assertTrue(res['hint'])

    def test_falls_back_to_system_back_and_reports_it(self):
        res, calls = self._run([], ['diff: 0.000%'],
                               back_diff='diff: 44.000% bbox=[0,0,1199,2669]')
        self.assertEqual(calls['back'], 1)
        self.assertEqual(res['via'], 'system')
        self.assertTrue(res['ok'])

    def test_first_candidate_that_moves_the_screen_wins(self):
        res, calls = self._run([(_box(1020, 380, 1090, 440), '关闭', 0.9),
                                (_box(200, 1500, 340, 1560), '取消', 0.9)],
                               ['diff: 0.010%', 'diff: 51.000%'], bbox=[80, 320, 1120, 2300])
        self.assertEqual(len(calls['tap']), 2)
        self.assertTrue(res['ok'])
        self.assertEqual(res['text'], '取消')
        self.assertEqual(len(res['tried']), 2)


class ShareTrapUnderGuiActTest(unittest.TestCase):
    """把 10:06 那一步原样重放: target 没命中 + 退回目测坐标落在标题栏右角 → 不许点。"""

    def _handler(self):
        import ga_android
        h = object.__new__(ga_android.GenericAgentHandler)
        h.working = {}
        h.history_info = []
        h.current_turn = 0
        h._gui_actions = 0
        h._task_finished = False
        h._no_tool_retries = 0
        h._vision_in_turn_attached = False
        h._see_cache = None
        h._memory_tip_shown = False
        h._last_bbox = None
        h._done_steps = []
        h._silent_exit_warned = False
        h._goal_text = ''
        h._screen_hist = None
        h.parent = types.SimpleNamespace(verbose=False)
        return h

    def test_guessed_title_bar_point_is_refused(self):
        import types as _types
        from unittest.mock import patch as _patch
        taps = []
        fake = _types.SimpleNamespace(
            find=lambda target, exact=False: [],
            tap=lambda x, y, **kw: (taps.append((x, y)), {'diff': 'diff: 0.000%'})[1],
            swipe=lambda *a, **k: {'diff': 'diff: 0.000%'},
            longpress=lambda *a, **k: {'diff': 'diff: 0.000%'},
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: None,
            wait_stable=lambda **kw: {'stable': True, 'wait_for': 0.0},
            _sensitive_fg=lambda: True,
            observe=lambda **kw: {'kind': 'blanked', 'items': [], 'notes': [],
                                  'needs_vision': True, 'ms': 1.0},
        )
        h = self._handler()
        with _patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'point': [906, 205],
                                'target': '关闭按钮（X）'},
                               _types.SimpleNamespace(content=''))
        self.assertEqual(taps, [])                       # 一下都没点
        self.assertIn('title bar right corner', out.data)
        self.assertIn('close', out.data)                 # 提示改用什么


class ShareTrapTest(unittest.TestCase):
    """target 没命中 + 退回目测坐标 = 最容易点开分享的那条路。"""

    def setUp(self):
        import ga_android
        self.h = ga_android.GenericAgentHandler

    def test_title_band_right_corner_is_a_trap(self):
        with patch.object(droid, 'screen', lambda: (1200, 2670)):
            self.assertTrue(self.h._share_trap(906, 205))
            self.assertTrue(self.h._share_trap(1100, 300))

    def test_real_controls_are_not_trapped(self):
        with patch.object(droid, 'screen', lambda: (1200, 2670)):
            self.assertFalse(self.h._share_trap(600, 900))    # 弹窗中部
            self.assertFalse(self.h._share_trap(80, 205))     # 标题栏左侧(返回)
            self.assertFalse(self.h._share_trap(600, 2450))   # 底栏

    def test_no_screen_geometry_means_no_blocking(self):
        with patch.object(droid, 'screen', side_effect=RuntimeError('bus down')):
            self.assertFalse(self.h._share_trap(906, 205))


class CloseDialogIconTest(unittest.TestCase):
    """canvas 弹窗的关闭键是画出来的叉: OCR 读不到文字, 要认弹层右上方那个图标框。"""

    def _run(self, items, bbox=(0, 0, 1199, 2282), diffs=None):
        taps = []
        seq = diffs or ['diff: 63.000% bbox=[0, 0, 1199, 2669]']

        def fake_tap(x, y, **kw):
            taps.append((x, y))
            return {'diff': seq.pop(0) if len(seq) > 1 else seq[0]}

        with patch.object(droid, 'shot', lambda *a, **k: IMG),              patch.object(droid, 'ocr', lambda img: []),              patch.object(droid, 'look', lambda **kw: items),              patch.object(droid, 'tap', fake_tap),              patch.object(droid, 'longpress', fake_tap),              patch.object(droid, 'back', lambda: {'diff': 'diff: 0.050% bbox=[0, 0, 1199, 2669]'}):
            res = droid.close_dialog(bbox=bbox)
        return res, taps

    def _icon(self, x, y):
        return {'x': x, 'y': y, 'label': 'Icon', 'cls': 'icon', 'bbox': [x - 20, y - 20, x + 20, y + 20]}

    def test_icon_in_the_dialog_right_top_is_tapped(self):
        res, taps = self._run([self._icon(1030, 400)])
        self.assertTrue(res['ok'])
        self.assertEqual(res['via'], 'icon')
        self.assertEqual(taps, [(1030, 400)])

    def test_icon_in_the_title_band_is_never_tapped(self):
        res, taps = self._run([self._icon(1110, 210)])
        self.assertEqual(taps, [])
        self.assertFalse(res['ok'])

    def test_icon_far_left_inside_the_dialog_is_not_a_close_control(self):
        res, taps = self._run([self._icon(120, 400)])
        self.assertEqual(taps, [])

    def test_icon_below_the_dialog_top_half_is_not_a_close_control(self):
        res, taps = self._run([self._icon(1030, 2000)])
        self.assertEqual(taps, [])


class TitleCornerRepeatTest(unittest.TestCase):
    """2026-10-30 10:26 那一轮: 模型把标题栏右角的三个点(分享/更多)当"关闭/退出",
    同一个点 [895,206] 连点 5 次, 每次 diff 都是 85.850%(分享面板开→关→开)。
    第一下可以照着点(也可能是真的「完成/保存」), 但**同一处第二下起**不许再照点。"""

    def _handler(self):
        import ga_android
        h = object.__new__(ga_android.GenericAgentHandler)
        h.working = {}
        h.history_info = []
        h.current_turn = 0
        h._gui_actions = 0
        h._task_finished = False
        h._no_tool_retries = 0
        h._vision_in_turn_attached = False
        h._see_cache = None
        h._memory_tip_shown = False
        h._last_bbox = [0, 0, 1199, 2669]
        h._done_steps = []
        h._silent_exit_warned = False
        h._goal_text = ''
        h._screen_hist = None
        h._trap_seen = []
        h.parent = types.SimpleNamespace(verbose=False)
        return h

    def _fake(self, taps, close_calls):
        def tap(x, y, **kw):
            taps.append((x, y))
            return {'diff': 'diff: 85.850% bbox=[0, 0, 1199, 2669]'}

        def close_dialog(bbox=None):
            close_calls.append(bbox)
            return {'ok': True, 'via': 'button', 'text': '关闭窗口',
                    'point': [1015, 402], 'diff': 'diff: 62.100% bbox=[0, 0, 1199, 2669]'}

        return types.SimpleNamespace(
            find=lambda target, exact=False: [],
            tap=tap, swipe=lambda *a, **k: {'diff': 'diff: 0.000%'},
            longpress=lambda *a, **k: {'diff': 'diff: 0.000%'},
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: None,
            wait_stable=lambda **kw: {'stable': True, 'wait_for': 0.0},
            _sensitive_fg=lambda: True,
            observe=lambda **kw: {'kind': 'blanked', 'items': [], 'notes': [],
                                  'needs_vision': True, 'ms': 1.0},
            close_dialog=close_dialog,
        )

    def test_capsule_tap_with_close_intent_is_redirected_to_close(self):
        taps, closes = [], []
        h = self._handler()
        fake = self._fake(taps, closes)
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'point': [895, 206], 'expect': '关闭今日密码弹窗'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [])                      # 一步都没点胶囊
        self.assertEqual(closes, [[0, 0, 1199, 2669]])   # 改成在弹层范围里找关闭键
        self.assertEqual(data['redirect'], 'title_band_close')
        self.assertTrue(data['ok'])

    def test_capsule_tap_with_exit_intent_uses_the_close_key_only(self):
        taps, closes = [], []
        h = self._handler()
        fake = self._fake(taps, closes)
        exits = []

        def exit_miniapp(**kw):
            exits.append(1)
            return {'ok': True, 'via': 'capsule_close', 'point': [1110, 217],
                    'more': [1000, 215], 'diff': 'diff: 62.000% bbox=[0, 0, 1199, 2669]'}

        fake.exit_miniapp = exit_miniapp
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'point': [1000, 215],
                                'expect': '退出小程序重来'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [])                       # 分享键一步都没点
        self.assertEqual(exits, [1])                     # 改走胶囊右侧那个关闭键
        self.assertEqual(data['redirect'], 'miniapp_capsule_close')
        self.assertEqual(data['point'], [1110, 217])

    def test_capsule_tap_without_close_or_exit_intent_is_allowed_but_explained(self):
        # 微信主界面的放大镜也在标题栏右侧(0.83w): 只凭坐标分不开胶囊和放大镜, 所以按意图拦。
        taps, closes = [], []
        h = self._handler()
        fake = self._fake(taps, closes)
        with patch.dict(sys.modules, {'droid': fake}):
            out = h.do_gui_act({'action': 'tap', 'point': [996, 215], 'expect': '打开搜索框'},
                               types.SimpleNamespace(content=''))
        data = json.loads(out.data)
        self.assertEqual(taps, [(996, 215)])
        self.assertEqual(closes, [])
        self.assertIn('总控胶囊', data['zone_hint'])
        self.assertIn('exit_miniapp', data['zone_hint'])


class CapsuleTest(unittest.TestCase):
    """胶囊 = 小程序右上角并排两个键(左分享/右关闭), 只认 YOLO 在标题带右侧给的图标框。"""

    def _run(self, items, screen=(1200, 2670), tap_diffs=None):
        taps = []
        diffs = tap_diffs or ['diff: 63.000% bbox=[0, 0, 1199, 2669]']

        def fake_tap(x, y, **kw):
            taps.append((x, y))
            return {'diff': diffs.pop(0) if len(diffs) > 1 else diffs[0]}

        with patch.object(droid, 'look', lambda **kw: items),              patch.object(droid, 'ping', lambda: {'w': screen[0], 'h': screen[1]}),              patch.object(droid, 'tap', fake_tap),              patch.object(droid, 'longpress', fake_tap):
            return droid.miniapp_capsule(), taps

    def _icon(self, x, y):
        return {'x': x, 'y': y, 'label': 'Icon', 'cls': 'icon', 'bbox': [x - 20, y - 20, x + 20, y + 20]}

    def test_two_icons_rightmost_is_close(self):
        cap, _ = self._run([self._icon(1000, 215), self._icon(1110, 214)])
        self.assertTrue(cap['found'])
        self.assertEqual(cap['close'], [1110, 214])
        self.assertEqual(cap['more'], [1000, 215])

    def test_single_icon_is_close_and_more_is_unknown(self):
        cap, _ = self._run([self._icon(1110, 214)])
        self.assertEqual(cap['close'], [1110, 214])
        self.assertIsNone(cap['more'])

    def test_icon_outside_the_capsule_zone_is_ignored(self):
        cap, _ = self._run([self._icon(400, 214)])       # 标题带左侧, 不是胶囊
        self.assertFalse(cap['found'])
        self.assertIn('see', cap['hint'])

    def test_icon_below_the_title_band_is_ignored(self):
        cap, _ = self._run([self._icon(1110, 900)])
        self.assertFalse(cap['found'])

    def test_no_icons_at_all_means_not_found(self):
        cap, _ = self._run([])
        self.assertFalse(cap['found'])
        self.assertIsNone(cap['close'])

    def test_exit_miniapp_taps_the_close_key_and_never_the_share_key(self):
        taps = []

        def fake_tap(x, y, **kw):
            taps.append((x, y))
            return {'diff': 'diff: 62.000% bbox=[0, 0, 1199, 2669]'}

        with patch.object(droid, 'look', lambda **kw: [self._icon(1000, 215), self._icon(1110, 214)]),              patch.object(droid, 'ping', lambda: {'w': 1200, 'h': 2670}),              patch.object(droid, 'tap', fake_tap),              patch.object(droid, 'longpress', fake_tap):
            res = droid.exit_miniapp()
        self.assertTrue(res['ok'])
        self.assertEqual(res['via'], 'capsule_close')
        self.assertEqual(taps, [(1110, 214)])

    def test_exit_miniapp_refuses_when_the_capsule_is_not_found(self):
        taps = []
        with patch.object(droid, 'look', lambda **kw: []),              patch.object(droid, 'ping', lambda: {'w': 1200, 'h': 2670}),              patch.object(droid, 'tap', lambda x, y, **kw: taps.append((x, y)) or {'diff': 'x'}):
            res = droid.exit_miniapp()
        self.assertFalse(res['ok'])
        self.assertEqual(taps, [])


class CloseWiringTest(unittest.TestCase):
    def test_gui_act_advertises_and_implements_close(self):
        import ga_android
        self.assertIn('close', ga_android.GenericAgentHandler._GUI_ACTIONS)
        src = (CORE / 'ga_android.py').read_text(encoding='utf-8')
        self.assertIn('droid.close_dialog(', src)
        self.assertIn('_diff_bbox', src)      # 弹层范围来自最近一次画面变化的 bbox

    def test_bbox_is_parsed_from_the_diff_line(self):
        import ga_android
        self.assertEqual(
            ga_android.GenericAgentHandler._diff_bbox(
                {'diff': 'diff: 85.850% bbox=[0, 0, 1199, 2282]'}),
            [0, 0, 1199, 2282])
        self.assertIsNone(ga_android.GenericAgentHandler._diff_bbox({'diff': 'n/a'}))


if __name__ == '__main__':
    unittest.main()
