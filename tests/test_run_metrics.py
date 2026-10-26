"""每 turn 运行指标: 纯聚合、判定归因、分位与落盘(SPEC.md Part 4.6 / Phase 0)。

全部合成 fixture: 不连设备、不联网、不需要模型 key。
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import run_metrics


@pytest.fixture
def clean_verify():
    """排空线程本地的 verify 累加器(线程本地, 不影响其他测试)。"""
    run_metrics.take_verify_seconds()
    yield
    run_metrics.take_verify_seconds()


class TestExtractVerdict:
    def test_booleans_and_short_enums_are_kept(self):
        data = {'verified': True, 'uncertain': False, 'scrolled': True,
                'evidence': 'pixel', 'performed': True, 'hint': 'x' * 500,
                'fg': 'com.example.app'}
        assert run_metrics.extract_verdict(data) == {
            'verified': True, 'uncertain': False, 'scrolled': True,
            'evidence': 'pixel', 'performed': True}

    def test_diff_becomes_a_bare_percentage_without_bbox(self):
        v = run_metrics.extract_verdict({'diff': 'diff: 1.234% bbox=[10,20,30,40]'})
        assert v == {'diff_pct': 1.234}

    def test_unparseable_or_missing_diff_is_dropped(self):
        assert run_metrics.extract_verdict({'diff': 'diff: n/a'}) == {}
        assert run_metrics.extract_verdict({'diff': None}) == {}
        assert run_metrics.extract_verdict({'diff': 12}) == {}

    def test_non_dict_result_yields_nothing(self):
        assert run_metrics.extract_verdict(None) == {}
        assert run_metrics.extract_verdict('a very long tool result') == {}
        assert run_metrics.extract_verdict([{'t': 'node'}]) == {}


class TestAttribVerifier:
    @pytest.mark.parametrize('tool,verdict,expected', [
        ('droid.tap', {'verified': True, 'diff_pct': 1.2}, '_img_diff_str'),
        ('tap', {'uncertain': True, 'diff_pct': 0.0}, '_img_diff_str'),
        ('swipe', {'diff_pct': 2.0}, '_img_diff_str'),
        ('scroll_view', {'scrolled': True, 'evidence': 'text'}, '_scroll_verdict'),
        ('scroll', {'scrolled': False, 'evidence': 'none'}, '_scroll_verdict'),
        ('paste', {'verified': True}, '_classify_paste_rows'),
        ('tap', {'verified': True}, None),          # 无像素证据 → 不归因
        ('file_read', {'verified': True}, None),    # 非判定类工具 → 不归因
        ('dump', {}, None),
    ])
    def test_mapping(self, tool, verdict, expected):
        assert run_metrics.attrib_verifier(tool, verdict) == expected


class TestPercentile:
    def test_empty(self):
        assert run_metrics.percentile([], 50) is None

    def test_single_value(self):
        assert run_metrics.percentile([4.2], 95) == 4.2

    def test_interpolates(self):
        assert run_metrics.percentile([1, 2, 3, 4], 50) == 2.5
        assert run_metrics.percentile([1, 2, 3, 4], 95) == 3.85

    def test_ignores_non_numbers(self):
        assert run_metrics.percentile([1, None, 'x', 3], 50) == 2.0


class TestVerifyAccumulator:
    def test_no_mark_means_no_verify_time(self, clean_verify):
        assert run_metrics.take_verify_seconds() is None

    def test_mark_then_take_is_non_negative_and_one_shot(self, clean_verify):
        run_metrics.mark_action_dispatched()
        first = run_metrics.take_verify_seconds()
        assert first is not None and first >= 0.0
        assert run_metrics.take_verify_seconds() is None

    def test_consecutive_actions_split_the_wait(self, clean_verify):
        """code_run 里连续多个动作: 每段"动作后验"都要计入, 不能只算最后一个。"""
        run_metrics.mark_action_dispatched()
        time.sleep(0.02)
        run_metrics.mark_action_dispatched()      # 第二段动作开始 → 第一段入账
        time.sleep(0.02)
        total = run_metrics.take_verify_seconds()
        assert total >= 0.04


class TestJsonlIO:
    def test_jsonl_line_survives_non_scalar_values(self):
        line = run_metrics.jsonl_line({'a': {1, 2}, 'b': object()})
        assert '\n' not in line
        assert json.loads(line)['b']

    def test_append_creates_the_directory_and_one_object_per_line(self, tmp_path):
        p = tmp_path / 'a' / 'b' / 'metrics_1.jsonl'
        assert run_metrics.append_jsonl(str(p), ['{"a": 1}', '{"b": 2}']) is True
        assert run_metrics.append_jsonl(str(p), ['{"c": 3}']) is True
        assert [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] == [
            {'a': 1}, {'b': 2}, {'c': 3}]

    def test_unwritable_path_returns_false_instead_of_raising(self, tmp_path):
        blocker = tmp_path / 'blocker'
        blocker.write_text('not a directory', encoding='utf-8')
        assert run_metrics.append_jsonl(str(blocker / 'x.jsonl'), ['{}']) is False

    def test_prune_keeps_only_the_newest_files(self, tmp_path):
        for i, name in enumerate(['metrics_a.jsonl', 'metrics_b.jsonl', 'metrics_c.jsonl']):
            p = tmp_path / name
            p.write_text('{}', encoding='utf-8')
            os.utime(p, (1000 + i, 1000 + i))
        assert run_metrics.prune_oldest(str(tmp_path), 'metrics_', keep=2) == 1
        assert sorted(x.name for x in tmp_path.iterdir()) == ['metrics_b.jsonl', 'metrics_c.jsonl']

    def test_prune_ignores_other_files_and_missing_dirs(self, tmp_path):
        (tmp_path / 'session_x.json').write_text('{}', encoding='utf-8')
        assert run_metrics.prune_oldest(str(tmp_path), 'metrics_', keep=5) == 0
        assert run_metrics.prune_oldest(str(tmp_path / 'nope'), 'metrics_') == 0
