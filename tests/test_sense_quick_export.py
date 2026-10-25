"""Source guard: other apps must not be able to make GAgent start the microphone."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'app'
ANDROID = '{http://schemas.android.com/apk/res/android}'


def _activity(name):
    root = ET.parse(APP / 'src/main/AndroidManifest.xml').getroot()
    return next(a for a in root.iter('activity') if a.get(ANDROID + 'name') == name)


def test_quick_record_activity_is_not_exported():
    # launchedFromUid is -1 for callers that do not share their identity, so the in-code check cannot stand alone.
    assert _activity('.SenseQuickActivity').get(ANDROID + 'exported') == 'false'


def test_static_shortcuts_target_this_app():
    gradle = (APP / 'build.gradle').read_text(encoding='utf-8')
    app_id = re.search(r'applicationId "([^"]+)"', gradle).group(1)
    suffix = re.search(r'applicationIdSuffix "([^"]+)"', gradle).group(1)
    for res, pkg in (('src/main', app_id), ('src/debug', app_id + suffix)):
        intents = ET.parse(APP / res / 'res/xml/shortcuts.xml').getroot().iter('intent')
        assert {i.get(ANDROID + 'targetPackage') for i in intents} == {pkg}
