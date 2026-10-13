import unittest
from core import Step
from desktop import ocr_text, Recorder, parse_key, recorded_scroll_data


def row(text, y, score=0.99):
    return [[[0, y], [200, y], [200, y+20], [0, y+20]], text, score]


class OCRLayoutTests(unittest.TestCase):
    def test_zero_confidence_does_not_block_recognized_digits(self):
        self.assertEqual(ocr_text([row('661886', 0, 0.25)], 0), '661886')

    def test_reading_order_and_paragraph_gap(self):
        rows = [row('其他消息 999999', 90), row('验证码为：001234。', 25), row('【学生账号】', 0)]
        self.assertEqual(ocr_text(rows, 0.8), '【学生账号】\n验证码为：001234。\n\n其他消息 999999')

    def test_low_confidence_pauses(self):
        from core import AmbiguousCode
        with self.assertRaises(AmbiguousCode):
            ocr_text([row('学生账号 001234', 0, 0.5)], 0.8)

    def test_empty_image_result(self):
        self.assertEqual(ocr_text(None, 0.8), '')


class RecorderTests(unittest.TestCase):
    def test_scroll_calibration_ignores_clicks_and_keys(self):
        recorder = Recorder()
        recorder.start(now=10, kinds={'scroll'})
        recorder.record('click', {'x': 99, 'y': 99}, now=10.2)
        recorder.record('scroll', {'x': 100, 'y': 200, 'amount': -1}, now=11)
        recorder.record('key_event', {'key': 'a', 'action': 'press'}, now=11.2)
        recorder.record('scroll', {'x': 110, 'y': 210, 'amount': -2}, now=11.4)
        data = recorded_scroll_data(recorder.finish(now=15))
        self.assertEqual((data['x'], data['y'], data['amount']), (100, 200, -3))
        self.assertEqual(len(data['scroll_events']), 2)
        self.assertEqual(data['scroll_events'][0], {'amount': -1, 'delay': 0})
        self.assertAlmostEqual(data['scroll_events'][1]['delay'], 0.4)

    def test_calibration_without_scroll_rejected(self):
        with self.assertRaises(ValueError):
            recorded_scroll_data([Step('wait', wait=1)])

    def test_recorded_intervals_and_key_release(self):
        recorder = Recorder()
        recorder.start(now=10)
        recorder.record('click', {'x': 1, 'y': 2}, now=10.1)
        recorder.record('key_event', {'key': 'ctrl', 'action': 'press'}, now=10.6)
        recorder.record('key_event', {'key': 'ctrl', 'action': 'release'}, now=10.9)
        steps = recorder.finish(now=11)
        self.assertEqual(len(steps), 3)
        self.assertAlmostEqual(steps[0].wait, 0.5)
        self.assertAlmostEqual(steps[1].wait, 0.3)
        self.assertEqual(steps[-1].data['action'], 'release')

    def test_recording_disabled_outside_explicit_session(self):
        recorder = Recorder()
        recorder.record('click', {'x': 1, 'y': 2}, now=10)
        self.assertEqual(recorder.steps, [])

    def test_invalid_key_rejected(self):
        with self.assertRaises(ValueError):
            parse_key('not-a-real-key')


if __name__ == '__main__':
    unittest.main()
