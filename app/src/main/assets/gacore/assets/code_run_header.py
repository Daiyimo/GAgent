import sys, os, json, re, time, subprocess
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'memory'))
_r = subprocess.run
def _d(b):
    if not b: return ''
    if isinstance(b, str): return b
    try: return b.decode()
    except: return b.decode('gbk', 'replace')
def _run(*a, **k):
    t = k.pop('text', 0) | k.pop('universal_newlines', 0)
    enc = k.pop('encoding', None)
    k.pop('errors', None)
    if enc: t = 1
    if t and isinstance(k.get('input'), str):
        k['input'] = k['input'].encode()
    r = _r(*a, **k)
    if t:
        if r.stdout is not None: r.stdout = _d(r.stdout)
        if r.stderr is not None: r.stderr = _d(r.stderr)
    return r
subprocess.run = _run
_Pi = subprocess.Popen.__init__
def _pinit(self, *a, **k):
    if os.name == 'nt': k['creationflags'] = (k.get('creationflags') or 0) | 0x08000000
    _Pi(self, *a, **k)
subprocess.Popen.__init__ = _pinit
sys.excepthook = lambda t, v, tb: (sys.__excepthook__(t, v, tb), print(f"\n[Agent Hint]: NO GUESSING! You MUST probe first. If missing common package, pip.")) if issubclass(t, (ImportError, AttributeError)) else sys.__excepthook__(t, v, tb)
# 每次 code_run 都是全新命名空间(不跨轮保留变量/导入). 手机 GUI 原语 droid 常驻预导入: 74 个真机 run 里 145 次报错中大半是「忘了 import droid /
# 上一轮的变量不在了」, 每次浪费一整轮(~10-30s). 导入失败(PC 侧/总线未起)静默跳过, 不影响纯计算脚本.
try:
    import droid  # noqa: F401
except Exception:
    pass
