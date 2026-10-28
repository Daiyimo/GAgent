import sys, os, re, json, time, threading, importlib
from datetime import datetime
from pathlib import Path
import tempfile, traceback, subprocess, itertools, collections, difflib, shutil
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_loop import BaseHandler, StepOutcome, json_default
import run_guard   # 僵尸线程协作取消护栏(超时/停止后仍在后台派发手势的线程, 下一次操作手机即自毁)
import phone_ledger   # 动作账本(SPEC W3): 每轮 [LOOP-GUARD] 提示注入; 与 droid 执行边界守卫共用 ACTIVE 实例(本模块保持设备无关, 不 import droid)
import geom          # 坐标换算唯一权威(0-1000 ↔ 像素) + 实测系统 UI 锚带; 纯函数无设备依赖
run_guard.install_thread_inheritance()   # 让用户代码派生的子线程也继承取消令牌(僵尸孙线程同样受护栏); 幂等
script_dir = os.path.dirname(os.path.abspath(__file__))

def safe_print(*args, **kwargs):
    try: print(*args, **kwargs)
    except: pass

def code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=None, maxlen=10000, myprint=safe_print, vision_backend=None):
    """代码执行器 (Android: python进程内exec, sh走/system/bin/sh)"""
    preview = (code[:60].replace('\n', ' ') + '...') if len(code) > 60 else code.strip()
    cwd = cwd or os.path.join(script_dir, 'temp')
    yield f"[Action] Running {code_type} in {os.path.basename(cwd)}: {preview}\n"
    os.makedirs(cwd, exist_ok=True)
    myprint("code run output:")
    full_stdout = []; exit_code = None
    if code_type in ["python", "py"]:
        header = ''
        cr_header = os.path.join(script_dir, 'assets', 'code_run_header.py')
        if os.path.exists(cr_header): header = open(cr_header, encoding='utf-8').read()
        box = {}
        class _Cap:
            def write(self, t): full_stdout.append(t)
            def flush(self): pass
        token = [False]   # 协作取消令牌: 超时/停止时置位; 僵尸线程下一次经 droid 副作用入口即抛 RunCancelled 自毁
        def _run():
            # 截止时刻一并登记: droid.ask_vision 之类的昂贵调用据此自算总时长预算
            run_guard.enter(token, time.time() + timeout)
            old_out, old_err, old_cwd = sys.stdout, sys.stderr, os.getcwd()
            try:
                os.chdir(cwd)
                sys.stdout = sys.stderr = _Cap()
                try:
                    import droid
                    droid.set_vision_backend(vision_backend)
                except Exception:
                    pass
                exec(compile(header + '\n' + code, '<code_run>', 'exec'),
                     {'__name__': '__main__', '__file__': os.path.join(cwd, '_code_run.py')})
                box['exit'] = 0
            except SystemExit as e:
                box['exit'] = int(e.code) if str(e.code).isdigit() else (0 if not e.code else 1)
            except run_guard.RunCancelled:
                box['exit'] = 1   # 被取消令牌中止: 静默退出(输出早已被监督线程取走), 不喷 traceback
            except BaseException:
                full_stdout.append(traceback.format_exc()); box['exit'] = 1
            finally:
                try:
                    import droid
                    droid.set_vision_backend(None)
                except Exception:
                    pass
                run_guard.leave()
                sys.stdout, sys.stderr = old_out, old_err
                try: os.chdir(old_cwd)
                except: pass
        t = threading.Thread(target=_run, daemon=True)
        start_t = time.time(); t.start()
        while t.is_alive():
            if time.time() - start_t > timeout:
                run_guard.cancel(token)
                full_stdout.append("\n[Timeout Error] 超时(令牌已取消; 僵尸线程下一次操作手机即自毁, 不再驱动整机)"); break
            if stop_signal:
                run_guard.cancel(token)
                full_stdout.append("\n[Stopped] 用户请求终止(令牌已取消; 僵尸线程下一次操作手机即自毁)"); break
            time.sleep(0.3)
        t.join(timeout=0.2)
        exit_code = box.get('exit')
    elif code_type in ["sh", "shell", "bash", "powershell", "ps1", "pwsh"]:
        try:
            p = subprocess.run(["sh", "-c", code], capture_output=True, timeout=timeout, cwd=cwd)
            full_stdout.append(p.stdout.decode('utf-8', errors='replace') + p.stderr.decode('utf-8', errors='replace'))
            exit_code = p.returncode
        except subprocess.TimeoutExpired as e:
            full_stdout.append((e.stdout or b'').decode('utf-8', 'replace') + "\n[Timeout Error] 超时强制终止")
        except Exception as e:
            full_stdout.append(format_error(e)); exit_code = 1
    else:
        return {"status": "error", "msg": f"不支持的类型: {code_type}"}
    stdout_str = "".join(full_stdout)
    myprint(stdout_str)
    status = "success" if exit_code == 0 else "error"
    status_icon = "✅" if exit_code == 0 else ("⏳" if exit_code is None else "❌")
    output_snippet = smart_format(stdout_str, max_str_len=600, omit_str='\n\n[omitted long output]\n\n')
    output_snippet = re.sub(r'`{4,}', lambda m: m.group(0)[:3] + '\u200b' + m.group(0)[3:], output_snippet)
    yield f"[Status] {status_icon} Exit Code: {exit_code}\n[Stdout]\n{output_snippet}\n"
    return {"status": status,
            "stdout": smart_format(stdout_str, max_str_len=maxlen, omit_str='\n\n[omitted long output]\n\n'),
            "exit_code": exit_code}


