"""Packaged smoke test using synthetic data; never runs a user workflow."""
import json
import time
import traceback
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageGrab
from core import Step, Workflow, CodeGate, extract_code
from desktop import LocalOCR, Desktop, screen_bounds, recorded_scroll_data


def make_fixture(code='001234', phone=False):
    image = Image.new('RGB', (900, 170), 'white')
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 36)
    text = '手机号：' + code if phone else '【学生账号】验证码为：' + code + '。'
    ImageDraw.Draw(image).text((25, 50), text, font=font, fill='#152238')
    return image


def run_selftest(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {'tests': [], 'passed': False}
    app = None
    try:
        gate = CodeGate('学生账号', use_first=False)
        assert gate.observe('学生账号 661886')[0] == 'baseline'
        assert gate.observe('学生账号 661886')[0] == 'unchanged'
        assert gate.observe('学生账号 001234') == ('new', '001234')
        report['tests'].append('first baseline / unchanged / new / leading zero')
        phone_gate = CodeGate('', 11, True)
        assert phone_gate.observe('13800138000')[0] == 'baseline'
        assert phone_gate.observe('13800138000')[0] == 'unchanged'
        assert phone_gate.observe('13900139000') == ('new', '13900139000')
        report['tests'].append('phone first baseline / unchanged / new')
        ocr = LocalOCR()
        for code in ['661886', '001234']:
            fixture = make_fixture(code)
            fixture.save(output / ('OCR-' + code + '.png'))
            text = ocr.recognize(fixture)
            assert extract_code(text, '学生账号') == code, repr(text)
            report['tests'].append('offline Chinese OCR: ' + text)
        for phone in ['13800138000', '13900139000']:
            fixture = make_fixture(phone, phone=True)
            text = ocr.recognize(fixture)
            assert extract_code(text, '', 11, True) == phone, repr(text)
            report['tests'].append('offline phone OCR: ' + text)

        from ui import App
        app = App(listeners=False)
        refresh = Step('hotkey', {'keys': ['ctrl', 'r']}, wait=1, title='刷新来源消息')
        read = Step('read', {'region': [100, 100, 750, 260], 'keyword': '学生账号',
                            'retry_from': refresh.id, 'timeout': 60, 'confidence': 0.8}, wait=1,
                    title='等待变化后提取六位数字')
        click = Step('click', {'x': 500, 'y': 400, 'button': 'left', 'count': 1}, wait=0.5, title='点击目标输入框')
        paste = Step('paste', {'text': '{{code}}'}, wait=0.5, title='输入刚获取的数据')
        app.flow = Workflow('示例：获取老师的新数据', [refresh, read, click, paste])
        app.name_var.set(app.flow.name)
        app.selected = read.id
        app.refresh_list()
        app.build_editor()
        app.flow.validate()
        app.flow.save(output / 'test-flow.json')
        assert Workflow.load(output / 'test-flow.json').to_dict() == app.flow.to_dict()
        report['tests'].append('workflow editor / validation / JSON roundtrip')
        scroll_data = recorded_scroll_data([Step('scroll', {'x': 100, 'y': 200, 'amount': -1}, wait=0.35),
                                            Step('scroll', {'x': 100, 'y': 200, 'amount': -2}, wait=4)])
        scroll = Step('scroll', scroll_data, title='已录入的实际滚动', wait=0.5)
        scroll_flow = Workflow('示例：实际滚动录入', [scroll])
        scroll_flow.validate()
        scroll_flow.save(output / 'scroll-flow.json')
        assert Workflow.load(output / 'scroll-flow.json').to_dict() == scroll_flow.to_dict()
        app.flow = scroll_flow
        app.name_var.set(scroll_flow.name)
        app.selected = scroll.id
        app.refresh_list()
        app.build_editor()
        assert app.fields['amount'].get() == '-3'
        report['tests'].append('scroll calibration / timing preservation / editor / JSON roundtrip')
        phone_refresh = Step('wait', wait=1, title='等待来源区域更新（可替换为点击刷新）')
        phone_read = Step('read_phone', {'region': [0, 0, 0, 0], 'keyword': '',
                                        'retry_from': phone_refresh.id, 'timeout': 60, 'confidence': 0.8},
                          title='请框选手机号固定位置')
        phone_flow = Workflow('示例：读取新手机号（先重新框选和取点）',
                              [phone_refresh, phone_read,
                               Step('click', {'x': 0, 'y': 0, 'button': 'left', 'count': 1}, title='请取点目标输入框'),
                               Step('paste', {'text': '{{phone}}'}, title='输入新手机号')])
        phone_flow.save(output / 'phone-flow.json')
        assert Workflow.load(output / 'phone-flow.json').to_dict() == phone_flow.to_dict()
        assert '读取新十一位手机号' in app.kind_menu.cget('values')
        report['tests'].append('phone editor option / independent variable / JSON roundtrip')
        # Show the scroll calibration controls in the release screenshot.
        app.flow = scroll_flow
        app.name_var.set(scroll_flow.name)
        app.selected = scroll.id
        app.refresh_list()
        app.build_editor()
        app.log('实际滚动录入：共 2 个滚动动作，总刻度 -3（自检示例）')
        app.log('滚动节奏、流程保存、验证码和手机号识别自检通过')
        app.ocr_var.set('选择“实际滚动录入”，亲自滚到合适的位置，按 F8 完成。\n\n试滚前把页面恢复到同一起点。')
        app.code_var.set('滚动校准与单步试滚')
        app.update()
        app.lift()
        app.update()
        # Crop only this application, excluding the user's other windows.
        time.sleep(0.3)
        app.update()
        box = (app.winfo_rootx(), app.winfo_rooty(), app.winfo_rootx()+app.winfo_width(), app.winfo_rooty()+app.winfo_height())
        ImageGrab.grab(bbox=box, all_screens=True).save(output / '界面预览.png')
        report['tests'].append('Tk layout rendered / application-only screenshot')
        app.close(force=True)
        app = None
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if app is not None:
            app.close(force=True)
        (output / 'selftest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1


def run_headless_test(output):
    """Verify a packaged upgrade without opening windows or sending input."""
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'tests': []}
    try:
        gate = CodeGate('', 6, True)
        assert gate.observe('006321') == ('first', '006321')
        assert gate.observe('006321') == ('unchanged', '006321')
        assert gate.observe('552211') == ('new', '552211')
        phone = CodeGate('', 11, True)
        assert phone.observe('13800138000') == ('baseline', '13800138000')
        assert phone.observe('13900139000') == ('new', '13900139000')
        report['tests'].append('first code accepted / leading zero / subsequent changes / phone baseline')
        sms = '13800138000/0.26/【百度】验证码为：142716。您正在进行网站登陆，1分钟内有效。如非您本人操作，可忽略本次消息。\n\n (\n… … …)'
        assert CodeGate('', 6, True).observe(sms) == ('first', '142716')
        assert extract_code('订单 998877。验证码为：142716。', '', 6, True) == '142716'
        assert extract_code('订单 998877。验证码为：待收取。', '', 6, True) is None
        report['tests'].append('real SMS / labelled code priority / incomplete SMS waits')
        from runner import Runner
        class QuietDesktop:
            def __init__(self):
                self.reads = 0
                self.received = None

            def read(self, data):
                self.reads += 1
                return '006321'

            def perform(self, step, code, phone=None):
                if step.kind == 'paste':
                    self.received = code

            def release_all(self):
                pass
        first = Step('wait', wait=0)
        read = Step('read', {'region': [0, 0, 100, 100], 'retry_from': first.id,
                            'confidence': 0, 'keyword': ''}, wait=0)
        workflow = Workflow('无界面验证', [first, read, Step('paste', {'text': '{{code}}'}, wait=0)], start_delay=0)
        desktop = QuietDesktop()
        runner = Runner(workflow, desktop)
        runner.run()
        assert runner.state == 'completed' and desktop.reads == 1 and desktop.received == '006321'
        workflow.save(output / 'test-flow.json')
        assert Workflow.load(output / 'test-flow.json').to_dict() == workflow.to_dict()
        report['tests'].append('executor accepts first read / JSON roundtrip')
        class MissingDesktop(QuietDesktop):
            def read(self, data):
                self.reads += 1
                return '暂无短信' if self.reads == 1 else sms

        class FastRunner(Runner):
            def __init__(self, *args):
                super().__init__(*args)
                self.waits = []

            def wait(self, seconds):
                self.checkpoint()
                self.waits.append(seconds)

        missing = MissingDesktop()
        pending = FastRunner(workflow, missing)
        pending.run()
        assert pending.state == 'completed' and pending.waits == [0, 0, 5, 0, 0, 0]
        assert missing.reads == 2 and missing.received == '142716'
        report['tests'].append('missing code waits five seconds / retry then paste only six digits')
        import comtypes.client
        import uiautomation
        module = comtypes.client.GetModule('UIAutomationCore.dll')
        assert hasattr(module, 'IUIAutomation')
        from window_text import read_ema_text
        import contextlib
        from types import SimpleNamespace
        class FakeSMSWindow:
            Name = 'E码云短信'
            AutomationId = 'MainForm'
            def EditControl(self, **kwargs):
                assert kwargs['AutomationId'] == 'msgTextBox'
                return SimpleNamespace(NativeWindowHandle=0, Exists=lambda **kwargs: True,
                                       GetValuePattern=lambda: SimpleNamespace(Value='【百度】验证码为：006321。'))
        provider = SimpleNamespace(UIAutomationInitializerInThread=contextlib.nullcontext,
                                   GetRootControl=lambda: SimpleNamespace(GetChildren=lambda: [FakeSMSWindow()]))
        assert read_ema_text(provider) == '【百度】验证码为：006321。'
        report['tests'].append('UI Automation dependencies / read-only SMS adapter with simulated provider')
        text = LocalOCR().recognize(make_fixture('006321'))
        assert extract_code(text, '', 6, True) == '006321', text
        report['tests'].append('offline in-memory OCR')
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    (output / 'selftest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1
