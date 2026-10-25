"""A saved provider change (e.g. reasoning effort) must reach every conversation's agent, not just the first."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

CORE = Path(__file__).parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))


def test_llm_switch_makes_the_agent_rebuild_its_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv('GA_DIR', str(tmp_path))
    import android_entry as entry
    queued = []
    agent = SimpleNamespace(llmclients=['stale'], put_task=lambda text: queued.append(text) or 'q')
    entry._queue_control(agent, '/session.temperature=1')
    assert hasattr(agent, 'llmclients')                       # other control commands keep the session list
    entry._queue_control(agent, '/llm {"name": "GLM", "model": "glm-5.3-flash"}')
    assert not hasattr(agent, 'llmclients')                   # load_llm_sessions will rebuild from the saved config
    assert queued == ['/session.temperature=1', '/llm {"name": "GLM", "model": "glm-5.3-flash"}']


def test_choosing_an_effort_saves_then_reapplies_the_active_model():
    web = Path(__file__).parents[1] / 'app/src/main/assets/gacore/webui'
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.sent=[];
          window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>false, abort:()=>'',
            send:(c)=>{sent.push(c);return c==='/config'?'{"ok":true,"items":[]}':c.startsWith('/kv.get ')?'':'{"ok":true}'}
          },{get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((web / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.evaluate("providers=[{id:'p1',name:'GLM',type:'claude',apikey:'k',apibase:'https://x.test',model:'glm-5.3-flash',models:['glm-5.3-flash']}];"
                      "active={pid:'p1',model:'glm-5.3-flash'};sent.length=0;selectEff('low');selectEff('')")
        cmds = [c.split(' ')[0] for c in page.evaluate('sent') if c.startswith(('/provider.save', '/llm'))]
        assert cmds == ['/provider.save', '/llm', '/provider.save', '/llm']
        saves = [json.loads(c.split(' ', 1)[1]) for c in page.evaluate('sent') if c.startswith('/provider.save')]
        assert saves[0].get('reasoning_effort') == 'low' and 'reasoning_effort' not in saves[1]
        switch = json.loads([c for c in page.evaluate('sent') if c.startswith('/llm')][-1][5:])
        assert switch == {'name': 'GLM', 'model': 'glm-5.3-flash'}
        assert not errors
        browser.close()


def test_settings_row_says_repair_when_the_phone_revoked_self_adb_trust():
    web = Path(__file__).parents[1] / 'app/src/main/assets/gacore/webui'
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en')
        page.route('http**://**', lambda route: route.abort())
        page.add_init_script('''
          window.adb={wifi:true,paired:true,connected:false,repair:true};
          window.GA=new Proxy({ready:()=> 'ok', poll:()=> '{}', isDark:()=>false, adbSelfStatus:()=>JSON.stringify(adb),
            send:(c)=>c==='/config'?'{"ok":true,"items":[]}':c.startsWith('/kv.get ')?'':'{}'
          },{get:(t,k)=>t[k]||(()=> '{}')});
        ''')
        page.goto((web / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.evaluate('openSettings();refreshAdb()')
        assert page.locator('#adbVal').inner_text() == 'Re-pair needed'
        page.evaluate("adb.repair=false;refreshAdb()")
        assert page.locator('#adbVal').inner_text() == 'Not connected'
        page.evaluate("adb.connected=true;refreshAdb()")
        assert page.locator('#adbVal').inner_text() == 'Connected'
        browser.close()
