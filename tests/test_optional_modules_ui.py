import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

WEB = Path(__file__).parents[1] / 'app/src/main/assets/gacore/webui'


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_profile_import_requires_save_and_provider_remains_available(language):
    errors, outgoing = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 390, 'height': 844}, locale=language)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http**://**', lambda route: (outgoing.append(route.request.url), route.abort()))
        page.add_init_script('''
          window.savedProfiles=[]; window.kv={};
          const services={voice:{url:'wss://voice.example.com/asr',has_token:true}};
          window.GA=new Proxy({
            ready:()=> 'nokey', poll:()=> '{}', isDark:()=>false,
            appVersion:()=> '{"name":"2.33.1","code":134}',
            send:(command)=>{
              if(command==='/config')return '{"ok":true,"items":[]}';
              if(command==='/integrations.get')return JSON.stringify(services);
              if(command.startsWith('/integrations.save ')){
                savedProfiles.push(JSON.parse(command.slice(19)));return '{"ok":true}';
              }
              if(command.startsWith('/kv.get '))return kv[command.slice(8)]||'';
              if(command.startsWith('/kv.set ')){const rest=command.slice(8),i=rest.indexOf(' ');kv[rest.slice(0,i)]=rest.slice(i+1);return 'ok'}
              return '{}';
            }
          },{get:(target,key)=>target[key]||(()=> '{}')});
        ''')
        page.goto((WEB / 'index.html').as_uri())
        page.locator('.pcAgree').click()
        page.evaluate('openSettings();openIntegrations()')
        card = page.locator('.modalCard').filter(has=page.locator('input[type=file]'))
        assert card.locator('input[type=password]').evaluate_all('(xs)=>xs.every(x=>!x.value)')
        profile = {'schema': 1, 'integrations': {'voice': {'url': 'wss://speech.example.com/asr', 'token': 'sample-user-token', 'model': 'asr'}}}
        card.locator('input[type=file]').set_input_files({'name':'connection.json','mimeType':'application/json','buffer':json.dumps(profile).encode()})
        expect(card.locator('input[type=password][placeholder]')).to_have_value('sample-user-token')
        assert page.evaluate('savedProfiles.length') == 0
        card.get_by_role('button', name='保存' if language == 'zh' else 'Save', exact=True).click()
        assert page.evaluate('savedProfiles[0].voice') == profile['integrations']['voice']
        page.evaluate('openIntegrations()')
        page.get_by_role('button', name='模型服务商 / GA Plan' if language == 'zh' else 'Model provider / GA Plan', exact=True).click()
        assert page.locator('#provListPanel').is_visible()
        assert not errors
        assert not outgoing
        browser.close()
