"""run_metrics —— 一次任务的每 turn 运行指标: 记录、聚合、落盘(docs/SPEC.md Part 4.6 / Phase 0)。

职责边界(遵循本仓"纯函数做决策, I/O 留边界"的约定):
  - 纯函数: 判定字段白名单提取、判定函数归因、分位、汇总、JSONL 渲染。
  - 显式副作用: 只有 append_jsonl()/prune_oldest() 碰文件系统; RunRecorder 的时钟与写入口可注入。
  - 只观察: 写入失败静默——观测绝不影响 agent 主循环或手机操作。
  - 隐私: 不写屏幕内容、坐标、账号数据; 判定只取布尔/短枚举白名单字段。

字段口径:
  model_wait_s  本轮 llm_before→llm_after 的墙钟(verbose 路径含流式消费时间)
  tool_exec_s   本轮各工具 tool_before→tool_after 之和(含后验)
  verify_wait_s  上一段"动作已下发"到工具调用结束的时间; 未派发过动作的工具不计(≠0)
                → action_s = tool_exec_s - verify_wait_s
  in_tok/out_tok 同一轮只有一次模型请求, 但一次请求分多事件上报(Claude: message_start
                的占位 output + message_delta 的终值) → 取最大值避免重复计
  resend_chars  BaseSession.history 的序列化字符数(协议路径每轮整体重发; 实际扁平化
                提示词略大于此值)
线程: RunRecorder 自带锁; mark/take 用线程本地(code_run 子线程与循环线程不同)。
"""
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

SCHEMA_VERSION = 1
DEFAULT_KEEP = 20                       # 落盘目录保留最近的运行记录文件数(沿用 _persist_convo 限量先例)
LAYER_TODAY = 'L4'                      # 当前只有通用 ReAct 一层; Phase 3 路由器落地后由路由决策填入

# 判定白名单: 这些键由既有判定函数产出(_img_diff_str/_scroll_verdict/_classify_paste_rows),
# 值为布尔或短枚举, 可安全落盘; 其余工具结果一律不记录。
# 今天手机动作都在 code_run 的 stdout 里, 工具结果不带这些键 → 记录为 tools_without_verdict;
# 结构化动作空间落地后同一段代码直接开始产出判定与判定来源。
VERDICT_KEYS = ('verified', 'uncertain', 'scrolled', 'evidence', 'performed')

# 判定函数归因表: (工具名, 见到的白名单键) → 既有判定函数名。归不出返回 None, 不猜。
_VERIFIER_TABLE = (
    (('tap', 'tap_rel', 'swipe'), ('diff_pct',), '_img_diff_str'),
    (('scroll', 'scroll_view'), ('evidence',), '_scroll_verdict'),
    (('paste',), ('verified',), '_classify_paste_rows'),
)


def diff_pct(value) -> Optional[float]:
    """'diff: 1.234% bbox=[...]' → 1.234; 取不到返回 None(只留像素变化率, 不留坐标)。"""
    if not isinstance(value, str) or '%' not in value:
        return None
    try:
        return float(value.split('%', 1)[0].rsplit(' ', 1)[-1])
    except (TypeError, ValueError):
        return None


def extract_verdict(data) -> dict:
    """从工具结果里取判定证据(白名单); 非 dict 或无线索返回 {}。"""
    if not isinstance(data, dict):
        return {}
    out = {}
    for k in VERDICT_KEYS:
        v = data.get(k)
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, str) and len(v) <= 40:
            out[k] = v
    pct = diff_pct(data.get('diff'))
    if pct is not None:
        out['diff_pct'] = pct
    return out


def attrib_verifier(tool_name: str, verdict: dict) -> Optional[str]:
    """判定证据 → 既有判定函数名。证据不足或工具不识别时返回 None(不猜)。"""
    if not verdict:
        return None
    name = (tool_name or '').rsplit('.', 1)[-1]
    keys = set(verdict)
    for tools, needs, fn in _VERIFIER_TABLE:
        if name in tools and keys & set(needs):
            return fn
    return None


