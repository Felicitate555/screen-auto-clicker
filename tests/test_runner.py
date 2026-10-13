import threading
import time
import unittest
from core import Step, Workflow
from runner import Runner


class FakeDesktop:
    def __init__(self, texts):
        self.texts = iter(texts)
        self.calls = []
        self.released = 0

    def perform(self, step, code, phone=None):
        self.calls.append((step.kind, code))

    def read(self, data):
        return next(self.texts, '学生账号 001234')

    def release_all(self):
        self.released += 1


def flow(wait=0):
    click = Step('click', {'x': 1, 'y': 2}, wait=wait)
    read = Step('read', {'region': [0, 0, 100, 100], 'keyword': '学生账号',
                        'retry_from': click.id, 'timeout': 5, 'confidence': 0.8, 'use_first': False}, wait=0.01)
    return Workflow('test', [click, read, Step('paste', {'text': '{{code}}'})], start_delay=0)


class RunnerTests(unittest.TestCase):
    def test_missing_code_waits_five_seconds_before_retry_and_paste(self):
        workflow = flow()
        workflow.steps[1].data.pop('use_first')
        timeline = []

        class TraceDesktop(FakeDesktop):
            def read(self, data):
                text = super().read(data)
                timeline.append(('read', text))
                return text

            def perform(self, step, code, phone=None):
                timeline.append((step.kind, code))
                super().perform(step, code, phone)

        class FastRunner(Runner):
            def wait(self, seconds):
                self.checkpoint()
                timeline.append(('wait', seconds))

        desktop = TraceDesktop(['13800138000/0.26/暂无短信', '13800138000/0.26/【百度】验证码为：142716。'])
        runner = FastRunner(workflow, desktop)
        runner.run()
        self.assertEqual(runner.state, 'completed')
        first_read = next(i for i, event in enumerate(timeline) if event[0] == 'read')
        self.assertEqual(timeline[first_read + 1], ('wait', 5))
        self.assertEqual(timeline[first_read + 2], ('click', None))
        self.assertEqual(desktop.calls[-1], ('paste', '142716'))

    def test_missing_code_wait_can_be_stopped_before_retry(self):
        workflow = flow()
        workflow.steps[1].data.pop('use_first')
        workflow.steps[1].data['timeout'] = 0
        observed = threading.Event()
        desktop = FakeDesktop(['暂无短信'])
        runner = Runner(workflow, desktop, lambda event: observed.set() if event['type'] == 'ocr' else None)
        thread = threading.Thread(target=runner.run)
        thread.start()
        try:
            self.assertTrue(observed.wait(1))
            time.sleep(0.3)
            self.assertEqual(desktop.calls, [('click', None)])
            runner.stop()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(runner.state, 'stopped')
        finally:
            runner.stop()
            thread.join(1)

    def test_default_code_uses_first_read_without_repeating_predecessors(self):
        workflow = flow()
        workflow.steps[1].data.pop('use_first')
        desktop = FakeDesktop(['验证码 661886'])
        runner = Runner(workflow, desktop)
        runner.run()
        self.assertEqual(runner.state, 'completed')
        self.assertEqual(desktop.calls, [('click', None), ('paste', '661886')])

    def test_code_read_ignores_legacy_keyword(self):
        workflow = flow()
        workflow.steps[1].data['keyword'] = '不存在的旧关键词'
        desktop = FakeDesktop(['验证码 661886', '验证码 001234'])
        runner = Runner(workflow, desktop)
        runner.run()
        self.assertEqual(runner.state, 'completed')
        self.assertEqual(desktop.calls[-1], ('paste', '001234'))

    def test_calibrated_scroll_replays_each_tick_and_remains_stoppable(self):
        class ScrollDesktop(FakeDesktop):
            def perform(self, step, code, phone=None):
                self.calls.append(step.data['amount'])

        step = Step('scroll', {'x': 100, 'y': 200, 'amount': -3,
                              'scroll_events': [{'amount': -1, 'delay': 0}, {'amount': -2, 'delay': 60}]}, wait=0)
        desktop = ScrollDesktop([])
        runner = Runner(Workflow('scroll', [step], start_delay=0), desktop)
        thread = threading.Thread(target=runner.run)
        thread.start()
        time.sleep(0.08)
        runner.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(desktop.calls, [-1])
        self.assertEqual(runner.state, 'stopped')

    def test_phone_and_code_variables_are_independent(self):
        class PhoneDesktop(FakeDesktop):
            def perform(self, step, code, phone=None):
                if step.kind == 'paste':
                    self.calls.append((code, phone))

        refresh = Step('wait', wait=0)
        phone = Step('read_phone', {'region': [0, 0, 100, 100], 'keyword': '',
                                  'retry_from': refresh.id, 'timeout': 5}, wait=0)
        second = Step('wait', wait=0)
        code = Step('read', {'region': [0, 0, 100, 100], 'keyword': '学生账号',
                            'retry_from': second.id, 'timeout': 5}, wait=0)
        flow = Workflow('both', [refresh, phone, second, code, Step('paste', {'text': '{{phone}} {{code}}'}, wait=0)], start_delay=0)
        desktop = PhoneDesktop(['13800138000', '13800138000', '13900139000', '学生账号 661886', '学生账号 001234'])
        runner = Runner(flow, desktop)
        runner.run()
        self.assertEqual(runner.state, 'completed')
        self.assertEqual(desktop.calls, [('661886', '13900139000')])

    def test_pause_restores_recorded_modifier_before_next_key(self):
        class HeldDesktop(FakeDesktop):
            def __init__(self):
                super().__init__([])
                self.ctrl = False
                self.c_with_ctrl = False
                self.pressed = threading.Event()

            def perform(self, step, code, phone=None):
                if step.data['key'] == 'ctrl':
                    self.ctrl = step.data['action'] == 'press'
                    if self.ctrl:
                        self.pressed.set()
                elif step.data['key'] == 'c':
                    self.c_with_ctrl = self.ctrl

            def suspend_keys(self):
                saved = ['ctrl'] if self.ctrl else []
                self.ctrl = False
                return saved

            def restore_keys(self, saved):
                self.ctrl = 'ctrl' in saved

        desktop = HeldDesktop()
        steps = [Step('key_event', {'key': 'ctrl', 'action': 'press'}, wait=0.2),
                 Step('key_event', {'key': 'c', 'action': 'press'}, wait=0),
                 Step('key_event', {'key': 'ctrl', 'action': 'release'}, wait=0)]
        runner = Runner(Workflow('test', steps, start_delay=0), desktop)
        thread = threading.Thread(target=runner.run)
        thread.start()
        try:
            self.assertTrue(desktop.pressed.wait(1))
            runner.pause()
            self.assertFalse(desktop.ctrl)
            runner.resume()
            thread.join(1)
            self.assertTrue(desktop.c_with_ctrl)
            self.assertEqual(runner.state, 'completed')
        finally:
            runner.stop()
            thread.join(1)
    def test_timeout_interrupts_long_retry_wait_before_next_action(self):
        desktop = FakeDesktop(['学生账号 661886'])
        workflow = flow(wait=0.25)
        workflow.steps[1].data['timeout'] = 0.08
        runner = Runner(workflow, desktop)
        thread = threading.Thread(target=runner.run)
        thread.start()
        deadline = time.monotonic() + 2
        try:
            while runner.state != 'paused' and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(runner.state, 'paused')
            self.assertEqual(len(desktop.calls), 1, 'retry click must not execute after timeout during read wait')
        finally:
            runner.stop()
            thread.join(1)
    def test_retry_predecessors_until_new_code(self):
        desktop = FakeDesktop(['学生账号 661886', '学生账号 661886', '学生账号 001234'])
        runner = Runner(flow(), desktop)
        runner.run()
        self.assertEqual(desktop.calls, [('click', None), ('click', None), ('click', None), ('paste', '001234')])
        self.assertEqual(runner.state, 'completed')
        self.assertGreater(desktop.released, 0)

    def test_stop_interrupts_long_wait(self):
        desktop = FakeDesktop([])
        runner = Runner(flow(wait=60), desktop)
        thread = threading.Thread(target=runner.run)
        thread.start()
        time.sleep(0.08)
        runner.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(runner.state, 'stopped')
        self.assertNotIn('paste', [c[0] for c in desktop.calls])

    def test_pause_and_resume(self):
        desktop = FakeDesktop(['学生账号 661886', '学生账号 001234'])
        runner = Runner(flow(wait=0.12), desktop)
        thread = threading.Thread(target=runner.run)
        thread.start()
        time.sleep(0.04)
        runner.pause()
        count = len(desktop.calls)
        time.sleep(0.2)
        self.assertEqual(len(desktop.calls), count)
        runner.resume()
        thread.join(2)
        self.assertEqual(runner.state, 'completed')

    def test_timeout_pause_keeps_baseline_and_can_resume(self):
        desktop = FakeDesktop(['学生账号 661886', '学生账号 661886', '学生账号 001234'])
        workflow = flow()
        # Each read includes a 0.2s retry interval. The timeout must allow one
        # complete retry after Continue, while still expiring before read #3.
        workflow.steps[1].data['timeout'] = 0.3
        workflow.steps[0].wait = 0.025
        events = []
        runner = Runner(workflow, desktop, lambda event: events.append(event))
        thread = threading.Thread(target=runner.run)
        thread.start()
        deadline = time.monotonic() + 2
        while runner.state != 'paused' and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(runner.state, 'paused')
        runner.resume()
        thread.join(2)
        try:
            self.assertEqual(runner.state, 'completed')
            self.assertEqual(desktop.calls[-1], ('paste', '001234'))
        finally:
            runner.stop()
            thread.join(1)

    def test_ambiguity_pauses_before_input(self):
        desktop = FakeDesktop(['学生账号 123456 密码 654321'])
        runner = Runner(flow(), desktop)
        thread = threading.Thread(target=runner.run)
        thread.start()
        deadline = time.monotonic() + 2
        while runner.state != 'paused' and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(runner.state, 'paused')
        self.assertNotIn('paste', [c[0] for c in desktop.calls])
        runner.stop()
        thread.join(1)


if __name__ == '__main__':
    unittest.main()
