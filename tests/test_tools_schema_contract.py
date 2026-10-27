"""tools_schema 的 gui_act 与实现的一致性(评审实证的三类静默漂移)。

漂移都不报错, 只会让动作静默失效:
① schema 的 enum 宣传了 droid 侧没有的动作(曾: longpress → do_gui_act 抛 AttributeError,
   被宽 except 吞成 [Error] gui_act failed, 整轮作废);
② schema 描述教的参数名与实现读的不一致(曾: key {name:ENTER} 而实现读 args['value'],
   只因默认值恰为 ENTER 才看起来正常; text {value, point?} 而 point 被完全忽略);
③ 描述把 code_run 限成"仅多步逻辑或非 GUI 工作", 与 dump()/look()/ask_vision()/
   recipe_list() 只能经 code_run 调用相冲——观察屏幕被排除在唯一可行通道之外。
"""
import json
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))


class GuiActSchemaContractTest(unittest.TestCase):
    """tools_schema 的 gui_act 与实现的一致性。"""

    ACTIONS_NEEDING_DROID_FN = {
        'tap': 'tap', 'longpress': 'longpress', 'swipe': 'swipe', 'text': 'paste',
        'key': 'key', 'launch': 'launch', 'back': 'back', 'home': 'home',
        'wait': 'wait_stable',
    }

    def _schema(self, name):
        path = CORE / 'assets' / name
        for tool in json.loads(path.read_text(encoding='utf-8')):
            if tool.get('function', {}).get('name') == 'gui_act':
                return tool['function']
        raise AssertionError('gui_act not found in %s' % name)

    def test_every_advertised_action_has_a_droid_implementation(self):
        import droid
        fn = self._schema('tools_schema.json')
        for action in fn['parameters']['properties']['action']['enum']:
            self.assertIn(action, self.ACTIONS_NEEDING_DROID_FN, action)
            self.assertTrue(callable(getattr(droid, self.ACTIONS_NEEDING_DROID_FN[action], None)),
                            'gui_act 宣传了 %r 但 droid 侧没有实现' % action)

    def test_handler_accepts_exactly_the_advertised_actions(self):
        import ga_android
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            enum = set(self._schema(name)['parameters']['properties']['action']['enum'])
            self.assertEqual(enum, set(ga_android.GenericAgentHandler._GUI_ACTIONS), name)

    def test_both_language_schemas_agree_on_the_action_set(self):
        a = self._schema('tools_schema.json')['parameters']['properties']['action']['enum']
        b = self._schema('tools_schema_cn.json')['parameters']['properties']['action']['enum']
        self.assertEqual(a, b)

    def test_description_teaches_the_parameter_names_the_code_reads(self):
        # 实现读 args['value']; 描述教 name=/point? 会被静默忽略
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self.assertNotIn('name:ENTER', desc, name)
            self.assertNotIn('point?', desc, name)
            self.assertIn('key {value:ENTER}', desc, name)

    def test_description_states_the_pixel_to_normalized_conversion(self):
        """回归(真机实证): 145 个 tool_result 里 7 次整个轮次废在
        'point must be 0-1000 normalized, got [752, 2512]' 上, 占全部错误一半。
        根因是原描述说 point 取自 "dump bounds or look() box"——那两处给的是**像素**,
        与同段的 0-1000 要求自相矛盾, 模型照做就必错。描述必须把换算讲明白。"""
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self.assertIn('PIXELS', desc, name)
            self.assertIn('convert first', desc, name)
            # 换算公式要在, 否则模型仍不知道拿 screen() 除
            self.assertIn('1000/screen_w', desc.replace(' ', ''), name)

    def test_description_does_not_forbid_observing_the_screen(self):
        # 观察(dump/look)只有 code_run 一条路; 曾把"非 GUI 工作"当成唯一许可, 自相矛盾
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self.assertIn('code_run', desc, name)
            self.assertNotIn('only for multi-step logic or non-GUI work', desc, name)


if __name__ == '__main__':
    unittest.main()
