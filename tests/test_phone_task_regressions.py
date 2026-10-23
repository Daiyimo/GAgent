"""Regressions reproduced with GLM and the Android GUI task budget."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid
from llmcore import ToolClient


class ToolArgumentsTest(unittest.TestCase):
    def parse(self, value):
        client = object.__new__(ToolClient)
        return client._parse_mixed_response('<tool_use>' + json.dumps(value) + '</tool_use>')

    def test_glm_flat_file_read_retains_path(self):
        result = self.parse({'name': 'file_read', 'path': 'memory/phone_use.md', 'start': 1})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments),
                         {'path': 'memory/phone_use.md', 'start': 1})

    def test_flat_code_run_retains_execution_type(self):
        result = self.parse({'name': 'code_run', 'type': 'python', 'timeout': 20})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments),
                         {'type': 'python', 'timeout': 20})

    def test_explicit_empty_arguments_do_not_absorb_metadata(self):
        result = self.parse({'name': 'no_arg_tool', 'arguments': {}, 'path': 'ignored'})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments), {})

    def test_nested_arguments_remain_authoritative(self):
        result = self.parse({'name': 'file_read', 'arguments': {'path': 'correct'}, 'path': 'ignored'})
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments), {'path': 'correct'})

    def test_glm_multiple_fenced_open_tags_keep_all_calls(self):
        client = object.__new__(ToolClient)
        result = client._parse_mixed_response(
            '```<tool_use>\n{"name":"file_read","path":"one"}\n```\n'
            '```<tool_use>\n{"name":"file_read","path":"two"}\n```')
        self.assertEqual([json.loads(t.function.arguments)['path'] for t in result.tool_calls], ['one', 'two'])

    def test_fence_inside_script_does_not_end_tool_json(self):
        client = object.__new__(ToolClient)
        value = {'name': 'code_run', 'script': "print('```')"}
        result = client._parse_mixed_response('```<tool_use>\n' + json.dumps(value) + '\n```')
        self.assertEqual(json.loads(result.tool_calls[0].function.arguments)['script'], value['script'])


class VisionResponseTest(unittest.TestCase):
    def test_thinking_before_text_is_not_treated_as_missing_answer(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vision_template', CORE / 'memory/vision_api.template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = {'apibase': 'https://example.test/anthropic', 'apikey': 'test-placeholder', 'model': 'test'}
        with patch.object(module, '_cfg', return_value=cfg), patch.object(module.requests, 'post') as post:
            post.return_value.json.return_value = {'content': [
                {'type': 'thinking', 'thinking': 'internal'}, {'type': 'text', 'text': 'visible answer'}]}
            self.assertEqual(module._call_claude('fakeimage', 'locate button', 10), 'visible answer')


class TaskBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, val in [('_UNLOCK_FILE', self.tmp.name + '/unlock.json'),
                          ('_RISK_FILE', self.tmp.name + '/risk.json')]:
            ctx = patch.object(droid, name, val); ctx.start(); self.addCleanup(ctx.stop)
        ctx = patch.dict(droid.SENSITIVE_APPS, {'com.tencent.mm': {
            **droid.SENSITIVE_APPS['com.tencent.mm'], 'min_gap': 0}})
        ctx.start(); self.addCleanup(ctx.stop)

    def test_gui_navigation_has_no_arbitrary_action_budget(self):
        for _ in range(100):
            droid._gate_injection('tap', 'com.tencent.mm')
        self.assertEqual(droid.sensitive_unlock('com.tencent.mm', actions=3), {})
        self.assertNotIn('budget', droid.SENSITIVE_APPS['com.tencent.mm'])

    def test_gui_policy_still_blocks_notification_send(self):
        with self.assertRaises(RuntimeError):
            droid._gate_injection('reply_notification', 'com.tencent.mm')

    def test_risk_event_stops_further_actions(self):
        droid.sensitive_risk_event('com.tencent.mm', kind='captcha')
        with self.assertRaises(RuntimeError): droid._gate_injection('tap', 'com.tencent.mm')

    def test_visual_only_paste_never_calls_node_paste(self):
        with patch.object(droid, '_sensitive_fg', return_value=True), patch.object(droid, '_act', return_value={'ok': True}) as act:
            result = droid.paste('search query')
        self.assertEqual(act.call_args.kwargs['op'], 'clipboard')
        self.assertFalse(result['hit'])
        self.assertTrue(result['needs_gui_paste'])

    def test_dump_never_reads_sensitive_tree(self):
        with patch.object(droid, '_fg', return_value='com.tencent.mm'), patch.object(droid, '_get') as get:
            self.assertEqual(droid.dump(), [])
        get.assert_not_called()


if __name__ == '__main__': unittest.main()
