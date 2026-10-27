"""F2: GUI 结构化动作协议(phone_use)——模型选动作而非写 Python 代码。

真机实证(对比方案): 自由写 Python 的 agent 在游戏段每轮花 1-3 个模型调用在
探索接口(inspect.signature、试参数、写 OpenCV 分析); 结构化动作协议的 agent
31 步几乎无空转。经实测对比选择此方案效果更佳: 9 个动作 + 参数硬校验。
"""
import json
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


class NormPtTest(unittest.TestCase):
    """gui_act 坐标换算: 必须同时吃得下归一化值和 dump/look 的像素值。

    真机实证: 145 个 tool_result 里 7 次整个轮次废在
    'point must be 0-1000 normalized, got [752, 2512]' 上——占全部错误的一半,
    是最大的单一失败源。schema 让模型"point 取自 dump bounds 或 look() box",
    而那两处给的是像素, 于是照做就必错。"""

    def _norm(self, v):
        import ga_android
        h = object.__new__(ga_android.GenericAgentHandler)
        fake = types.SimpleNamespace(screen=lambda: (1200, 2670))
        with patch.dict(sys.modules, {'droid': fake}):
            return h._norm_pt(v)

    def test_normalized_coords_scale_to_pixels(self):
        self.assertEqual(self._norm([500, 250]), (600, 667))
        self.assertEqual(self._norm([0, 0]), (0, 0))
        self.assertEqual(self._norm([1000, 1000]), (1200, 2670))

    def test_pixel_coords_over_1000_pass_through(self):
        # >1000 不可能是归一化值(上限就是 1000), 所以只可能是像素, 无歧义
        self.assertEqual(self._norm([752, 2512]), (752, 2512))
        self.assertEqual(self._norm([1085, 210]), (1085, 210))
        self.assertEqual(self._norm([417, 1700]), (417, 1700))

    def test_mixed_pair_takes_the_pixel_reading(self):
        # 一个超限一个没超: 按像素解释整对(真机出现的 [1085, 210] 形态)
        self.assertEqual(self._norm([1085, 210]), (1085, 210))

    def test_real_device_failures_now_resolve(self):
        """回归: 这 6 个值是真机上让整个轮次作废的实参。"""
        for bad in ([752, 2512], [1085, 210], [500, 1500], [417, 1700],
                    [191, 1049], [500, 1800]):
            x, y = self._norm(bad)
            self.assertGreater(x, 0)
            self.assertGreater(y, 0)

    def test_negative_and_garbage_still_rejected_with_screen_size(self):
        for bad in ([-5, 100], [100, -5]):
            with self.assertRaises(ValueError) as cm:
                self._norm(bad)
            self.assertIn('1200x2670', str(cm.exception))    # 报错要能自解释
        for bad in (['a', 'b'], [None, 5], 'nope', [1, 2, 3]):
            with self.assertRaises(ValueError):
                self._norm(bad)


class ActProvedChangeTest(unittest.TestCase):
    """_act_proved_change: 决定 gui_act 要不要再付一次 wait_stable。

    判错的代价是双向的——把"没变化"判成变了会漏等加载页(点到未完成的界面),
    把"变了"判成没变会让动画/canvas 页每步白睡满 max_wait。
    """
    def setUp(self):
        import ga_android
        self.f = ga_android.GenericAgentHandler._act_proved_change

    def test_big_diff_skips_the_extra_wait(self):
        self.assertTrue(self.f('tap', {'diff': 'diff: 12.5% bbox=[1,2,3,4]'}))

    def test_small_diff_still_waits(self):
        # 页面几乎没变(可能在加载): 必须等, 否则下一步点到未完成的界面
        self.assertFalse(self.f('tap', {'diff': 'diff: 0.02% bbox=[1,2,3,4]'}))
        self.assertFalse(self.f('swipe', {'diff': 'diff: n/a'}))

    def test_foreground_pkg_alone_is_not_evidence_of_change(self):
        # 回归: tap()/swipe() 恒设 fg=当前前台包名。拿它当变化证据会让 tap 永远跳过等待。
        self.assertFalse(self.f('tap', {'diff': 'diff: 0.01%', 'fg': 'com.example.app'}))
        self.assertFalse(self.f('swipe', {'fg': 'com.example.app'}))

    def test_launch_foreground_is_evidence(self):
        self.assertTrue(self.f('launch', {'fg': 'com.example.app'}))

    def test_paste_hit_is_evidence(self):
        self.assertTrue(self.f('text', {'hit': True}))
        self.assertFalse(self.f('text', {'hit': False, 'uncertain': True}))

    def test_no_verdict_keys_means_wait(self):
        for act in ('back', 'home', 'key'):
            self.assertFalse(self.f(act, {'action': act}))