def ask_user(question, candidates=None):
    """question: 向用户提出的问题。candidates: 可选的候选项列表"""
    return {"status": "INTERRUPT", "intent": "HUMAN_INTERVENTION",
        "data": {"question": question, "candidates": candidates or []}}

def format_error(e):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb = traceback.extract_tb(exc_traceback)
    if tb:
        f = tb[-1]
        fname = os.path.basename(f.filename)
        return f"{exc_type.__name__}: {str(e)} @ {fname}:{f.lineno}, {f.name} -> `{f.line}`"
    return f"{exc_type.__name__}: {str(e)}"

def log_memory_access(path):
    if 'memory' not in path: return
    stats_file = os.path.join(script_dir, 'memory/file_access_stats.json')
    try:
        with open(stats_file, 'r', encoding='utf-8') as f: stats = json.load(f)
    except: stats = {}
    fname = os.path.basename(path)
    stats[fname] = {'count': stats.get(fname, {}).get('count', 0) + 1, 'last': datetime.now().strftime('%Y-%m-%d')}
    with open(stats_file, 'w', encoding='utf-8') as f: json.dump(stats, f, indent=2, ensure_ascii=False)

def expand_file_refs(text, base_dir=None):
    """展开文本中的 {{file:路径:起始行:结束行}} 引用为实际文件内容。
    可与普通文本混排。展开失败抛 ValueError。
    base_dir: 相对路径的基准目录，默认为进程 cwd"""
    pattern = r'\{\{file:(.+?):(\d+):(\d+)\}\}'
    def replacer(match):
        path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        path = os.path.abspath(os.path.join(base_dir or '.', path))
        if not os.path.isfile(path): raise ValueError(f"引用文件不存在: {path}")
        with open(path, 'r', encoding='utf-8') as f: lines = f.readlines()
        if start < 1 or end > len(lines) or start > end: raise ValueError(f"行号越界: {path} 共{len(lines)}行, 请求{start}-{end}")
        return ''.join(lines[start-1:end])
    return re.sub(pattern, replacer, text)
    
def file_patch(path: str, old_content: str, new_content: str):
    """在文件中寻找唯一的 old_content 块并替换为 new_content"""
    path = str(Path(path).resolve())
    try:
        if not os.path.exists(path): return {"status": "error", "msg": "文件不存在"}
        with open(path, 'r', encoding='utf-8') as f: full_text = f.read()
        if not old_content: return {"status": "error", "msg": "old_content 为空，请确认 arguments"}
        count = full_text.count(old_content)
        if count == 0: return {"status": "error", "msg": "未找到匹配的旧文本块，建议：先用 file_read 确认当前内容，再分小段进行 patch。若多次失败则询问用户，严禁自行使用 overwrite 或代码替换。"}
        if count > 1: return {"status": "error", "msg": f"找到 {count} 处匹配，无法确定唯一位置。请提供更长、更具体的旧文本块以确保唯一性。建议：包含上下文行来增强特征，或分小段逐个修改。"}
        updated_text = full_text.replace(old_content, new_content)
        with open(path, 'w', encoding='utf-8') as f: f.write(updated_text)
        return {"status": "success", "msg": "文件局部修改成功"}
    except Exception as e: return {"status": "error", "msg": str(e)}

_read_dirs = set()
def _scan_files(base, depth=2):
    try:
        for e in os.scandir(base):
            if e.is_file(): yield (e.name, e.path)
            elif depth > 0 and e.is_dir(follow_symlinks=False): yield from _scan_files(e.path, depth - 1)
    except (PermissionError, OSError): pass
