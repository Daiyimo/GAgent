"""F2: GUI 结构化动作协议(phone_use)——模型选动作而非写 Python 代码。

真机实证(对比方案): 自由写 Python 的 agent 在游戏段每轮花 1-3 个模型调用在
探索接口(inspect.signature、试参数、写 OpenCV 分析); 结构化动作协议的 agent
31 步几乎无空转。经实测对比选择此方案效果更佳: 9 个动作 + 参数硬校验。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from agent_loop import StepOutcome

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe

ACTIONS = ('tap', 'swipe', 'longpress', 'text', 'key', 'launch', 'back', 'home', 'wait')


def _validate_action(obj):
    """与方案一致的动作校验(镜像自 phone_use 契约)。"""
    if not isinstance(obj, dict):
        raise recipe.RecipeError('action must be object')
    kind = obj.get('action')
    if kind not in ACTIONS:
        raise recipe.RecipeError('unknown action %r' % kind)
    p = obj.get('point')
    if kind in ('tap', 'longpress') and (not p or len(p) != 2):
        raise recipe.RecipeError('%s requires point [x,y]' % kind)
    if kind == 'swipe':
        if not obj.get('point1') or not obj.get('point2'):
            raise recipe.RecipeError('swipe requires point1+point2')
    if kind == 'text' and not obj.get('value'):
        raise recipe.RecipeError('text requires value')
    for k in ('point', 'point1', 'point2'):
        v = obj.get(k)
        if v is not None:
            if len(v) != 2 or not all(isinstance(c, (int, float)) and 0 <= c <= 1000 for c in v):
                raise recipe.RecipeError('%s must be 0-1000 normalized' % k)
    return obj


class StructuredActionTest(unittest.TestCase):
    def test_tap_ok(self):
        self.assertEqual(_validate_action({'action': 'tap', 'point': [500, 500]})['action'], 'tap')

    def test_tap_without_point_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'tap'})

    def test_swipe_requires_two_points(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'swipe', 'point1': [1, 2]})
        _validate_action({'action': 'swipe', 'point1': [1, 2], 'point2': [3, 4], 'ms': 300})

    def test_text_requires_value(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'text'})
        _validate_action({'action': 'text', 'value': '蓝牙'})

    def test_out_of_range_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'tap', 'point': [1200, 500]})

    def test_unknown_action_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'teleport'})

    def test_back_home_wait_need_no_params(self):
        for a in ('back', 'home'):
            _validate_action({'action': a})
        _validate_action({'action': 'wait', 'seconds': 2})


if __name__ == '__main__':
    unittest.main()


class GuiActHandlerTest(unittest.TestCase):
    """do_gui_act 的设备接线(打桩 droid, 不碰真机)。"""
    def setUp(self):
        import ga_android
        self.h = object.__new__(ga_android.GenericAgentHandler)
        self.h.cwd = '.'
        self.h.working = {}
        self.h.history_info = []
        self.h.code_stop_signal = []
        self.h.current_turn = 1
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None

    def _run(self, args):
        ret = self.h.do_gui_act(args, types.SimpleNamespace(content=''))
        if isinstance(ret, StepOutcome):
            return ret
        try:
            next(ret)
        except StopIteration as e:
            return e.value

    def test_tap_normalizes_and_calls_droid(self):
        import ga_android
        calls = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            tap=lambda x, y: calls.append(('tap', x, y)) or {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True, 'waited_s': 0.3, 'uncertain': False})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertEqual(calls, [('tap', 600, 667)])
        self.assertIn('"action": "tap"', str(out.data))

    def test_out_of_range_rejected_before_device_call(self):
        import ga_android
        fake = types.SimpleNamespace(screen=lambda: (1200, 2670))
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [1500, 250]})
        self.assertIn('[Error]', str(out.data))

    def test_text_calls_paste(self):
        calls = []
        fake = types.SimpleNamespace(
            paste=lambda v: calls.append(v) or {'hit': True},
            wait_stable=lambda **kw: {'stable': True, 'waited_s': 0.1})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'text', 'value': '蓝牙'})
        self.assertEqual(calls, ['蓝牙'])

    def test_wait_uses_wait_stable(self):
        fake = types.SimpleNamespace(
            wait_stable=lambda **kw: {'stable': kw.get('max_wait') == 3, 'waited_s': 1.0})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'wait', 'seconds': 3})
        self.assertIn('"stable": true', str(out.data))
