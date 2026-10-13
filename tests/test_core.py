import json
import tempfile
import unittest
from pathlib import Path

from core import Step, Workflow, CodeGate, AmbiguousCode, extract_code


class ExtractionTests(unittest.TestCase):
    def test_real_sms_extracts_only_six_code_digits(self):
        text = '13800138000/0.26/【百度】验证码为：142716。您正在进行网站登陆，1分钟内有效。如非您本人操作，可忽略本次消息。\n\n (\n… … …)'
        self.assertEqual(extract_code(text, '', 6, True), '142716')

    def test_labelled_code_wins_over_other_six_digit_data(self):
        self.assertEqual(extract_code('订单 998877。验证码为：142716。', '', 6, True), '142716')

    def test_invalid_labelled_code_does_not_use_unrelated_number(self):
        for text in ['订单 998877。验证码为：1234567。', '订单 998877。验证码为：待收取。']:
            self.assertIsNone(extract_code(text, '', 6, True))

    def test_code_label_variants_preserve_leading_zero(self):
        for text in ['验证码是：001234', '验证码为 001234', '验 证 码：\n００１２３４']:
            self.assertEqual(extract_code(text, '', 6, True), '001234')

    def test_multiple_labelled_codes_remain_ambiguous(self):
        with self.assertRaises(AmbiguousCode):
            extract_code('验证码为：142716。验证码为：001234。', '', 6, True)

    def test_ocr_extra_bracket_before_code_is_tolerated(self):
        self.assertEqual(extract_code('【学生账号】验证码为：（ 006321。', '', 6, True), '006321')

    def test_phone_from_fixed_region_without_keyword(self):
        self.assertEqual(extract_code('手机号：13800138000', '', 11, True), '13800138000')

    def test_phone_fullwidth_and_exact_length(self):
        self.assertEqual(extract_code('１３８００１３８０００', '', 11, True), '13800138000')
        for text in ['661886', '138001380001', '1380013800']:
            self.assertIsNone(extract_code(text, '', 11, True))

    def test_phone_optional_keyword_limits_paragraph(self):
        self.assertEqual(extract_code('其他号码 13900139000\n\n学生手机号 13800138000', '学生手机号', 11, True), '13800138000')

    def test_multiple_phones_are_ambiguous(self):
        with self.assertRaises(AmbiguousCode):
            extract_code('13800138000\n13900139000', '', 11, True)

    def test_example(self):
        self.assertEqual(extract_code('【学生账号】验证码为：661886。', '学生账号'), '661886')

    def test_leading_zero_and_fullwidth(self):
        self.assertEqual(extract_code('【学生账号】验证码为：００１２３４。', '学生账号'), '001234')

    def test_wrapped_paragraph(self):
        self.assertEqual(extract_code('【学生 账号】\n验证码为：001234。', '学生账号'), '001234')

    def test_unrelated_paragraph_excluded(self):
        text = '其他内容 999999\n\n【学生账号】验证码为：001234。\n\n旧消息 123456'
        self.assertEqual(extract_code(text, '学生账号'), '001234')

    def test_next_message_excluded(self):
        self.assertEqual(extract_code('【学生账号】001234\n【其他消息】999999', '学生账号'), '001234')

    def test_missing_or_long_number(self):
        for text in ['其他账号 661886', '学生账号 1234567', '学生账号 暂无数据']:
            self.assertIsNone(extract_code(text, '学生账号'))

    def test_multiple_codes_pause(self):
        with self.assertRaises(AmbiguousCode):
            extract_code('学生账号 123456 密码 654321', '学生账号')

    def test_multiple_keyword_messages_pause(self):
        with self.assertRaises(AmbiguousCode):
            extract_code('学生账号 123456\n\n学生账号 654321', '学生账号')

    def test_empty_keyword_rejected(self):
        with self.assertRaises(ValueError):
            extract_code('123456', '')


class GateTests(unittest.TestCase):
    def test_six_digit_default_accepts_first_valid_code(self):
        gate = CodeGate('', 6, True)
        self.assertEqual(gate.observe('尚未出现数字'), ('missing', None))
        self.assertEqual(gate.observe('验证码 001234'), ('first', '001234'))
        self.assertEqual(gate.observe('验证码 001234'), ('unchanged', '001234'))
        self.assertEqual(gate.observe('验证码 552211'), ('new', '552211'))

    def test_phone_baseline_and_change(self):
        gate = CodeGate('', 11, True)
        self.assertEqual(gate.observe('13800138000'), ('baseline', '13800138000'))
        self.assertEqual(gate.observe('13800138000'), ('unchanged', '13800138000'))
        self.assertEqual(gate.observe('13900139000'), ('new', '13900139000'))

    def test_first_baseline_then_same_then_change(self):
        gate = CodeGate('学生账号', use_first=False)
        self.assertEqual(gate.observe('学生账号 661886'), ('baseline', '661886'))
        self.assertEqual(gate.observe('学生账号 验证码：661886。'), ('unchanged', '661886'))
        self.assertEqual(gate.observe('学生账号 001234'), ('new', '001234'))
        self.assertEqual(gate.observe('学生账号 001234'), ('unchanged', '001234'))

    def test_missing_does_not_set_baseline(self):
        gate = CodeGate('学生账号', use_first=False)
        self.assertEqual(gate.observe('无消息'), ('missing', None))
        self.assertEqual(gate.observe('学生账号 000123'), ('baseline', '000123'))


