"""run_metrics 插件 —— 每 turn 指标落盘(docs/SPEC.md Phase 0 / Part 4.6)。

契约与 tool_events_hook 一致: 执行层零改动, 只挂 agent_loop 既有 hook 点;
任何失败静默(hooks.trigger 已吞异常, 这里再兜一层); 指标只写文件, 不回灌模型上下文。

落盘: <GA_DIR>/temp/model_responses/sessions/metrics_<logid>.jsonl
  —— _clear_temp() 唯一保留的子树, 与 session_*.json 同级; 每次任务开局限量:
  除本次运行外最多保留 DEFAULT_KEEP 个历史记录(故目录稳态是 DEFAULT_KEEP+1 个文件)。
已知限制(如实记录):
  - 今天所有手机动作都埋在 code_run 的 stdout 里(droid.tap 的返回值不经过工具结果),
    所以工具级判定今天取不到 → 记录里 tools_without_verdict 会等于工具调用数。
    这是现状而不是缺陷: 该计数把这处空白显式记下来, 等结构化动作空间(Phase 1+)落地,
    同一段 extract_verdict/attrib_verifier 直接开始产出 verified/uncertain 与判定来源。
  - 任务被用户中止或抛异常时, agent_loop 的 agent_after 不触发 → 只落已完成的 turn 行,
    没有汇总行; 下一次任务开局会把上次补一条 end_reason='unfinished' 的汇总。
  - 一轮里供应商侧重试/故障转移产生的多次 HTTP 请求只记一次 model_wait(墙钟已含重试)。
"""
import json
import os
import threading
import time

from plugins.hooks import register
import run_metrics

_PREFIX = 'metrics_'
_SUFFIX = '.jsonl'
_lock = threading.Lock()
_rec = None                      # 当前任务的 RunRecorder(任务在 run 线程上串行)


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


def _ga_dir():
    """进程级真相(android_entry.init 固化); CLI 未设时回退到本文件上两级 = gacore/。"""
    d = os.environ.get('GA_DIR')
    if d:
        return d
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _metrics_dir():
    return os.path.join(_ga_dir(), 'temp', 'model_responses', 'sessions')


def _logid(ctx):
    """与既有 LLM 日志同根(model_responses_<ns>.txt) → 指标与响应日志可互相印证。"""
    raw = ''
    try:
        lp = getattr(getattr(ctx.get('handler'), 'parent', None), 'log_path', '') or ''
        if lp:
            raw = os.path.splitext(os.path.basename(lp))[0].replace('model_responses', '').lstrip('_')
    except Exception:
        raw = ''
    raw = raw or str(time.time_ns())
    return ''.join(c for c in raw if c.isalnum() or c in '_-')[:64] or 'run'


def _gen():
    """Android 侧代际号(与 poll/tool_events 同源); 无归属会话返回 0。"""
    try:
        from kernel_adapter import patches
        st = getattr(patches.current_sess(), 'state', None)
        if isinstance(st, dict):
            return int(st.get('gen', 0) or 0)
    except Exception:
        pass
    return 0


def _resend_chars(ctx):
    """本轮真正重发的历史字符数 = BaseSession.history 序列化长度(协议路径每轮整体重发)。
    取不到返回 None——不猜。"""
    try:
        hist = getattr(getattr(ctx.get('client'), 'backend', None), 'history', None)
        if isinstance(hist, list):
            return sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in hist)
    except Exception:
        pass
    return None


def _make_sink(run_id):
    """每个 run 自带写入口(不读全局 _rec): end_run 可能在 _rec 已指向下一次任务后才回调,
    届时读全局会静默丢弃整次运行的记录。"""
    def sink(lines):
        run_metrics.append_jsonl(
            os.path.join(_metrics_dir(), _PREFIX + run_id + _SUFFIX), lines)
    return sink


def _install_usage_observer():
    """把 llmcore 的用量观察者接到当前 recorder(幂等; recorder 每次任务换新, 由闭包现取)。"""
    try:
        import llmcore
        llmcore.add_usage_observer(_on_usage)
    except Exception:
        pass


def _on_usage(in_tok, out_tok, cached_tok):
    rec = _rec
    if rec is not None:
        _safe(rec.note_tokens, in_tok, out_tok)


def _on_agent_before(ctx):
    global _rec
    with _lock:
        prev, _rec = _rec, None
    if prev is not None:                     # 上一轮被中止/异常弃掉: 补一条汇总, 不丢也不假完成
        _safe(prev.end_run, 'unfinished')
    run_id = _logid(ctx)
    with _lock:
        _rec = run_metrics.RunRecorder(run_id=run_id, gen=_gen(), sink=_make_sink(run_id))
    _install_usage_observer()
    _safe(run_metrics.prune_oldest, _metrics_dir(), _PREFIX, run_metrics.DEFAULT_KEEP)


def _on_turn_before(ctx):
    rec = _rec
    if rec is not None:
        _safe(rec.start_turn, int(ctx.get('turn') or 0))


def _on_llm_before(ctx):
    rec = _rec
    if rec is not None:
        _safe(rec.llm_start)


def _on_llm_after(ctx):
    rec = _rec
    if rec is None:
        return
    n = _resend_chars(ctx)
    if n is not None:
        _safe(rec.set_resend_chars, n)
    _safe(rec.llm_end)


def _on_tool_before(ctx):
    if (ctx.get('tool_name') or '') == 'no_tool':
        return                              # 引擎自动触发, 不是工具调用
    rec = _rec
    if rec is not None:
        _safe(rec.tool_start)


def _on_tool_after(ctx):
    if (ctx.get('tool_name') or '') == 'no_tool':
        return                              # 引擎自动触发, 不是工具调用
    rec = _rec
    if rec is None:
        return
    _safe(rec.tool_end, str(ctx.get('tool_name') or ''),
          getattr(ctx.get('ret'), 'data', None), run_metrics.take_verify_seconds())


def _on_turn_after(ctx):
    rec = _rec
    if rec is not None:
        _safe(rec.end_turn)


def _on_agent_after(ctx):
    global _rec
    with _lock:
        rec, _rec = _rec, None
    if rec is None:
        return
    reason = ctx.get('exit_reason')
    reason = reason.get('result', '') if isinstance(reason, dict) else ''
    _safe(rec.end_run, reason or 'MAX_TURNS_EXCEEDED')


register('agent_before', _on_agent_before)
register('turn_before', _on_turn_before)
register('llm_before', _on_llm_before)
register('llm_after', _on_llm_after)
register('tool_before', _on_tool_before)
register('tool_after', _on_tool_after)
register('turn_after', _on_turn_after)
register('agent_after', _on_agent_after)
