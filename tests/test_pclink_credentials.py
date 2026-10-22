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