def percentile(values, p) -> Optional[float]:
    """线性插值分位(0..100); 空序列返回 None。"""
    xs = sorted(float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not xs:
        return None
    if len(xs) == 1:
        return round(xs[0], 3)
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


@dataclass
class ToolRecord:
    name: str
    exec_s: float
    verify_s: Optional[float]
    verdict: dict = field(default_factory=dict)
    verifier: Optional[str] = None

    def to_dict(self) -> dict:
        return {'name': self.name, 'exec_s': round(self.exec_s, 3),
                'verify_s': None if self.verify_s is None else round(self.verify_s, 3),
                'verdict': self.verdict, 'verifier': self.verifier}


@dataclass
class TurnRecord:
    turn: int
    layer: str
    t_start: float
    model_wait_s: float = 0.0
    tool_exec_s: float = 0.0
    verify_wait_s: float = 0.0
    in_tok: int = 0
    out_tok: int = 0
    resend_chars: int = 0
    escalations: list = field(default_factory=list)
    tool_records: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {'type': 'turn', 'v': SCHEMA_VERSION, 'turn': self.turn, 'layer': self.layer,
                't_start': self.t_start, 'model_wait_s': round(self.model_wait_s, 3),
                'tool_exec_s': round(self.tool_exec_s, 3), 'verify_wait_s': round(self.verify_wait_s, 3),
                'in_tok': self.in_tok, 'out_tok': self.out_tok, 'resend_chars': self.resend_chars,
                'n_tools': len(self.tool_records), 'tools': [r.name for r in self.tool_records],
                'tool_records': [r.to_dict() for r in self.tool_records],
                'escalations': list(self.escalations)}


@dataclass
class RunRecord:
    run_id: str
    gen: int
    started_at: float
    layer: str = LAYER_TODAY
    turns: list = field(default_factory=list)
    end_reason: str = ''
    ended_at: float = 0.0


def summarize(run: RunRecord) -> dict:
    """一次运行的总量与分位(SPEC Part 7.1); 不含任何屏幕内容。"""
    turns = run.turns
    model = [t.model_wait_s for t in turns]
    end_to_end = [t.model_wait_s + t.tool_exec_s for t in turns]
    return {
        'type': 'run_summary', 'v': SCHEMA_VERSION, 'run_id': run.run_id, 'gen': run.gen,
        'layer': run.layer, 'started_at': run.started_at, 'ended_at': run.ended_at,
        'end_reason': run.end_reason, 'turns': len(turns),
        # 每轮一次 client.chat; 供应商侧重试/故障转移不计入额外一次
        'model_calls': len(turns),
        'model_wait_s': round(sum(model), 3),
        'tool_exec_s': round(sum(t.tool_exec_s for t in turns), 3),
        'verify_wait_s': round(sum(t.verify_wait_s for t in turns), 3),
        'in_tok': sum(t.in_tok for t in turns), 'out_tok': sum(t.out_tok for t in turns),
        'resend_chars_last': turns[-1].resend_chars if turns else 0,
        'p50_turn_s': percentile(end_to_end, 50), 'p95_turn_s': percentile(end_to_end, 95),
        'p50_model_wait_s': percentile(model, 50), 'p95_model_wait_s': percentile(model, 95),
        'escalations': sum(len(t.escalations) for t in turns),
        # Part 7.2 verified-action rate 的分子; uncertain 记"未验证", 绝不是成功;
        # 无判定证据的工具单列, 不混入任何成功率
        'tools_verified': sum(1 for t in turns for r in t.tool_records
                              if r.verdict.get('verified') or r.verdict.get('scrolled')),
        'tools_uncertain': sum(1 for t in turns for r in t.tool_records if r.verdict.get('uncertain')),
        'tools_without_verdict': sum(1 for t in turns for r in t.tool_records if not r.verdict),
    }


def jsonl_line(obj) -> str:
    """单行 JSON(ensure_ascii=False); default=str 兜底——坏类型只毁自己这一行, 不毒死整条通道。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


def append_jsonl(path: str, lines) -> bool:
    """追加写 JSONL(本模块唯一的文件写入口); 失败返回 False 而不抛。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            for line in lines:
                f.write(str(line).rstrip('\n') + '\n')
        return True
    except Exception:
        return False


def prune_oldest(directory: str, prefix: str, keep: int = DEFAULT_KEEP) -> int:
    """只保留最近的 keep 个 <prefix>*.jsonl, 返回删除条数(防 temp 无限增长)。"""
    try:
        names = sorted((n for n in os.listdir(directory)
                        if n.startswith(prefix) and n.endswith('.jsonl')),
                       key=lambda n: os.path.getmtime(os.path.join(directory, n)))
        drop = names[:-keep] if keep > 0 else names
        removed = 0
        for n in drop:
            try:
                os.remove(os.path.join(directory, n))
                removed += 1
            except Exception:
                pass
        return removed
    except Exception:
        return 0


# ---------- 动作后验计时(线程本地; droid._act 打点, 插件在 tool_after 结算) ----------
_tls = threading.local()


def mark_action_dispatched():
    """droid._act() 派发成功后调用: 记录"动作已下发"时刻。
    同一线程上一次未结算的标记先入账——code_run 里连续多个动作由此正确切分。"""
    now = time.time()
    prev = getattr(_tls, 'verify_t0', None)
    if prev is not None:
        _tls.verify_total = getattr(_tls, 'verify_total', 0.0) + max(0.0, now - prev)
    _tls.verify_t0 = now


def take_verify_seconds() -> Optional[float]:
    """结算并取走本线程累计的"动作后验"秒数; 本线程没派发过动作返回 None。"""
    now = time.time()
    t0 = getattr(_tls, 'verify_t0', None)
    if t0 is None:
        return None
    total = getattr(_tls, 'verify_total', 0.0) + max(0.0, now - t0)
    _tls.verify_t0 = None
    _tls.verify_total = 0.0
    return round(total, 3)
