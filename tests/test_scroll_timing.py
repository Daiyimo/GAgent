"""The native swipe response acknowledges dispatch before the gesture ends."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'app/src/main/assets/gacore'))
import droid


@pytest.fixture
def asynchronous_screen(monkeypatch):
    state = {'now': 0.0, 'ends_at': 0.0, 'actions': [], 'observations': []}
    screen = dict(w=120, h=240, rot=0, pkg='com.android.settings')

    def dispatch(**body):
        assert state['now'] >= state['ends_at'], 'new gesture cancels the active one'
        state['ends_at'] = state['now'] + body['dur'] / 1000.0
        state['actions'].append(body)
        return {'ok': True}

    def sleep(seconds):
        state['now'] += seconds

    def observe(kind):
        if state['actions']:
            state['observations'].append((kind, state['now']))
        return bool(state['actions'])

    def dump():
        prefix = 'after' if observe('dump') else 'before'
        return [{'t': prefix + str(i)} for i in range(4)]

    def shot(**kwargs):
        return np.full((240, 120, 3), 255 if observe('shot') else 0, dtype=np.uint8)

    monkeypatch.setattr(droid, 'ping', lambda: dict(screen))
    monkeypatch.setattr(droid, '_act', dispatch)
    monkeypatch.setattr(droid, 'dump', dump)
    monkeypatch.setattr(droid, 'shot', shot)
    monkeypatch.setattr(droid.time, 'sleep', sleep)
    return state


@pytest.mark.parametrize('duration,settle', [(2000, .5), (260, 0)])
def test_scroll_observes_after_gesture_duration_and_settlement(asynchronous_screen, duration, settle):
    state = asynchronous_screen
    result = droid.scroll('up', dur=duration, settle=settle)
    assert result['scrolled'] is True
    assert {kind for kind, _ in state['observations']} == {'dump', 'shot'}
    assert all(at >= state['ends_at'] + settle for _, at in state['observations'])


def test_scroll_segments_do_not_cancel_each_other_without_verification(asynchronous_screen):
    result = droid.scroll('down', dur=900, times=2, verify=False, settle=0)
    assert len(asynchronous_screen['actions']) == 2
    assert asynchronous_screen['now'] >= asynchronous_screen['ends_at']
    assert result['performed'] is True
    assert result['verified'] is False


@pytest.mark.parametrize('finger,view,axis,sign', [
    ('up', 'down', 'y', -1), ('down', 'up', 'y', 1),
    ('left', 'right', 'x', -1), ('right', 'left', 'x', 1),
])
@pytest.mark.parametrize('verified', [True, False])
def test_scroll_feedback_distinguishes_finger_and_view_direction(
        asynchronous_screen, finger, view, axis, sign, verified):
    result = droid.scroll(finger, verify=verified)
    action = asynchronous_screen['actions'][0]
    assert (action[axis + '2'] - action[axis + '1']) * sign > 0
    assert result['finger_direction'] == finger
    assert result['view_direction'] == view
    # Direction is dispatch metadata, not proof of progress.
    if not verified:
        assert result['verified'] is False


def test_uncertain_scroll_still_reports_dispatched_direction(asynchronous_screen, monkeypatch):
    monkeypatch.setattr(droid, 'dump', lambda: [])
    monkeypatch.setattr(droid, 'shot', lambda **kwargs: None)
    result = droid.scroll('down')
    assert result['scrolled'] is False and result['uncertain'] is True
    assert result['finger_direction'] == 'down'
    assert result['view_direction'] == 'up'