def file_read(path, start=1, keyword=None, count=200, show_linenos=True):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            stream = ((i, l.rstrip('\r\n')) for i, l in enumerate(f, 1))
            stream = itertools.dropwhile(lambda x: x[0] < start, stream)
            if keyword:
                before = collections.deque(maxlen=count//3)
                for i, l in stream:
                    if keyword.lower() in l.lower():
                        res = list(before) + [(i, l)] + list(itertools.islice(stream, count - len(before) - 1))
                        break
                    before.append((i, l))
                else: return f"Keyword '{keyword}' not found after line {start}. Falling back to content from line {start}:\n\n" \
                               + file_read(path, start, None, count, show_linenos)
            else: res = list(itertools.islice(stream, count))
            realcnt = len(res); L_MAX = min(max(100, 256000//max(realcnt,1)), 8000); TAG = " ... [TRUNCATED]"
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (res[0][0] - 1 if res else start - 1) + realcnt + remaining
            tl_str = f"{total_lines}+" if remaining >= 5000 else str(total_lines)
            partial = total_lines > realcnt
            total_tag = f"[FILE] {tl_str} lines" + (f" | PARTIAL showing {realcnt}; assess need for more" if partial else "") + "\n"
            res = [(i, l if len(l) <= L_MAX else l[:L_MAX] + TAG) for i, l in res]
            result = "\n".join(f"{i}|{l}" if show_linenos else l for i, l in res)
            if show_linenos: result = total_tag + result
            elif partial: result += f"\n\n[FILE PARTIAL: showing {realcnt}/{tl_str} lines; assess need for more]"
            _read_dirs.add(os.path.dirname(os.path.abspath(path)))
            return result
    except FileNotFoundError:
        msg = f"Error: File not found: {path}"
        try:
            tgt = os.path.basename(path); scan = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            roots = [scan] + [d for d in _read_dirs if not d.startswith(scan)]
            cands = list(itertools.islice((c for base in roots for c in _scan_files(base)), 2000))
            top = sorted([(difflib.SequenceMatcher(None, tgt.lower(), c[0].lower()).ratio(), c) for c in cands[:2000]], key=lambda x: -x[0])[:5]
            top = [(s, c) for s, c in top if s > 0.3]
            if top: msg += "\n\nDid you mean:\n" + "\n".join(f"  {c[1]}  ({s:.0%})" for s, c in top)
        except Exception: pass
        return msg
    except Exception as e: return f"Error: {str(e)}"

def smart_format(data, max_str_len=100, omit_str=' ... '):
    if not isinstance(data, str): data = str(data)
    if len(data) < max_str_len + len(omit_str)*2: return data
    return f"{data[:max_str_len//2]}{omit_str}{data[-max_str_len//2:]}"

def consume_file(dr, file):
    if dr and os.path.exists(os.path.join(dr, file)): 
        with open(os.path.join(dr, file), encoding='utf-8', errors='replace') as f: content = f.read()
        os.remove(os.path.join(dr, file))
        return content

class GenericAgentHandler(BaseHandler):
    '''Generic Agent 工具库，包含多种工具的实现。工具函数自动加上了 do_ 前缀。实际工具名没有前缀。'''
    def __init__(self, parent, last_history=None, cwd='./temp'):
        phone_ledger.ACTIVE.clear()   # 任务边界: 动作账本不跨任务存活。上个任务卡死的尾巴(等价+aborted)会让
                                      # 新任务第一次动作直接被判 aborted 不下发, 并注入陈旧 [LOOP-GUARD](评审 C1 实证)
        try:
            import droid; droid.reset_trace()   # 操作痕迹同理: 不清则上个任务的 dump/tap 混进本次 recipe_record
        except Exception: pass                   # PC 侧/无设备环境下 droid 不可 import, 不影响工具库注册
        try:
            import droid; droid.reset_vision_fuse()   # 视觉熔断同理: 两次失败即冻结 120s, 上个任务
                                                      # 早期连撞两次(选中的模型不支持图片就会 2.4s 连错两次)
                                                      # 会让新任务整个游戏阶段失去唯一的 grounding 通道
        except Exception: pass
        self.parent = parent
        self.working = {}
        self.cwd = cwd;  self.current_turn = 0
        self.history_info = last_history if last_history else []
        self.code_stop_signal = []
        self._done_hooks = []
        self.print = safe_print

    def _get_abs_path(self, path):
        if not path: return ""
        return os.path.abspath(os.path.join(self.cwd, path))   

    def _extract_code_block(self, response, code_type):
        code_type = {'python':'python|py', 'powershell':'powershell|ps1|pwsh', 'bash':'bash|sh|shell'}.get(code_type, re.escape(code_type))
        matches = re.findall(rf"```(?:{code_type})\n(.*?)\n```", response.content, re.DOTALL)
        if matches: return matches[-1].strip()
        # 兜底: 无语言标签的裸围栏(模型高频发; 旧正则只认带标签的→提取失败→整轮作废, 实证连废2轮≈19s)
        bare = re.findall(r"```\n(.*?)\n```", response.content, re.DOTALL)
        return bare[-1].strip() if bare else None

    def _vision_backend(self):
        """当前任务选择的模型后端: 视觉问答复用同一 provider/model/key/proxy, 随任务页切换。"""
        try:
            c = getattr(self.parent, 'llmclient', None)
            return getattr(c, 'backend', None) if c is not None else None
        except Exception:
            return None

    def do_code_run(self, args, response):
        '''执行代码片段，有长度限制，不允许代码中放大量数据，如有需要应当通过文件读取进行。'''
        code_type = args.get("type", "python")
        code = args.get("code") or args.get("script")
        if not code:
            code = self._extract_code_block(response, code_type)
            if not code:
                return StepOutcome(
                    "[Error] code_run 被调用但既没有 'script' 参数, 回复里也没有 ```python 代码块。"
                    "代码必须二选一: ①(推荐)放进本次工具调用的 script 参数; "
                    "②或在本条回复正文附一个带 python 标签的 ```python 代码块。"
                    "注意: 只在回复里写代码而不发这次工具调用, 代码不会被执行(该轮直接作废)。",
                    next_prompt="\n")
        try: timeout = int(args.get("timeout", 60))
        except: timeout = 60
        raw_path = os.path.join(self.cwd, args.get("cwd", './'))
        cwd = os.path.normpath(os.path.abspath(raw_path))
        code_cwd = os.path.normpath(self.cwd)
        maxlen = 10000 // args.get('_tool_num', 1)
        if code_type == 'python' and args.get("inline_eval"):
            ns = {'handler':self, 'parent':self.parent, 'history':json.dumps(self.parent.llmclient.backend.history)}
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                try:
                    import droid
                    droid.set_vision_backend(self._vision_backend())
                except Exception:
                    pass
                try:
                    try: result = repr(eval(code, ns))
                    except SyntaxError: exec(code, ns); result = ns.get('_r', 'OK')
                except Exception as e: result = f'Error: {e}'
                finally:
                    try:
                        import droid
                        droid.set_vision_backend(None)
                    except Exception:
                        pass
            finally: os.chdir(old_cwd)
        else: result = yield from code_run(code, code_type, timeout, cwd, code_cwd=code_cwd, stop_signal=self.code_stop_signal, maxlen=maxlen, myprint=self.print, vision_backend=self._vision_backend())
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)
    
    _GUI_ACTIONS = ('tap', 'swipe', 'longpress', 'text', 'key', 'launch', 'back', 'home', 'wait')

    def _resolve_point(self, args, key, rel_key):
        """gui_act 坐标: `point`=像素, `rel`=0-1000。两个具名字段二选一, 不猜单位。

        为什么不再用一个 point 猜(旧 _norm_pt 的「任一轴 >1000 就当像素」): 在
        1200x2670 上, y<=1000(屏幕上方 37%)且 x<=1000(宽 83%)的区域里, 像素坐标会被
        静默当成归一化值再缩一遍。实测放大镜像素 (996,215) → (1195,574), 偏 199px
        右、359px 下; 搜索框 (635,245) → (762,654), 偏 409px 下。不报错、无 hint,
        模型只看到 diff=0, 于是反复重点。而搜索框/放大镜/标题行**全在这片区域**,
        「点不到搜索框」因此是必然, 不是偶发。单位无法从一个数值对里可靠推断, 所以
        让调用方显式选: 观测 API(dump/look/find/obs 的 x,y)给的像素走 point,
        ask_vision 给的千分比走 rel。

        越界像素**报错而不夹取**: 夹取会把"单位选错"变成一个看似合理的落点, 正是要消掉
        的那类静默失败; 报错带上当前屏幕尺寸和 rel 写法, 模型一轮就能改对。rel 侧
        仍夹取(见 geom.to_px): VLM 估算溢出几个单位是噪声, 不值得废一轮。

        落在状态栏里的像素点同样报错: 状态栏(geom 的 status 锚带, 本机 y 0-4%)没有
        可点目标, SOP 也明令"绝不点状态栏", 所以踩进去几乎只有一个成因——把 0-1000
        的数对当成了像素。真机 17:48 实证: ask_vision 回的是百分数(85%), 模型乘 10 得
        850、又猜了 y=45, 当 point 传进去 → 实际点 (1020,120) 状态栏, 搜索页从未打开,
        而模型只看到 diff 29% 以为成功了。这里把它变成一句能自解释的错。
        确需点状态栏(极少数)走 code_run 的 droid.tap(x,y), 那条路没有这道门。"""
        import droid
        w, h = droid.screen()
        has_px = args.get(key) is not None
        has_rel = args.get(rel_key) is not None
        if has_px and has_rel:
            raise ValueError('%s (pixels) and %s (0-1000) are the same coordinate in two '
                             'units; pass only one' % (key, rel_key))
        if not has_px and not has_rel:
            raise ValueError('%s needs point [x,y] in pixels (dump()/look()/obs x,y) or '
                             '%s [x,y] in 0-1000 (ask_vision); screen is %dx%d'
                             % (key, rel_key, w, h))
        name = key if has_px else rel_key
        v = args[name]
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError('%s must be [x, y], got %r' % (name, v))
        try:
            a, b = float(v[0]), float(v[1])
        except (TypeError, ValueError):
            raise ValueError('%s must be two numbers, got %r' % (name, v))
        if has_rel:
            return geom.to_px(a, b, w, h)
        if not (0 <= a < w and 0 <= b < h):
            raise ValueError('%s %r is outside the current screen (%dx%d). If those are '
                             '0-1000 normalized values, pass them as %s instead.'
                             % (name, v, w, h, rel_key))
        if w > 1 and h > 1 and geom.in_band('status', int(a), int(b), w, h):
            raise ValueError('%s %r lands in the status bar (y 0-%d on a %dx%d screen), '
                             'which has no tap target. That almost always means these are '
                             '0-1000 normalized values, not pixels — pass them as %s '
                             '(e.g. %s:[%d, %d]). If you really must tap the status bar, '
                             'use droid.tap(x, y) in code_run.'
                             % (name, v, int(0.04 * h), w, h, rel_key, rel_key,
                                *geom.to_norm(int(a), int(b), w, h)))
        return int(a), int(b)

    def do_gui_act(self, args, response):
        """GUI structured action: the model picks an action instead of writing Python.
        Measured on a real device against the alternative design: a free-form code agent
        burns 1-3 model calls per round exploring APIs; the structured action protocol
        finished 31 steps with almost no wasted turns. This design measured better."""
        import droid
        act = str(args.get('action') or '')
        if act not in self._GUI_ACTIONS:
            return StepOutcome('[Error] gui_act unknown action %r, choose from: %s'
                               % (act, '/'.join(self._GUI_ACTIONS)), next_prompt='\n')
        if act in ('tap', 'longpress', 'swipe'):
            # 预观测: 动作落账要带「动作前」的观测, 才能从点所在节点推导 recipe locator。
            # 不喂它, gui_act 通道录出的配方 locator 全是 any, 回放第一步就升级(评审实证)。
            # 只对需要坐标的动作做: back/home/key/wait 没有可定位的目标。
            # 按需而非每次: 模型在 code_run 里刚 dump()/look() 过时观测仍然有效,
            # 再 dump 一次是纯浪费(真机 39 轮任务约 20 次 gui_act 各多付一次 a11y 往返)。
            try: droid.ensure_fresh_obs()
            except Exception: pass
        try:
            if act in ('tap', 'longpress'):
                x, y = self._resolve_point(args, 'point', 'rel')
                if act == 'tap':
                    ret = droid.tap(x, y)
                else:
                    ret = droid.longpress(x, y, int(args.get('ms') or 800))
                # verified/uncertain/hint/fg 必须一起转发: 坐标失效(屏幕形态变化)、点到非热区、
                # 验证不可用在模型眼里要能区分。只给 diff 会把"没变化"当成"点到了但没反应"反复重发。
                out = {'action': act, 'point': [x, y], 'diff': ret.get('diff')}
                for k in ('verified', 'uncertain', 'hint', 'fg', 'screen', 'rot', 'orientation', 'orientation_changed'):
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'swipe':
                x1, y1 = self._resolve_point(args, 'point1', 'rel1')
                x2, y2 = self._resolve_point(args, 'point2', 'rel2')
                ret = droid.swipe(x1, y1, x2, y2, int(args.get('ms') or 300))
                out = {'action': act, 'diff': ret.get('diff')}
                for k in ('verified', 'uncertain', 'hint', 'fg', 'screen', 'rot', 'orientation', 'orientation_changed'):
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'text':
                val = str(args.get('value') or '')
                if not val:
                    return StepOutcome('[Error] text needs value (the content to type)', next_prompt='\n')
                ret = droid.paste(val)
                out = {'action': act, 'hit': ret.get('hit'), 'uncertain': ret.get('uncertain')}
                # 敏感 App(微信等): paste 只入剪贴板; 不把 needs_gui_paste/hint 带回去,
                # 模型只看到 hit=false/uncertain, 会误判“输入失败”并重复点搜索框。
                for k in ('needs_gui_paste', 'hint', 'ime_hint', 'ime_label'):
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'key':
                droid.key(str(args.get('value') or 'ENTER'))
                out = {'action': act}
            elif act == 'launch':
                ret = droid.launch(str(args.get('value') or ''))
                out = {'action': act, 'fg': ret.get('fg')}
                for k in ('screen', 'rot', 'orientation', 'fullscreen', 'shell', 'policy', 'hint'):
                    # fullscreen/shell/hint 必须一起转发: Kotlin 在两条 shell 通道都不可用时**故意**
                    # 回一份自解释的降级载荷(fullscreen:false + 两条通道真值 + 怎么修)。丢掉它,
                    # stepOS 把第三方 uid 的启动改写成小窗, 而 ping() 仍报整屏几何——于是后续所有
                    # 相对坐标全部落在小窗之外, agent 既不知道原因, 也没法告诉用户怎么修。
                    if ret.get(k) is not None:
                        out[k] = ret[k]
            elif act == 'back':
                droid.back()
                out = {'action': act}
            elif act == 'home':
                droid.home()
                out = {'action': act}
            else:
                sec = min(float(args.get('seconds') or 2), 30)
                st = droid.wait_stable(max_wait=sec)
                out = {'action': act, 'stable': st.get('stable'), 'waited_s': round(st.get('waited_s', 0), 2)}
        except Exception as e:
            return StepOutcome('[Error] gui_act failed: %s: %s' % (type(e).__name__, e), next_prompt='\n')
        # 动作后自动等页面稳定(F1): 静态页几乎不花时间, 加载页不抢跑。
        # 但动作自带后验已经证明页面变了(diff 超带/hit/fg)时不再等: 消除类棋盘/视频/动画页
        # 永远等不到两帧 diff<=1.5%, 每步白睡满 max_wait——那等于把 d60f6be 想消掉的固定
        # action_sleep 又请回来, 只是从 5s 变成 3s 且换成隐式发生。
        # wait 动作自己就是等待, 不重复等。
        changed = bool(out.get('orientation_changed'))
        if act != 'wait' and not changed and not self._act_proved_change(act, out):
            try:
                st = droid.wait_stable()
                out['stable'] = st.get('stable')
                if st.get('uncertain'):
                    out['stable_uncertain'] = True
            except Exception:
                pass
        # 动作后带回一份紧凑观测: 否则模型必须再花一整轮 code_run 去 dump()/look()
        # 才知道屏幕上现在有什么, "观察一轮→动作一轮"把每个动作的成本翻倍。
        # 真机实证: 39 轮任务里约 20 次是纯观察轮; 在供应商 p50 延迟 5~10s 的现状下,
        # 省一轮就是省 5~10s。观测封顶 12 项、标签截断, 比模型自己 print 全量节点小一个量级。
        # 旋转/折叠时 wait_stable 仍跳过(那是 16.3s/15.6s 后验的主要来源), 但必须给新画面的
        # 紧凑观测: 只给 screen/rot 不足以让弱模型继续——真机 3.7flash 看到横屏后直接放弃。
        if act in ('tap', 'swipe', 'longpress', 'back', 'home', 'key', 'launch'):
            try:
                out['obs'] = self._compact_obs()
            except Exception:
                pass
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(json.dumps(out, ensure_ascii=False), next_prompt=next_prompt)

    # 动作后观测的条目上限: 够模型选下一个目标, 又不把工具结果撑大(模型自己 print
    # 全量 look() 常常 2~5K 字符, 这里封顶后约 800)
    _OBS_ITEMS = 12
    _OBS_LABEL = 24

    def _compact_obs(self):
        """动作后的紧凑观测: [{t, src, label, cls, x, y, rx, ry, click}], 只留选目标必需的字段。

        路由在 droid.observe() 里(_classify 决定跑哪些通道), 这里只负责截断成模型看得动的
        条数。旧实现在这里分 dump/look 两路 + canvas 特判, 还要额外付一次 screen_kind() 的
        dump_state 往返; canvas 页现在直接由 observe 返回空, 不再白跑一次全屏 look。"""
        import droid
        try:
            res = droid.observe()
        except Exception:
            return []
        items = []
        for i in res['items'][:self._OBS_ITEMS]:
            # t=显示文本(树节点的 text / yolo 的 OCR 文字), desc=contentDescription; 都没有才退 cls
            label = str(i.get('t') or i.get('desc') or i.get('cls') or '').strip()[:self._OBS_LABEL]
            items.append({'t': label, 'src': i['src'], 'label': label,
                          'cls': str(i.get('cls') or '')[:16],
                          'x': i['x'], 'y': i['y'], 'rx': i['rx'], 'ry': i['ry'],
                          'click': i['click']})
        return items

    @staticmethod
    def _act_proved_change(act, out):
        """动作自带后验是否已证明页面变了(此时再等页面稳定是纯浪费)。
        阈值用 phone_ledger.EVIDENCE_PCT(与账本同一口径): diff 超过它=产出新证据。
        ⚠️ tap/swipe 的 fg 只是"当前前台包名", 恒有——它不是变化证据。
        只有 launch 的 fg(目标包已在前台)才是。"""
        if act == 'launch' and out.get('fg'):
            return True
        if out.get('hit') is True:
            return True
        d = out.get('diff')
        if isinstance(d, str) and '%' in d:
            try:
                return float(d.split('%', 1)[0].rsplit(' ', 1)[-1]) > phone_ledger.EVIDENCE_PCT
            except (TypeError, ValueError):
                return False
        return False

    def do_ask_user(self, args, response):
        question = args.get("question", "请提供输入：")
        candidates = args.get("candidates", [])
        result = ask_user(question, candidates)
        yield f"Waiting for your answer ...\n"
        return StepOutcome(result, next_prompt="", should_exit=True)
    
    def do_file_patch(self, args, response):
        path = self._get_abs_path(args.get("path", ""))
        yield f"[Action] Patching file: {path}\n"
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")
        try: new_content = expand_file_refs(new_content, base_dir=self.cwd)
        except ValueError as e:
            yield f"[Status] ❌ 引用展开失败: {e}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        result = file_patch(path, old_content, new_content)
        yield f"\n{str(result)}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_file_write(self, args, response):
        '''用于对整个文件的大量处理，精细修改要用file_patch。
        需要将要写入的内容放在<file_content>标签内，或者放在代码块中'''
        path = self._get_abs_path(args.get("path", ""))
        mode = args.get("mode", "overwrite")  # overwrite/append/prepend
        action_str = {"prepend": "Prepending to", "append": "Appending to"}.get(mode, "Overwriting")
        yield f"[Action] {action_str} file: {os.path.basename(path)}\n"

        def extract_robust_content(text):
            tags = re.findall(r"<file_content[^>]*>(.*?)</file_content>", text, re.DOTALL)
            if tags: return tags[-1].strip()
            blocks = re.findall(r"```[^\n]*\n([\s\S]*?)```", text)
            if blocks: return blocks[-1].strip()
            return None
        
        content = args.get('content') or extract_robust_content(response.content)
        if not content:
            yield f"[Status] ❌ 失败: 未在回复中找到<file_content>代码块内容\n"
            return StepOutcome({"status": "error", "msg": "No content found. Blank is not supported. Put content inside <file_content>...</file_content> tags in your reply body before call file_write."}, next_prompt="\n")
        try:
            new_content = expand_file_refs(content, base_dir=self.cwd)
            if mode == "prepend":
                old = open(path, 'r', encoding="utf-8").read() if os.path.exists(path) else ""
                open(path, 'w', encoding="utf-8").write(new_content + old)
            else:
                with open(path, 'a' if mode == "append" else 'w', encoding="utf-8") as f: f.write(new_content)
            yield f"[Status] ✅ {mode.capitalize()} 成功 ({len(new_content)} bytes)\n"
            next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
            return StepOutcome({"status": "success", 'writed_bytes': len(new_content)}, next_prompt=next_prompt)
        except Exception as e:
            yield f"[Status] ❌ 写入异常: {str(e)}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        
    def do_file_read(self, args, response):
        '''读取文件内容。从第start行开始读取。如有keyword则返回第一个keyword(忽略大小写)周边内容'''
        path = self._get_abs_path(args.get("path", ""))
        yield f"\n[Action] Reading file: {path}\n"
        start = args.get("start", 1)
        count = args.get("count", 200)
        keyword = args.get("keyword")
        show_linenos = args.get("show_linenos", True)
        result = file_read(path, start=start, keyword=keyword,
                           count=count, show_linenos=show_linenos)
        if show_linenos and not result.startswith("Error:"): result = '由于设置了show_linenos，以下返回信息为：(行号|)内容 。\n' + result 
        if ' ... [TRUNCATED]' in result: result += '\n\n（某些行被截断，如需完整内容可改用 code_run 读取）'
        maxlen = 15000 // args.get('_tool_num', 1)
        result = smart_format(result, max_str_len=maxlen, omit_str='\n\n[omitted long content]\n\n')
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        log_memory_access(path)
        if 'memory' in path or 'sop' in path: 
            next_prompt += "\n[SYSTEM TIPS] 正在读取记忆或SOP文件，若决定按sop执行请提取sop中的关键点（特别是靠后的）update working memory."
        return StepOutcome(result, next_prompt=next_prompt)
    
    def _in_plan_mode(self): return self.working.get('in_plan_mode')
    def _exit_plan_mode(self): self.working.pop('in_plan_mode', None)
    def enter_plan_mode(self, plan_path): 
        self.working['in_plan_mode'] = plan_path; self.max_turns = 100
        self.print(f"[Info] Entered plan mode with plan file: {plan_path}")
        return plan_path
    def _check_plan_completion(self):
        if not os.path.isfile(p:=self._in_plan_mode() or ''): return None
        try: return len(re.findall(r'\[ \]', open(p, encoding='utf-8', errors='replace').read()))
        except: return None
    
    def do_update_working_checkpoint(self, args, response):
        '''为整个任务设定后续需要临时记忆的重点。'''
        key_info = args.get("key_info", "")
        related_sop = args.get("related_sop", "")
        if "key_info" in args: self.working['key_info'] = key_info
        if "related_sop" in args: self.working['related_sop'] = related_sop
        self.working['passed_sessions'] = 0
        yield f"[Info] Updated key_info and related_sop.\n"
        next_prompt = self._get_anchor_prompt(skip=args.get('_index', 0) > 0)
        #next_prompt += '\n[SYSTEM TIPS] 此函数一般在任务开始或中间时调用，如果任务已成功完成应该是start_long_term_update用于结算长期记忆。\n'
        return StepOutcome({"result": "working key_info updated"}, next_prompt=next_prompt)

    def _retry_or_exit(self, prompt):
        self._empty_ct = getattr(self, '_empty_ct', 0) + 1
        if self._empty_ct >= 3: return StepOutcome({}, should_exit=True)
        return StepOutcome({}, next_prompt=prompt)

    def do_no_tool(self, args, response):
        '''这是一个特殊工具，由引擎自主调用，不要包含在TOOLS_SCHEMA里。
        当模型在一轮中未显式调用任何工具时，由引擎自动触发。
        二次确认仅在回复几乎只包含<thinking>/<summary>和一段大代码块时触发。'''
        content = getattr(response, 'content', '') or ""
        thinking = getattr(response, 'thinking', '') or ""
        if not response or (not content.strip() and not thinking.strip()):
            yield "[Warn] LLM returned an empty response. Retrying...\n"
            return self._retry_or_exit("[System] Blank response, regenerate and tooluse")
        if '[!!! 流异常中断' in content[-100:] or '!!!Error:' in content[-100:]:
            return self._retry_or_exit("[System] Incomplete response. Regenerate and tooluse.")
        if 'max_tokens !!!]' in content[-100:]:
            return self._retry_or_exit("[System] max_tokens limit reached. Use multi small steps to do it.")
        
        if self._in_plan_mode() and any(kw in content for kw in ['任务完成', '全部完成', '已完成所有', '🏁']):
            if 'VERDICT' not in content and '[VERIFY]' not in content and '验证subagent' not in content:
                yield "[Warn] Plan模式完成声明拦截。\n"
                return StepOutcome({}, next_prompt="⛔ [验证拦截] 检测到你在plan模式下声称完成，但未执行[VERIFY]验证步骤。请先按plan_sop §四执行验证（实际工具调用取证），获得VERDICT后才能声称完成。")
            
        # 2. 检测"包含较大代码块但未调用工具"的情况
        # 关键特征：恰好1个大代码块 + 代码块直接结尾（后面只有空白）
        code_block_pattern = r"```[a-zA-Z0-9_]*\n[\s\S]{50,}?```"
        blocks = re.findall(code_block_pattern, content)
        if len(blocks) == 1:
            m = re.search(code_block_pattern, content)
            after_block = content[m.end():]
            if not after_block.strip():
                residual = content.replace(m.group(0), "")
                residual = re.sub(r"<thinking>[\s\S]*?</thinking>", "", residual, flags=re.IGNORECASE)
                residual = re.sub(r"<summary>[\s\S]*?</summary>", "", residual, flags=re.IGNORECASE)
                clean_residual = re.sub(r"\s+", "", residual)
                if len(clean_residual) <= 30:
                    yield "[Info] Detected large code block without tool call and no extra natural language. Requesting clarification.\n"
                    next_prompt = (
                        "[System] 检测到你在上一轮回复中主要内容是较大代码块，且本轮未调用任何工具。\n"
                        "如果这些代码需要执行、写入文件或进一步分析，请重新组织回复并显式调用相应工具"
                        "（例如：code_run、file_write、file_patch 等）；\n"
                        "如果只是向用户展示或讲解代码片段，请在回复中补充自然语言说明，"
                        "并明确是否还需要额外的实际操作。"
                    )
                    return StepOutcome({}, next_prompt=next_prompt)
                
        if self._in_plan_mode():
            remaining = self._check_plan_completion()
            if remaining == 0:
                self._exit_plan_mode(); yield "[Info] Plan完成：plan.md中0个[ ]残留，退出plan模式。\n"
        
        #yield "[Info] Final response to user.\n"
        return StepOutcome(response, next_prompt=None)
    
    def do_start_long_term_update(self, args, response):
        '''Agent觉得当前任务完成后有重要信息需要记忆时调用此工具。'''
        prompt = '''### [总结提炼经验] 既然你觉得当前任务有重要信息需要记忆，请提取最近一次任务中【事实验证成功且长期有效】的环境事实、用户偏好、重要步骤，更新记忆。
本工具是标记开启结算过程，若已在更新记忆过程或没有值得记忆的点，忽略本次调用。
**如果没有经验证的，未来能用上的信息，忽略本次调用！**
**只能提取行动验证成功的信息**：
- **环境事实**（路径/凭证/配置）→ `file_patch` 更新 L2，同步 L1
- **复杂任务经验**（关键坑点/前置条件/重要步骤）→ L3 精简 SOP（只记你被坑得多次重试的核心要点）
**禁止**：临时变量、具体推理过程、未验证信息、通用常识、你可以轻松复现的细节、只是做了但没有验证的信息
**操作**：严格遵循提供的L0的记忆更新SOP。本工具结果已附记忆库结构与 L1 现状——
**除非确知要改哪个文件，否则不要额外 `file_read` 去"看现有"**；直接判断类型 → 最小化
`file_patch` 更新 → 无新内容跳过，保证对记忆库最小局部修改。\n
''' + get_global_memory()
        yield "[Info] Start distilling good memory for long-term storage.\n"
        path = './memory/memory_management_sop.md'
        if os.path.exists(path): result = 'This is L0:\n' + file_read(path, show_linenos=False)
        else: result = "Memory Management SOP not found. Do not update memory."
        return StepOutcome(result, next_prompt=prompt)

    def _fold_earlier(self, lines):
        FALLBACK = '直接回答了用户问题'
        parts, cnt, last = [], 0, ''
        def flush():
            if cnt:
                if FALLBACK in last: parts.append(f'[Agent]（{cnt} turns）')
                else: parts.append(f'{last}（{cnt} turns）')
        for line in lines:
            if line.startswith('[USER]'):
                flush(); parts.append(line); cnt = 0; last = ''
            else: cnt += 1; last = line
        flush()
        return "\n".join(parts[-70:])

    def _get_anchor_prompt(self, skip=False):
        if skip: return "\n"
        h = self.history_info; W = 30
        earlier = f'<earlier_context>\n{self._fold_earlier(h[:-W])}\n</earlier_context>\n' if len(h) > W else ""
        h_str = "\n".join(h[-W:])
        prompt = f"\n### [WORKING MEMORY]\n{earlier}<history>\n{h_str}\n</history>"
        prompt += f"\nCurrent turn: {self.current_turn}\n"
        if self.working.get('key_info'): prompt += f"\n<key_info>{self.working.get('key_info')}</key_info>"
        if self.working.get('related_sop'): prompt += f"\n有不清晰的地方请再次读取{self.working.get('related_sop')}"
        if getattr(self.parent, 'verbose', False): self.print(prompt)
        return prompt
    
    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        _c = re.sub(r'```.*?```|<thinking>.*?</thinking>', '', response.content, flags=re.DOTALL)
        rsumm = re.search(r"<summary>(.*?)</summary>", _c, re.DOTALL)
        if rsumm: summary = rsumm.group(1).strip()
        else:
            tc = tool_calls[0]; tool_name, args = tc['tool_name'], tc['args']   # at least one because no_tool
            clean_args = {k: v for k, v in args.items() if not k.startswith('_')}
            summary = f"调用工具{tool_name}, args: {clean_args}"
            if tool_name == 'no_tool': summary = "直接回答了用户问题"
            next_prompt += "\n\n\n[SYSTEM] 必须在回复文本中包含<summary>！\n\n"
            summary = smart_format(summary.replace('\n', ''), max_str_len=40)
        summary = smart_format(summary.replace('\n', ''), max_str_len=80)
        self.history_info.append(f'[Agent] {summary}')
        _plan = self._in_plan_mode()

        if turn % 75 == 0 and (not _plan):
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。必须总结情况进行ask_user，不允许继续重试。"
        elif turn % 7 == 0:
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。禁止无效重试。若无有效进展，必须切换策略：1. 探测物理边界 2. 请求用户协助。如有需要，可调用 update_working_checkpoint 保存关键上下文。"
        elif turn % 10 == 0: next_prompt += get_global_memory()

        _guard = phone_ledger.ACTIVE.hint()   # 循环守卫(SPEC W3 提示级): 动作等价/界面粘滞等机械信号; 无信号零注入
        if _guard: next_prompt += f"\n\n{_guard}\n"

        if _plan and turn >= 10 and turn % 5 == 0:
            next_prompt = f"[Plan Hint] 正在计划模式。必须 file_read({_plan}) 确认当前步骤，回复开头引用：📌 当前步骤：...\n\n" + next_prompt
        if _plan and turn >= 120: next_prompt += f"\n\n[DANGER] Plan模式已运行 {turn} 轮，已达上限。必须 ask_user 汇报进度并确认是否继续。"

        injkeyinfo = consume_file(self.parent.task_dir, '_keyinfo')
        injprompt = consume_file(self.parent.task_dir, '_intervene')
        if injkeyinfo: self.working['key_info'] = self.working.get('key_info', '') + f"\n[MASTER] {injkeyinfo}"
        if injprompt: next_prompt += f"\n\n[MASTER] {injprompt}\n"
        next_prompt += lang_directive()   # 每轮重注语言指令: 中途 /lang 切换即刻生效, 压过历史语言惯性
        for hook in list(getattr(self.parent, '_turn_end_hooks', {}).values()): hook(locals())  # current readonly
        return next_prompt

def lang_directive():
    """返回当前语言的 [LANG] 回复指令(实时读 GA_LANG, 用于压过历史语言惯性; 显式 /lang 切换永远优先)。
    GA_LANG 由 UI /lang(或首启 navigator.language)与系统 locale 决定。"""
    return ("\n[LANG] Respond to the user in English, regardless of the language of context or tool output (verbatim quotes excepted).\n"
            if os.environ.get('GA_LANG', '') == 'en'
            else "\n[LANG] 用简体中文回复用户，无论上下文或工具输出是什么语言（逐字引用原文除外）。\n")


def get_global_memory():
    prompt = "\n"
    try:
        suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''
        with open(os.path.join(script_dir, 'memory/global_mem_insight.txt'), 'r', encoding='utf-8', errors='replace') as f: insight = f.read()
        with open(os.path.join(script_dir, f'assets/insight_fixed_structure{suffix}.txt'), 'r', encoding='utf-8') as f: structure = f.read()
        prompt += f'cwd = {os.path.join(script_dir, "temp")} (./)\n'
        prompt += f"\n[Memory] (../memory)\n"
        prompt += structure + '\n../memory/global_mem_insight.txt:\n'
        prompt += insight + "\n"
    except FileNotFoundError: pass
    return prompt