class WorkflowTests(unittest.TestCase):
    def test_ema_text_source_needs_no_region(self):
        first = Step('wait', wait=0)
        read = Step('read', {'source': 'ema_text', 'retry_from': first.id})
        Workflow('EMA', [first, read, Step('paste', {'text': '{{code}}'})]).validate()
        read.data['source'] = 'unknown'
        with self.assertRaises(ValueError):
            Workflow('EMA', [first, read]).validate()

    def test_code_region_needs_no_keyword_and_allows_disabled_confidence(self):
        refresh = Step('wait', wait=0)
        read = Step('read', {'region': [0, 0, 200, 100], 'keyword': '',
                            'retry_from': refresh.id, 'confidence': 0})
        Workflow('code', [refresh, read, Step('paste', {'text': '{{code}}'})]).validate()

    def test_scroll_profile_persistence_and_invalid_profile(self):
        step = Step('scroll', {'x': 1, 'y': 2, 'amount': -3,
                              'scroll_events': [{'amount': -1, 'delay': 0}, {'amount': -2, 'delay': 0.4}]})
        workflow = Workflow('scroll', [step])
        workflow.validate()
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'scroll.json'
            workflow.save(file)
            self.assertEqual(Workflow.load(file).to_dict(), workflow.to_dict())
        for events in [[], [{'amount': -1, 'delay': -1}], [{'amount': 1.5, 'delay': 0}], 'bad']:
            step.data['scroll_events'] = events
            with self.assertRaises(ValueError):
                workflow.validate()

    def test_phone_workflow_roundtrip_without_keyword(self):
        refresh = Step('wait', wait=0)
        read = Step('read_phone', {'region': [0, 0, 300, 100], 'keyword': '', 'retry_from': refresh.id})
        flow = Workflow('手机流程', [refresh, read, Step('paste', {'text': '{{phone}}'})])
        flow.validate()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'phone.json'
            flow.save(path)
            self.assertEqual(Workflow.load(path).to_dict(), flow.to_dict())

    def test_phone_requires_its_own_prior_read(self):
        flow = self.make_flow()
        flow.steps[-1].data['text'] = '{{phone}}'
        with self.assertRaises(ValueError):
            flow.validate()

    def make_flow(self):
        refresh = Step('click', {'x': 120, 'y': 230, 'button': 'left', 'count': 1}, wait=0.2)
        read = Step('read', {'region': [10, 20, 300, 200], 'keyword': '学生账号',
                            'retry_from': refresh.id, 'timeout': 60, 'confidence': 0.8}, wait=0.5)
        paste = Step('paste', {'text': '{{code}}'})
        return Workflow('学生作品', [refresh, read, paste])

    def test_save_load_roundtrip(self):
        flow = self.make_flow()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '流程.json'
            flow.save(path)
            loaded = Workflow.load(path)
            self.assertEqual(loaded.to_dict(), flow.to_dict())
            self.assertNotIn('661886', path.read_text(encoding='utf-8'))

    def test_retry_target_must_precede_read(self):
        flow = self.make_flow()
        flow.steps[1].data['retry_from'] = flow.steps[2].id
        with self.assertRaises(ValueError):
            flow.validate()

    def test_invalid_region(self):
        flow = self.make_flow()
        flow.steps[1].data['region'] = [0, 0, 0, 100]
        with self.assertRaises(ValueError):
            flow.validate()

    def test_unknown_step_and_negative_wait(self):
        for step in [Step('unknown'), Step('wait', wait=-1), Step('wait', wait=float('nan'))]:
            with self.assertRaises(ValueError):
                Workflow('test', [step]).validate()

    def test_code_input_before_read_rejected(self):
        with self.assertRaises(ValueError):
            Workflow('test', [Step('paste', {'text': '{{code}}'})]).validate()

    def test_duplicate_ids_rejected(self):
        flow = self.make_flow()
        flow.steps[2].id = flow.steps[0].id
        with self.assertRaises(ValueError):
            flow.validate()

    def test_corrupt_json_not_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            path.write_text(json.dumps({'version': 99, 'steps': []}), encoding='utf-8')
            with self.assertRaises(ValueError):
                Workflow.load(path)

    def test_malformed_step_data_rejected_at_load(self):
        for kind, data in [('paste', {'text': 123}), ('hotkey', {'keys': 'ctrl+r'}),
                           ('read', {'keyword': [], 'region': [0, 0, 1, 1]}),
                           ('launch', {'path': 'x.exe', 'args': 'bad'})]:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'bad.json'
                path.write_text(json.dumps(Workflow('test', [Step(kind, data)]).to_dict()), encoding='utf-8')
                with self.assertRaises(ValueError):
                    Workflow.load(path)


if __name__ == '__main__':
    unittest.main()
