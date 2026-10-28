"""droid.ask_vision 必须优先使用当前任务的 active backend, 而不是要求 vision_api。"""
import sys
from pathlib import Path

import types

import numpy as np
import pytest
from unittest.mock import patch

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import droid
import ga_android
import vision_llm


def test_ask_vision_uses_the_active_backend(monkeypatch):
    fake = object()
    calls = []

    def _ask(backend, image, prompt, **kw):
        calls.append((backend, prompt, kw))
        return 'active ok'

    monkeypatch.setattr(vision_llm, 'ask_with_backend', _ask)
    droid.set_vision_backend(fake)
    try:
        out = droid.ask_vision(np.zeros((20, 20, 3), dtype=np.uint8), 'q')
    finally:
        droid.set_vision_backend(None)
    assert out == 'active ok'
    assert calls and calls[0][0] is fake


def test_active_backend_failure_is_counted_for_the_fuse(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError('upstream rejected image')

    monkeypatch.setattr(vision_llm, 'ask_with_backend', _boom)
    droid.set_vision_backend(object())
    try:
        with pytest.raises(RuntimeError):
            droid.ask_vision(np.zeros((20, 20, 3), dtype=np.uint8), 'q')
    finally:
        droid.set_vision_backend(None)
    assert droid._VISION_FAILS['n'] == 1


def test_vision_backend_comes_from_the_active_agent():
    sentinel = object()
    h = object.__new__(ga_android.GenericAgentHandler)
    h.parent = types.SimpleNamespace(llmclient=types.SimpleNamespace(backend=sentinel))
    assert h._vision_backend() is sentinel
    h.parent = types.SimpleNamespace(llmclient=None)
    assert h._vision_backend() is None


def test_do_code_run_passes_the_active_backend(monkeypatch):
    sentinel = object()
    h = object.__new__(ga_android.GenericAgentHandler)
    h.cwd = '.'
    h.working = {}
    h.history_info = []
    h.code_stop_signal = []
    h.current_turn = 1
    h.print = lambda *a, **k: None
    h.parent = types.SimpleNamespace(
        llmclient=types.SimpleNamespace(backend=sentinel),
        task_dir=None, verbose=False, _turn_end_hooks={})
    captured = {}

    def _fake_code_run(code, code_type, timeout, cwd, **kw):
        captured.update(kw)
        yield 'x'
        return {'status': 'success', 'stdout': '', 'exit_code': 0}

    monkeypatch.setattr(ga_android, 'code_run', _fake_code_run)
    gen = ga_android.GenericAgentHandler.do_code_run(
        h, {'script': 'x'}, types.SimpleNamespace(content=''))
    try:
        while True:
            next(gen)
    except StopIteration as e:
        out = e.value
    assert out.data['stdout'] == ''
    assert captured.get('vision_backend') is sentinel


def test_code_run_sets_the_active_backend_in_the_exec_thread():
    sentinel = object()
    gen = ga_android.code_run(
        "import droid\nprint(droid._vision_backend() is not None)",
        vision_backend=sentinel, timeout=10)
    out = None
    try:
        while True:
            next(gen)
    except StopIteration as e:
        out = e.value
    assert out['exit_code'] == 0
    assert 'True' in out['stdout']
    assert droid._vision_backend() is None       # 执行线程外的 TLS 不受影响