class GuiActSkipsRedundantWaitTest(unittest.TestCase):
    """动作自带后验已证明页面变化时, gui_act 不得再调 wait_stable(每步白睡 3s)。"""
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

    def test_tap_with_real_change_skips_wait_stable(self):
        waited = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: 42.0%'},
            wait_stable=lambda **kw: waited.append(kw) or {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertEqual(waited, [])
        self.assertNotIn('stable', str(out.data))

    def test_tap_without_change_still_waits(self):
        waited = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: 0.01%'},
            wait_stable=lambda **kw: waited.append(kw) or {'stable': True, 'uncertain': False})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertEqual(len(waited), 1)
        self.assertIn('"stable": true', str(out.data))

    def test_tap_forwards_verdict_fields(self):
        # 坐标失效/点到非热区/验证不可用在模型眼里要能区分, 不能只给一个 diff
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: n/a', 'verified': False, 'uncertain': True,
                              'hint': '屏幕尺寸变化；重新截图定位，不复用旧坐标。', 'fg': 'com.a'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        data = str(out.data)
        self.assertIn('"uncertain": true', data)
        self.assertIn('重新截图定位', data)

    def test_longpress_is_dispatched_to_droid(self):
        calls = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            longpress=lambda x, y, ms: calls.append((x, y, ms)) or {'diff': 'diff: 3.0%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'longpress', 'point': [500, 250], 'ms': 900})
        self.assertEqual(calls, [(600, 667, 900)])
        self.assertNotIn('[Error]', str(out.data))

    def test_point_actions_observe_before_acting(self):
        # 预观测是 recipe locator 的唯一来源: 不喂它, gui_act 录出的配方 locator 全是 any。
        # 走 ensure_fresh_obs 而不是裸 dump: 模型刚 dump()/look() 过时观测仍有效, 不再重复取。
        obs = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: obs.append(1) or {'nodes': []},
            tap=lambda x, y: {'diff': 'diff: 0.01%'},
            swipe=lambda *a, **k: {'diff': 'diff: 0.01%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'tap', 'point': [500, 250]})
            self._run({'action': 'swipe', 'point1': [500, 800], 'point2': [500, 200]})
        self.assertEqual(len(obs), 2)

    def test_point_actions_fall_back_to_dump_when_helper_missing(self):
        # 兼容: 打桩只提供 dump(旧行为)时也不能炸, 更不能不观测
        dumps = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: dumps.append(1) or [],
            tap=lambda x, y: {'diff': 'diff: 0.01%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertNotIn('[Error]', str(out.data))

    def test_non_point_actions_do_not_pay_for_an_observation(self):
        obs = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: obs.append(1) or {'nodes': []},
            back=lambda: None, home=lambda: None,
            key=lambda name: None, wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'back'})
            self._run({'action': 'home'})
            self._run({'action': 'key', 'value': 'ENTER'})
        self.assertEqual(obs, [])      # back/home/key 没有可定位的目标


NODES = [
    {'t': '搜索', 'cls': 'EditText', 'x': 645, 'y': 598, 'b': '182,527,1109,670'},
    {'t': '取消', 'cls': 'TextButton', 'x': 100, 'y': 200},
    {'t': '', 'cls': 'Image', 'x': 300, 'y': 300},          # 无文字 → 应被丢掉
    {'label': '发送', 'cls': 'TextButton', 'bbox': [900, 2400, 1100, 2500]},  # look() 形态
    {'t': 'x' * 80, 'cls': 'Text', 'x': 10, 'y': 20},        # 超长标签 → 应截断
]


class PostActionObsTest(unittest.TestCase):
    """gui_act 结果必须带动作后的紧凑观测, 否则每个动作都要多花一整轮去观察。

    真机实证: 39 轮任务里约 20 轮是纯观察(code_run + dump/look); 供应商 p50 延迟
    5~10s 的现状下, 省一轮就是省 5~10s。"""

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

    def _run(self, args, nodes=NODES, dets=None):
        import ga_android
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: list(nodes),
            look=lambda *a, **k: list(dets or []),
            tap=lambda x, y: {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            ret = self.h.do_gui_act(args, types.SimpleNamespace(content=''))
            if isinstance(ret, StepOutcome):
                return ret
            try:
                next(ret)
            except StopIteration as e:
                return e.value

    def test_tap_result_carries_obs(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        self.assertIn('obs', out)
        self.assertTrue(out['obs'])
        first = out['obs'][0]
        self.assertEqual((first['t'], first['cls'], first['x'], first['y']),
                         ('搜索', 'EditText', 645, 598))

    def test_obs_drops_textless_items_and_truncates_labels(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        labels = [i['t'] for i in out['obs']]
        self.assertNotIn('', labels)                    # 无文字项丢掉
        self.assertTrue(all(len(l) <= 24 for l in labels))
        self.assertIn('发送', labels)                    # look() 形态(bbox)也收

    def test_obs_is_capped(self):
        many = [{'t': 'item%d' % i, 'x': i, 'y': i} for i in range(40)]
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}, nodes=many).data)
        self.assertEqual(len(out['obs']), 12)

    def test_empty_tree_falls_back_to_look(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]},
                                   nodes=[], dets=[{'label': '确定', 'x': 600, 'y': 1200}]).data)
        self.assertEqual([i['t'] for i in out['obs']], ['确定'])

    def test_both_channels_empty_yields_empty_obs(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]},
                                   nodes=[], dets=[]).data)
        self.assertEqual(out['obs'], [])          # 不炸, 模型照旧走 code_run 观察

    def test_obs_does_not_pollute_the_verdict(self):
        """指标口径不能被观测字段污染: extract_verdict 只认白名单键。"""
        import run_metrics
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        v = run_metrics.extract_verdict(json.dumps(out, ensure_ascii=False))
        self.assertNotIn('obs', v)
        self.assertEqual(set(v), {'diff_pct'})
        self.assertEqual(v['diff_pct'], 8.0)

    def test_obs_survives_a_failing_observation(self):
        """观测取不到不能把动作结果一起毁掉; 键仍在但为空, 模型知道要另行观察。"""
        import ga_android
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: (_ for _ in ()).throw(RuntimeError('bus down')),
            look=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('bus down')),
            tap=lambda x, y: {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            ret = self.h.do_gui_act({'action': 'tap', 'point': [500, 250]},
                                    types.SimpleNamespace(content=''))
            out = json.loads(ret.data)
        self.assertEqual(out['diff'], 'diff: 8.0%')     # 动作结果完好
        self.assertEqual(out['obs'], [])                # 观测缺失给空列表, 不给假数据
