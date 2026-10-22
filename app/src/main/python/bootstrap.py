# APK内固定层: 只负责把可写目录下的 android_entry 接入, 其余逻辑全在 filesDir/ga (py端可热更新)
# 不变量: _INITED 由本层在 init 成功后盖章; 缺章 ⇒ 该模块实例从未 init(如 sys.modules 被清后重导入) ⇒ 自愈复位
import os, sys, threading

_ga_dir = None
_heal_lock = threading.Lock()   # 多线程桥调用(WebUI/AlarmWorker/NotifWorker)并发撞缺章模块时, init 只跑一次

def init(ga_dir, package_name=""):
    if package_name: os.environ["GA_PACKAGE"] = package_name
    global _ga_dir
    _ga_dir = ga_dir
    if ga_dir not in sys.path: sys.path.insert(0, ga_dir)
    import android_entry
    r = android_entry.init(ga_dir)
    android_entry._INITED = True
    return r

def call(fn, *args):
    if _ga_dir and _ga_dir not in sys.path: sys.path.insert(0, _ga_dir)
    import android_entry
    if _ga_dir and not getattr(android_entry, '_INITED', False):   # 重导入的新模块: GA_DIR/猴补丁/迁移全丢 → 整体重跑 init(对新模块幂等)
        with _heal_lock:
            if not getattr(android_entry, '_INITED', False):
                init(_ga_dir)
    return str(getattr(android_entry, fn)(*args))
