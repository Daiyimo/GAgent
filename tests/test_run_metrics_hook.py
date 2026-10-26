"""run_metrics 插件: 挂 agent_loop 既有 hook 点, 一次任务产出 SPEC Part 7.1 全指标集。

用假 client/handler 真跑 agent_runner_loop: 不连设备、不联网、不需要模型 key。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import agent_loop
import llmcore
import run_metrics
import plugins.run_metrics_hook as hook
from agent_loop import StepOutcome


class _Backend:
    def __init__(self):
        self.history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'x' * 100}]}]


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = json.dumps(arguments)


class _TC:
    def __init__(self, name, args, id='tc1'):
        self.function = _Fn(name, args)
        self.id = id


class _Resp:
    def __init__(self, tool_calls):
        self.thinking = ''
        self.content = 'ok'
        self.raw = ''
        self.tool_calls = tool_calls
        self.stop_reason = 'tool_use' if tool_calls else 'end_turn'


class _Client:
    """两轮: 第一轮调 tap, 第二轮不调工具(引擎自动触发 no_tool → 结束)。"""
    last_tools = ''

    def __init__(self, script):
        self.script = list(script)
        self.backend = _Backend()

    def chat(self, messages, tools=None):
        name = self.script.pop(0)
        llmcore._record_usage({'prompt_tokens': 1975, 'completion_tokens': 42,
                               'prompt_tokens_details': {'cached_tokens': 8}}, 'chat_completions')
        yield 'chunk'
        return _Resp([_TC(name, {})] if name else [])


class _Handler(agent_loop.BaseHandler):
    def __init__(self, parent):
        self.max_turns = 5
        self.current_turn = 0
        self._done_hooks = []
        self.parent = parent
        self.working = {}

    def do_tap(self, args, response):
        """合成替身: 代表"结果自带判定字段的工具"——即未来的结构化动作空间。
        今天所有手机动作都埋在 code_run 的 stdout 里, 工具级判定确实取不到(见模块已知限制),
        所以这条路径用替身覆盖, 不冒充真实现状。"""
        run_metrics.mark_action_dispatched()     # 模拟"动作已下发"(真实路径由 droid._act 打点)
        return StepOutcome({'verified': True, 'diff': 'diff: 1.500% bbox=[0,0,9,9]'},
                           next_prompt='next')

    def do_no_tool(self, args, response):
        return StepOutcome({'done': True}, next_prompt=None)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    saved, hook._rec = hook._rec, None
    yield tmp_path / 'temp' / 'model_responses' / 'sessions'
    hook._rec = saved


def _drive(tmp_path, script=('tap', None), logid='1700000000000000000'):
    parent = SimpleNamespace(log_path=str(tmp_path / f'model_responses_{logid}.txt'), task_dir=None)
    handler = _Handler(parent)
    # agent_runner_loop 是生成器: 必须消费掉循环体才真正执行(与 agentmain.run 的 for chunk in gen 一致)
    list(agent_loop.agent_runner_loop(_Client(list(script)), 'sys', 'read three headlines',
                                      handler, [], max_turns=5, verbose=False))
    return handler


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]


def test_one_task_writes_the_phase_zero_metric_set(run_dir, tmp_path):
    _drive(tmp_path)
    files = list(run_dir.glob('metrics_*.jsonl'))
    assert len(files) == 1
    lines = _lines(files[0])
    turns = [x for x in lines if x['type'] == 'turn']
    summary = [x for x in lines if x['type'] == 'run_summary']
    assert len(turns) == 2 and len(summary) == 1
    t1 = turns[0]
    assert t1['layer'] == 'L4' and t1['turn'] == 1
    assert t1['model_wait_s'] >= 0 and t1['tool_exec_s'] >= 0 and t1['verify_wait_s'] >= 0
    assert (t1['in_tok'], t1['out_tok']) == (1975, 42)
    assert t1['resend_chars'] > 0
    assert t1['tools'] == ['tap']
    assert t1['tool_records'][0]['verdict'] == {'verified': True, 'diff_pct': 1.5}
    assert t1['tool_records'][0]['verifier'] == '_img_diff_str'
    assert t1['escalations'] == []
    s = summary[0]
    assert s['turns'] == 2 and s['model_calls'] == 2
    assert s['end_reason'] == 'CURRENT_TASK_DONE'
    assert s['p50_turn_s'] is not None and s['p95_turn_s'] is not None
    assert s['in_tok'] == 3950 and s['out_tok'] == 84
    assert s['tools_verified'] == 1
    assert s['tools_uncertain'] == 0 and s['tools_without_verdict'] == 0


def test_metrics_file_sits_beside_the_session_snapshots(run_dir, tmp_path):
    _drive(tmp_path)
    assert (run_dir / 'metrics_1700000000000000000.jsonl').exists()


def test_the_engine_no_tool_call_is_not_counted_as_a_tool(run_dir, tmp_path):
    _drive(tmp_path)
    lines = _lines(next(run_dir.glob('metrics_*.jsonl')))
    turns = [x for x in lines if x['type'] == 'turn']
    assert [t['n_tools'] for t in turns] == [1, 0]
    assert turns[1]['tools'] == []


def test_pruning_keeps_only_the_newest_run_files(run_dir, tmp_path):
    for i in range(run_metrics.DEFAULT_KEEP + 3):
        _drive(tmp_path, logid=str(1700000000000000000 + i))
    # 裁剪发生在任务开局, 裁的是"除本次之外"的历史记录 → 稳态是 DEFAULT_KEEP 个历史 + 本次 1 个
    assert len(list(run_dir.glob('metrics_*.jsonl'))) == run_metrics.DEFAULT_KEEP + 1


def test_unfinished_run_is_closed_by_the_next_task(run_dir, tmp_path):
    """中止/异常时 agent_after 不触发; 下一个任务开局必须把上次标成 unfinished, 不丢也不假完成。"""
    hook._on_agent_before({'handler': _Handler(SimpleNamespace(
        log_path=str(tmp_path / 'model_responses_1.txt'), task_dir=None))})
    hook._on_turn_before({'turn': 1})
    hook._on_llm_before({})
    hook._on_llm_after({'client': _Client([])})
    # 没有 turn_after / agent_after —— 模拟循环生成器被弃
    _drive(tmp_path, logid='2')
    assert _lines(run_dir / 'metrics_1.jsonl')[-1]['end_reason'] == 'unfinished'


def test_a_failing_write_never_breaks_the_task(run_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(run_metrics, 'append_jsonl',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    handler = _drive(tmp_path)          # 仍然正常跑完并返回终态
    assert handler.current_turn == 2


def test_ga_dir_fallback_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv('GA_DIR', raising=False)
    assert hook._ga_dir().endswith('gacore')
