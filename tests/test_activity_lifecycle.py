"""Source guard: a recreated MainActivity must not leave its chat WebView running."""
from pathlib import Path
import re

SRC = Path(__file__).resolve().parents[1] / 'app/src/main/java/com/ljq/ga/MainActivity.kt'


def test_on_destroy_releases_main_webview():
    text = SRC.read_text(encoding='utf-8')
    body = re.search(r'override fun onDestroy\(\) \{(.*?)\n    \}', text, re.S)
    assert body, 'MainActivity.onDestroy not found'
    assert 'web.destroy()' in body.group(1)
    assert 'removeView(web)' in body.group(1)
