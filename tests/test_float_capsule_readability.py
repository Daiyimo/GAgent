"""Floating capsule text must stay readable at the user's transparency preference."""
from pathlib import Path
import re

SRC = Path(__file__).resolve().parents[1] / 'app/src/main/java/com/ljq/ga/FloatService.kt'


def _lum(rgb):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _hex(code):
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


def test_preference_fades_body_not_text():
    text = SRC.read_text(encoding='utf-8')
    body = re.search(r'private fun styleBody\(.*?\n    \}', text, re.S)
    assert body, 'styleBody not found'
    assert 'tv.alpha = 1f' in body.group(0) and 'tv.background?.alpha' in body.group(0)
    assert 'setShadowLayer' in body.group(0)          # white text keeps a dark halo on any wallpaper
    assert not re.search(r'tv\.alpha = f\b|alpha = floatOpacity\(\)', text)


def test_dark_done_text_is_only_used_on_a_solid_enough_body():
    text = SRC.read_text(encoding='utf-8')
    solid = float(re.search(r'SOLID_BODY = ([0-9.]+)f', text).group(1))
    green = _hex(re.search(r'C_DONE = Color.parseColor\("#(\w{6})"\)', text).group(1))
    ink = _hex('0B1F12')
    for wallpaper in [(0, 0, 0), (255, 255, 255), (128, 128, 128)]:
        body = tuple(round(g * solid + w * (1 - solid)) for g, w in zip(green, wallpaper))
        assert _ratio(ink, body) >= 4.5, (wallpaper, _ratio(ink, body))
