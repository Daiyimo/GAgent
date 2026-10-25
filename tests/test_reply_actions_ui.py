"""Reply action row: no dead buttons, and the step count reads correctly."""
from playwright.sync_api import sync_playwright

from test_motion_navigation_ui import open_page


def test_action_row_has_no_placeholder_translate_and_counts_steps():
    with sync_playwright() as engine:
        browser, page, errors = open_page(engine)
        rows = page.evaluate('''()=>[1,2].map(n=>{newTask('p','m',Date.now());
          task.steps=Array.from({length:n},()=>({_text:'done'}));addActions();
          const r=task.box.querySelector('.msgAct');
          return [[...r.querySelectorAll('button')].map(b=>b.getAttribute('aria-label')),r.querySelector('.tm').textContent]})''')
        for labels, _ in rows:
            assert 'Translate' not in labels and 'Read aloud' in labels
        assert [count for _, count in rows] == ['1 step', '2 steps']
        assert not errors
        browser.close()
