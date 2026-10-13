import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from core import Step, Workflow
from desktop import Desktop, keyboard
from runner import Runner


class QuickFeatureTests(unittest.TestCase):
    def test_replace_selects_original_before_pasting(self):
        events = []
        desktop = Desktop.__new__(Desktop)
        desktop.lock = threading.RLock()
        desktop.clipboard = SimpleNamespace(set=lambda text: events.append(('text', text)))
        desktop.keyboard = SimpleNamespace(press=lambda key: events.append(('press', key)),
                                           release=lambda key: events.append(('release', key)))
        desktop.perform(Step('paste', {'text': '{{code}}'}), '142716')
        self.assertEqual(events, [('text', '142716'), ('press', keyboard.Key.ctrl),
                                 ('press', 'a'), ('release', 'a'), ('press', 'v'),
                                 ('release', 'v'), ('release', keyboard.Key.ctrl)])
        events.clear()
        desktop.perform(Step('paste', {'text': '追加', 'replace_existing': False}), None)
        self.assertNotIn(('press', 'a'), events)

    def test_repetitions_reset_first_code_and_run_exact_count(self):
        first = Step('wait', wait=0)
        read = Step('read', {'source': 'ema_text', 'retry_from': first.id}, wait=0)
        workflow = Workflow('重复', [first, read, Step('paste', {'text': '{{code}}'}, wait=0)], start_delay=0)
        workflow.repetitions = 3
        pasted = []
        desktop = SimpleNamespace(read=lambda data: '验证码为：142716。', release_all=lambda: None,
                                  perform=lambda step, code, phone: pasted.append(code) if step.kind == 'paste' else None)
        runner = Runner(workflow, desktop)
        runner.run()
        self.assertEqual(runner.state, 'completed')
        self.assertEqual(pasted, ['142716'] * 3)

    def test_repeat_count_saved_and_invalid_counts_rejected(self):
        workflow = Workflow('重复', [Step('wait', wait=0)])
        workflow.repetitions = 3
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'flow.json'
            workflow.save(file)
            self.assertEqual(Workflow.load(file).repetitions, 3)
        for count in [0, -1, 1.5, True]:
            workflow.repetitions = count
            with self.assertRaises(ValueError):
                workflow.validate()
