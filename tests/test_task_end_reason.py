"""A user stop or a dead worker must not be reported as a finished task by the floating capsule."""
import json
import queue
import sys
import threading
from pathlib import Path

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
FLOAT = Path(__file__).parents[1] / 'app/src/main/java/com/ljq/ga/FloatService.kt'


class _Agent:
    def __init__(self):
        self.aborted = False
        self.history = []

    def abort(self):
        self.aborted = True


@pytest.fixture
def entry(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    import android_entry as entry
    for name in ('_save_hist', '_persist_convo'):
        monkeypatch.setattr(entry, name, lambda *a, **k: None)
    monkeypatch.setattr(entry, '_hist', [])
    monkeypatch.setattr(entry.patches, 'abort_streams', lambda s: None)
    return entry


def _running(entry, monkeypatch, cid):
    sess = entry._Sess(cid)
    sess.agent = _Agent()
    sess.state.update(running=True, status='思考中', steps=[], final='', prompt='p', gen=entry._next_gen(), end='')
    monkeypatch.setattr(entry, '_resolve_cid', lambda c, explicit=False, build=False: (sess, None))
    return sess


def _finish(entry, sess, item):
    q = queue.Queue()
    q.put({'turn': 2, 'outputs': ['step text']})
    q.put(dict(item, turn=2, outputs=['step text']))
    t = threading.Thread(target=entry._drain, args=(q, sess.state['gen'], sess, 'c1'))
    t.start(); t.join(5)
    assert not t.is_alive()
    return json.loads(entry._poll_for(sess, '0', summary=True))


def test_normal_completion_is_done(entry, monkeypatch):
    poll = _finish(entry, _running(entry, monkeypatch, 'ga_done'), {'done': 'all good'})
    assert poll['end'] == 'done' and poll['status'].startswith('完成')


def test_user_stop_is_reported_as_stopped(entry, monkeypatch):
    sess = _running(entry, monkeypatch, 'ga_stop')
    entry.abort2('c1')
    assert sess.agent.aborted
    poll = _finish(entry, sess, {'done': 'partial'})
    assert poll['end'] == 'stopped' and poll['status'].startswith('已停止') and not poll['running']


def test_stop_after_finish_does_not_relabel(entry, monkeypatch):
    sess = _running(entry, monkeypatch, 'ga_late')
    _finish(entry, sess, {'done': 'all good'})
    entry.abort2('c1')
    assert json.loads(entry._poll_for(sess, '0', summary=True))['end'] == 'done'


def test_error_final_is_reported_as_error(entry, monkeypatch):
    poll = _finish(entry, _running(entry, monkeypatch, 'ga_err'), {'done': '!!!Error: provider unreachable'})
    assert poll['end'] == 'error' and poll['status'].startswith('出错')


def test_capsule_never_shows_done_for_stop_or_error():
    text = FLOAT.read_text(encoding='utf-8')
    assert 'val done = ended && !stopped && !failed' in text
    assert 's("■ 已停止", "■ Stopped")' in text and 's("⚠ 出错", "⚠ Error")' in text
    assert 'x.optString("end") != "stopped") notifyTaskEnd' in text
