import tempfile
import unittest
from pathlib import Path
from core import Step, Workflow
from ui import App


class UITests(unittest.TestCase):
    def test_loading_existing_flow_relaxes_reading_in_memory(self):
        first = Step('wait', wait=0)
        step = Step('read', {'region': [0, 0, 200, 100], 'keyword': '旧关键词',
                            'retry_from': first.id, 'confidence': 0.8})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '我的流程.json'
            Workflow('我的流程', [first, step]).save(path)
            original = path.read_bytes()
            self.app.load_flow(path, relax_read=True)
            self.assertEqual(self.app.flow.steps[1].data['keyword'], '')
            self.assertEqual(self.app.flow.steps[1].data['confidence'], 0)
            self.assertEqual(self.app.path, path)
            self.assertTrue(self.app.dirty)
            self.assertEqual(path.read_bytes(), original)

    def test_code_editor_has_no_keyword_and_defaults_to_zero_confidence(self):
        self.app.add_step('wait')
        self.app.add_step('read')
        self.assertNotIn('keyword', self.app.fields)
        self.app.commit_editor()
        self.assertEqual(self.app.current().data['keyword'], '')
        self.assertEqual(self.app.current().data['confidence'], 0)

    def test_scroll_calibration_updates_selected_step_without_appending(self):
        self.app.add_step('scroll')
        sid = self.app.current().id
        self.app.scroll_capture_id = sid
        self.app.finish_recording([Step('scroll', {'x': 100, 'y': 200, 'amount': -1}, wait=0.4),
                                   Step('scroll', {'x': 100, 'y': 200, 'amount': -2}, wait=3)])
        self.assertEqual(len(self.app.flow.steps), 1)
        self.assertEqual(self.app.current().data['amount'], -3)
        self.assertEqual(self.app.current().data['scroll_events'][1]['delay'], 0.4)
        self.app.put_field('amount', '-4')
        self.app.commit_editor()
        self.assertNotIn('scroll_events', self.app.current().data)

    def test_cancelling_calibration_countdown_keeps_step(self):
        self.app.add_step('scroll')
        callbacks = []
        self.app.after = lambda delay, callback: callbacks.append(callback)
        self.app.capture_scroll()
        self.app.stop_run()
        callbacks[0]()
        self.assertFalse(self.app.recorder.active)
        self.assertIsNone(self.app.scroll_capture_id)
        self.assertNotIn('scroll_events', self.app.current().data)

    def test_phone_option_has_optional_keyword_and_separate_variable(self):
        self.assertIn('读取新十一位手机号', self.app.kind_menu.cget('values'))
        self.app.add_step('wait')
        first = self.app.flow.steps[0].id
        self.app.add_step('read_phone')
        self.app.commit_editor()
        self.assertEqual(self.app.current().data['keyword'], '')
        self.assertEqual(self.app.current().data['retry_from'], first)
        self.app.add_step('paste')
        self.app.insert_phone()
        self.app.commit_editor()
        self.assertEqual(self.app.current().data['text'], '{{phone}}')

    def setUp(self):
        self.app = App(listeners=False)
        self.app.withdraw()

    def tearDown(self):
        self.app.close(force=True)

    def test_editor_changes_model_and_roundtrips(self):
        self.app.add_step('wait')
        self.app.fields['wait'].delete(0, 'end')
        self.app.fields['wait'].insert(0, '1.25')
        self.app.commit_editor()
        self.assertEqual(self.app.flow.steps[0].wait, 1.25)
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'test.json'
            self.app.flow.save(file)
            self.assertEqual(Workflow.load(file).steps[0].wait, 1.25)

    def test_duplicate_uses_new_identity(self):
        self.app.add_step('wait')
        self.app.duplicate_step()
        self.assertEqual(len(self.app.flow.steps), 2)
        self.assertNotEqual(self.app.flow.steps[0].id, self.app.flow.steps[1].id)

    def test_read_retry_selection_references_id(self):
        self.app.add_step('wait')
        first = self.app.flow.steps[0].id
        self.app.add_step('read')
        self.app.commit_editor()
        self.assertEqual(self.app.flow.steps[1].data['retry_from'], first)

    def test_dirty_editor_detected(self):
        self.app.add_step('wait')
        self.app.dirty = False
        self.app.fields['wait'].delete(0, 'end')
        self.app.fields['wait'].insert(0, '2')
        self.app.commit_editor()
        self.assertTrue(self.app.dirty)

    def test_cancelled_record_countdown_cannot_start_new_session_early(self):
        callbacks = []
        self.app.after = lambda delay, callback: callbacks.append(callback)
        self.app.toggle_record()
        self.app.stop_run()
        self.app.toggle_record()
        callbacks[0]()
        self.assertFalse(self.app.recorder.active)
        self.assertTrue(self.app.record_pending)
        callbacks[1]()
        self.assertTrue(self.app.recorder.active)
        self.app.recorder.finish()


if __name__ == '__main__':
    unittest.main()
