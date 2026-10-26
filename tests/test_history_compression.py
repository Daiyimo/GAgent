"""F3: 历史压缩参数化 + 更激进的默认值。

真机实证: 长任务(30+ 轮)历史不压缩时 in_tok 从 11K 涨到 36K,
model_wait 从 3s 涨到 37s——上下文膨胀是后期变慢的主因。
经实测对比选择此方案效果更佳: keep_recent=4(只保留最近 4 轮完整)/max_len=600。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
from llmcore import compress_history_tags


def _msgs(n):
    out = []
    for i in range(n):
        out.append({'role': 'user', 'content': '<tool_use>{"name":"code_run","arguments":{"script":"%s"}}</tool_use><tool_result>%s</tool_result>%s' % ('x' * 2000, 'y' * 2000, 'z' * 2000)})
    return out


class CompressionParamsTest(unittest.TestCase):
    def setUp(self):
        compress_history_tags._cd = 0
        self.addCleanup(lambda: setattr(compress_history_tags, '_cd', 0))

    def test_older_messages_truncated_recent_kept(self):
        msgs = _msgs(10)
        compress_history_tags(msgs, keep_recent=4, max_len=600, force=True)
        # 前 6 条被截断, 后 4 条原样
        self.assertIn('[Truncated]', msgs[0]['content'])
        self.assertNotIn('[Truncated]', msgs[-1]['content'])
        self.assertLess(len(msgs[0]['content']), 800)

    def test_truncation_keeps_head_and_tail(self):
        msgs = [{'role': 'user', 'content': '<tool_use>HEAD' + 'm' * 3000 + 'TAIL</tool_use>'}]
        compress_history_tags(msgs, keep_recent=0, max_len=600, force=True)
        self.assertIn('HEAD', msgs[0]['content'])
        self.assertIn('TAIL', msgs[0]['content'])
        self.assertIn('[Truncated]', msgs[0]['content'])

    def test_history_and_key_info_blocks_collapsed(self):
        msgs = [{'role': 'user', 'content': '<history>' + 'h' * 3000 + '</history><key_info>' + 'k' * 1000 + '</key_info>'}]
        compress_history_tags(msgs, keep_recent=0, force=True)
        self.assertIn('<history>[...]</history>', msgs[0]['content'])
        self.assertIn('<key_info>[...]</key_info>', msgs[0]['content'])

    def test_interval_still_observed(self):
        # interval=5: 前 4 次调用不压缩, 第 5 次压缩
        msgs = _msgs(10)
        for _ in range(4):
            compress_history_tags(msgs, keep_recent=4, max_len=600, interval=5)
        self.assertNotIn('[Truncated]', msgs[0]['content'])
        compress_history_tags(msgs, keep_recent=4, max_len=600, interval=5)
        self.assertIn('[Truncated]', msgs[0]['content'])


if __name__ == '__main__':
    unittest.main()
