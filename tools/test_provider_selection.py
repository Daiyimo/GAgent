"""Exercise the real slash-command method without starting the Android runtime."""
import ast
import json
from pathlib import Path
import queue
import re
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore/agentmain.py'
tree = ast.parse(SOURCE.read_text('utf-8'))
method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_handle_slash_cmd')
namespace = dict(json=json, re=re)
exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)


class Agent:
    command = namespace['_handle_slash_cmd']

    def __init__(self, names):
        self.llmclients = [SimpleNamespace(backend=SimpleNamespace(name=n, model='original')) for n in names]
        self.llmclient = self.llmclients[0]
        self.selected = None

    def load_llm_sessions(self):
        pass

    def next_llm(self, index):
        self.selected = index
        self.llmclient = self.llmclients[index]

    def get_llm_name(self, client=None, model=False):
        backend = (client or self.llmclient).backend
        return backend.model if model else 'NativeOAISession/' + backend.name


class ProviderSelection(unittest.TestCase):
    def select(self, names, target, expected):
        agent = Agent(names)
        output = queue.Queue()
        agent.command('/llm ' + json.dumps(dict(name=target, model='requested')), output)
        self.assertEqual(agent.selected, expected)
        for index, client in enumerate(agent.llmclients):
            self.assertEqual(client.backend.model, 'requested' if index == expected else 'original')
        self.assertEqual(output.get_nowait()['source'], 'system')

    def test_exact_short_name_beats_earlier_prefix(self):
        self.select(['R33-step5', 'R33-step'], 'R33-step', 1)

    def test_ambiguous_abbreviation_does_not_switch_or_mutate(self):
        self.select(['alpha-east', 'alpha-west'], 'alpha', None)

    def test_unique_abbreviation_still_works(self):
        self.select(['alpha-east', 'beta-west'], 'east', 0)

    def test_duplicate_exact_names_require_index(self):
        self.select(['alpha', 'alpha'], 'alpha', None)

    def test_numeric_index_still_works(self):
        self.select(['alpha', 'beta'], '1', 1)

    def test_empty_and_missing_names_do_not_switch(self):
        for name in ('', 'missing'):
            self.select(['alpha', 'beta'], name, None)


if __name__ == '__main__':
    unittest.main()
