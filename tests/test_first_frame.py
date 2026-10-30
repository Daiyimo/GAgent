"""任务第一步必须看到"此刻"的屏幕。

为什么钉这条: 真机 2026-10-30 15:29/15:34 两次任务里, 会话历史还带着上一个任务的截图和
"今日密码弹窗已打开、密码是 0600/0954/…"的结论; 而这两个任务的第一轮**一张图都没发**
(auto 模式只在视觉型页面上附图, 那会儿前台是桌面) —— 模型凭旧记忆判断"弹窗还开着",
于是在桌面上连按 close/back, 把整个小程序退掉了, 用户看到的就是"路径全不对"。

两条配套口径:
  ① 任务第一步无论如何都附图(除非 /vision off), 并在提示里声明"旧截图/坐标作废";
  ② 顺手把历史里的旧截图块摘掉: 既防止被当成"现在", 也省 token(每张约 1.4k)。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import ga_android                                                      # noqa: E402


def _handler(history=None, pending=True):
    h = object.__new__(ga_android.GenericAgentHandler)
    h._task_frame_pending = pending
    h._attached_img_wh = None
    h._attached_screen_wh = None
    h._vision_in_turn_attached = False
    h.parent = types.SimpleNamespace(history=history if history is not None else [])
    return h


def _fake_droid(sensitive=False, pkg='com.android.launcher3'):
    return types.SimpleNamespace(
        _sensitive_fg=lambda: sensitive,
        shot_frame_b64=lambda **kw: ('BASE64', (647, 1440)),
        screen=lambda: (1200, 2670),
        ping=lambda: {'pkg': pkg},
        take_pending_frame=lambda: None,
    )


class FirstFrameTest(unittest.TestCase):

    def _call(self, h, mode='auto', sensitive=False, pkg='com.android.launcher3'):
        with patch.dict(sys.modules, {'droid': _fake_droid(sensitive, pkg)}), \
                patch('agent_settings.vision_in_turn', return_value=mode):
            return h.turn_content_blocks()

    def test_first_turn_attaches_even_when_the_screen_is_not_visual(self):
        # 桌面不是"视觉型页面": auto 模式下普通轮次不附图, 但任务第一步必须附。
        blocks = self._call(_handler())
        self.assertIsNotNone(blocks)
        self.assertEqual(blocks[1]['source']['data'], 'BASE64')
        self.assertIn('任务刚开始', blocks[0]['text'])
        self.assertIn('作废', blocks[0]['text'])
        self.assertIn('com.android.launcher3', blocks[0]['text'])

    def test_the_next_turn_falls_back_to_the_auto_rule(self):
        h = _handler()
        self.assertIsNotNone(self._call(h))
        self.assertIsNone(self._call(h))                 # 第二步起: 桌面不附图

    def test_stale_screenshots_are_dropped_from_history(self):
        hist = [
            {'role': 'user', 'content': [{'type': 'text', 'text': '旧提示'},
                                          {'type': 'image', 'source': {'data': 'OLD'}}]},
            {'role': 'user', 'content': [{'type': 'image', 'source': {'data': 'ONLY'}}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': '好的'}]},
        ]
        self._call(_handler(hist))
        self.assertEqual(hist[0]['content'], [{'type': 'text', 'text': '旧提示'}])
        self.assertEqual(hist[1]['content'][0]['type'], 'text')    # 只剩图的空消息补一句占位
        self.assertIn('过期', hist[1]['content'][0]['text'])
        self.assertEqual(hist[2]['content'], [{'type': 'text', 'text': '好的'}])

    def test_vision_off_changes_nothing_at_all(self):
        hist = [{'role': 'user', 'content': [{'type': 'image', 'source': {'data': 'OLD'}}]}]
        h = _handler(hist)
        self.assertIsNone(self._call(h, mode='off'))
        self.assertEqual(hist[0]['content'][0]['type'], 'image')   # off: 一帧不发, 也不动历史
        self.assertTrue(h._task_frame_pending)

    def test_always_mode_still_attaches_on_the_second_turn(self):
        h = _handler()
        self._call(h, mode='always')
        self.assertIsNotNone(self._call(h, mode='always'))


if __name__ == '__main__':
    unittest.main()
