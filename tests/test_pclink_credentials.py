import asyncio
import importlib.util
from pathlib import Path
import sys
import types

import pytest

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))


def load_link():
    spec = importlib.util.spec_from_file_location('isolated_pclink_credentials', CORE / 'pclink.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_relay_key_cannot_sign():
    import p2p_ws_client as relay
    assert relay.DEFAULT_ACCESS_KEY == ''
    with pytest.raises(ValueError, match='credential'):
        relay.signed_url('wss://relay.example/ws', 'ws', 'room')
    assert 'sample-credential' not in relay.signed_url('wss://relay.example/ws', 'ws', 'room', 'sample-credential')


@pytest.mark.parametrize('current', [None, {'url': 'wss://other.example/ws', 'token': 'sample-new'}])
def test_disabling_or_changing_relay_closes_old_socket_without_reconnect(monkeypatch, current):
    module = load_link()
    closed = []
    async def close():
        closed.append(True)
    module._sock = types.SimpleNamespace(close=close)
    module._sock_config = {'url': 'wss://old.example/ws', 'token': 'sample-old'}
    monkeypatch.setattr(module.service_config, 'load_config', lambda: {'pclink': current} if current else {})
    monkeypatch.setattr(module, '_paired', lambda: True)
    async def forbidden(*a, **k):
        pytest.fail('must not send a credential to the saved relay')
    monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(
        connect_saved=forbidden, load_room=lambda *a, **k: {'signal_url': 'wss://old.example/ws'}))
    async def scenario():
        task = asyncio.create_task(module._keeper())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert closed and module._sock is None


def test_stale_socket_cannot_send_after_configuration_change(monkeypatch):
    module = load_link()
    module._sock = object()
    module._sock_config = {'url': 'wss://old.example/ws', 'token': 'sample-old'}
    monkeypatch.setattr(module.service_config, 'load_config', lambda: {})
    with pytest.raises(RuntimeError, match='disabled'):
        asyncio.run(module._api('GET', '/api/peers', ''))


class _Sock:
    def __init__(self, name):
        self.name, self.closed = name, False

    async def recv(self):
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


def _race_link(monkeypatch, tmp_path):
    """Keeper connects to the saved room only after `release` is set, so tests can interleave pair/unpair."""
    import json
    module = load_link()
    config = {'url': 'wss://relay.example/ws', 'token': 'sample-user'}
    monkeypatch.setattr(module.service_config, 'load_config', lambda: {'pclink': config})
    rooms = tmp_path / 'rooms.json'
    rooms.write_text(json.dumps({module.NAME: {'signal_url': config['url'], 'room': 'old-room'}}))
    monkeypatch.setattr(module, 'ROOMS', str(rooms))
    state = {'started': asyncio.Event(), 'release': asyncio.Event(), 'old': _Sock('old'), 'new': _Sock('new')}
    def load_room(name, path):
        return json.loads(Path(path).read_text())[name]
    async def connect_saved(name, path, access_key):
        state['started'].set()
        await state['release'].wait()
        return state['old']
    async def connect_code(url, code, name, rooms_file, access_key):
        Path(rooms_file).write_text(json.dumps({name: {'signal_url': url, 'room': 'new-room'}}))
        return state['new']
    monkeypatch.setitem(sys.modules, 'p2p_ws_client', types.SimpleNamespace(
        load_room=load_room, connect_saved=connect_saved, connect_code=connect_code))
    return module, state


def test_keeper_connect_finishing_after_unpair_is_discarded(monkeypatch, tmp_path):
    module, state = _race_link(monkeypatch, tmp_path)
    async def scenario():
        keeper = asyncio.create_task(module._keeper())
        await asyncio.wait_for(state['started'].wait(), 1)
        await module._unpair()                     # user unlinks while the reconnect is still in flight
        state['release'].set()
        await asyncio.sleep(0.05)
        seen = (module._sock, state['old'].closed, module._paired())   # before teardown cancels receivers
        keeper.cancel()
        return seen
    assert asyncio.run(scenario()) == (None, True, False)


def test_pairing_is_not_replaced_by_a_late_keeper_connect(monkeypatch, tmp_path):
    module, state = _race_link(monkeypatch, tmp_path)
    async def scenario():
        keeper = asyncio.create_task(module._keeper())
        await asyncio.wait_for(state['started'].wait(), 1)
        await module._pair('123456789')            # new pairing completes before the old-room reconnect
        state['release'].set()
        await asyncio.sleep(0.05)
        seen = (module._sock is state['new'], state['old'].closed, state['new'].closed)
        keeper.cancel()
        return seen
    assert asyncio.run(scenario()) == (True, True, False)
