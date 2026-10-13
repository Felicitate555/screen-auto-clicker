from dataclasses import dataclass, field, asdict
from pathlib import Path
import uuid
import json
import math
import os
import re
import tempfile
import unicodedata

KINDS = {'launch': '打开软件', 'click': '点击', 'scroll': '滚动', 'hotkey': '快捷键',
         'key_event': '录制按键', 'paste': '输入文字', 'wait': '等待', 'read': '读取新六位数字',
         'read_phone': '读取新十一位手机号'}
READ_KINDS = {'read': (6, '六位数字', 'code'), 'read_phone': (11, '十一位手机号', 'phone')}


def validate_scroll_events(events):
    if not isinstance(events, list) or not 1 <= len(events) <= 5000:
        raise ValueError('滚动记录应包含 1 到 5000 个动作')
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('滚动记录格式错误')
        amount = event.get('amount')
        if isinstance(amount, bool) or not isinstance(amount, int) or not -1000 <= amount <= 1000:
            raise ValueError('记录中的滚动格数必须是 -1000 到 1000 的整数')
        number(event.get('delay'), '滚动间隔')


def number(value, label, minimum=0, maximum=86400):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f'{label}必须是有效数字')
    if not minimum <= value <= maximum:
        raise ValueError(f'{label}应在 {minimum} 到 {maximum} 之间')
    return value


class AmbiguousCode(ValueError):
    pass


@dataclass
class Step:
    kind: str
    data: dict = field(default_factory=dict)
    wait: float = 0.5
    title: str = ''
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Workflow:
    name: str
    steps: list[Step] = field(default_factory=list)
    start_delay: float = 3.0
    repetitions: int = 1

    def validate(self):
        self.check_structure()
        if not self.steps:
            raise ValueError('请先添加至少一个步骤')
        number(self.start_delay, '开始倒计时', 0, 60)
        available_code = False
        available_phone = False
        for index, step in enumerate(self.steps):
            prefix = f'第 {index + 1} 步：'
            try:
                number(step.wait, '等待秒数')
                data = step.data
                if step.kind in ('click', 'scroll'):
                    for key in ('x', 'y'):
                        number(data.get(key), '坐标 ' + key, -100000, 100000)
                    if step.kind == 'click':
                        if data.get('button', 'left') not in ('left', 'right', 'middle'):
                            raise ValueError('鼠标按键无效')
                        if data.get('count', 1) not in (1, 2):
                            raise ValueError('点击次数只能是 1 或 2')
                    else:
                        number(data.get('amount'), '滚动格数', -1000, 1000)
                        if 'scroll_events' in data and sum(e['amount'] for e in data['scroll_events']) != data['amount']:
                            raise ValueError('滚动总格数与记录不一致，请重新录入')
                elif step.kind == 'launch':
                    if not isinstance(data.get('path'), str) or not data['path'].strip():
                        raise ValueError('请选择软件的 EXE 路径')
                elif step.kind in ('hotkey', 'key_event'):
                    keys = data.get('keys') if step.kind == 'hotkey' else [data.get('key')]
                    if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k for k in keys):
                        raise ValueError('请输入有效按键')
                    if step.kind == 'key_event' and data.get('action') not in ('press', 'release'):
                        raise ValueError('按键动作无效')
                elif step.kind == 'paste':
                    if not isinstance(data.get('text'), str):
                        raise ValueError('输入文字必须是文本')
                    if '{{code}}' in data['text'] and not available_code:
                        raise ValueError('输入 {{code}} 前需要有读取新六位数字步骤')
                    if '{{phone}}' in data['text'] and not available_phone:
                        raise ValueError('输入 {{phone}} 前需要有读取新十一位手机号步骤')
                elif step.kind in READ_KINDS:
                    source = data.get('source', 'screen')
                    if source not in ('screen', 'ema_text') or (step.kind != 'read' and source == 'ema_text'):
                        raise ValueError('不支持的读取来源')
                    if source == 'screen':
                        region = data.get('region')
                        if not isinstance(region, list) or len(region) != 4:
                            raise ValueError('请先框选识别区域')
                        for value in region:
                            number(value, '区域坐标', -100000, 100000)
                        if region[2] <= region[0] or region[3] <= region[1]:
                            raise ValueError('识别区域宽度和高度必须大于零')
                        if region[2] - region[0] > 10000 or region[3] - region[1] > 10000:
                            raise ValueError('识别区域过大，请缩小到消息区域')
                    previous = {s.id for s in self.steps[:index]}
                    if data.get('retry_from') not in previous:
                        raise ValueError('重试起点必须是当前步骤前面的某一步')
                    number(data.get('timeout', 60), '最长等待秒数')
                    number(data.get('confidence', 0), '识别置信度', 0, 1)
                    if step.kind == 'read':
                        available_code = True
                    else:
                        available_phone = True
            except ValueError as error:
                raise ValueError(prefix + str(error)) from error

    def check_structure(self):
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int) or not 1 <= self.repetitions <= 99999:
            raise ValueError('运行次数必须是 1 到 99999 的整数')
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('流程名称不能为空')
        if not isinstance(self.steps, list) or len(self.steps) > 5000:
            raise ValueError('流程最多支持 5000 步')
        ids = []
        for step in self.steps:
            if not isinstance(step, Step) or step.kind not in KINDS:
                raise ValueError('文件包含不支持的步骤类型')
            if not isinstance(step.id, str) or not step.id or not isinstance(step.data, dict):
                raise ValueError('步骤格式错误')
            if not isinstance(step.title, str):
                raise ValueError('步骤名称格式错误')
            if 'use_first' in step.data and not isinstance(step.data['use_first'], bool):
                raise ValueError('首次识别使用选项必须是布尔值')
            if 'replace_existing' in step.data and not isinstance(step.data['replace_existing'], bool):
                raise ValueError('替换原文字选项必须是布尔值')
            # Drafts may omit fields, but present values must be displayable
            # and typed correctly before the editor replaces its current flow.
            for key in ('text', 'path', 'keyword', 'retry_from', 'button', 'key', 'action', 'source'):
                if key in step.data and not isinstance(step.data[key], str):
                    raise ValueError(f'步骤字段 {key} 必须是文本')
            for key in ('keys', 'args'):
                if key in step.data and (not isinstance(step.data[key], list) or
                                         not all(isinstance(value, str) for value in step.data[key])):
                    raise ValueError(f'步骤字段 {key} 必须是文本列表')
            for key in ('x', 'y', 'count', 'amount', 'timeout', 'confidence'):
                if key in step.data:
                    number(step.data[key], key, -100000, 100000)
            if 'region' in step.data:
                region = step.data['region']
                if not isinstance(region, list) or len(region) != 4:
                    raise ValueError('区域字段应包含四个坐标')
                for value in region:
                    number(value, '区域坐标', -100000, 100000)
            if 'scroll_events' in step.data:
                validate_scroll_events(step.data['scroll_events'])
            number(step.wait, '等待秒数')
            ids.append(step.id)
        if len(set(ids)) != len(ids):
            raise ValueError('步骤 ID 重复')

    def to_dict(self):
        return {'version': 1, **asdict(self)}

    def save(self, path):
        self.check_structure()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as file:
                temporary = file.name
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('流程文件超过 4 MB')
        try:
            obj = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(obj, dict) or obj.get('version') != 1:
                raise ValueError('不支持的流程文件版本')
            result = cls(obj['name'], [Step(**s) for s in obj['steps']], obj.get('start_delay', 3), obj.get('repetitions', 1))
            result.check_structure()
            number(result.start_delay, '开始倒计时', 0, 60)
            return result
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('流程文件格式错误：' + str(error)) from error


def extract_code(text, keyword, digit_count=6, allow_empty_keyword=False):
    keyword = re.sub(r'\s+', '', unicodedata.normalize('NFKC', keyword))
    if not keyword and not allow_empty_keyword:
        raise ValueError('关键词不能为空')
    text = unicodedata.normalize('NFKC', text)
    # Blank lines and bracketed message headings delimit paragraphs. Ordinary
    # wrapping stays within the same paragraph, including OCR-inserted spaces.
    parts = re.split(r'\n\s*\n|\n(?=\s*[【\[])', text)
    matches = [part for part in parts if keyword in re.sub(r'\s+', '', part)] if keyword else [text]
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousCode('识别区域有多段包含关键词的消息，请缩小区域后继续')
    paragraph = matches[0]
    code_label = r'验\s*证\s*码'
    if digit_count == 6 and re.search(code_label, paragraph):
        # SMS prefixes may contain a phone, price, or order number. A visible
        # code label takes priority; an incomplete labelled code must wait.
        codes = re.findall(code_label + r'\s*(?:[为是]\s*)?[\s:(\[【]*([0-9]{6})(?![0-9])', paragraph)
    else:
        # Retain support for a tightly cropped region containing only digits.
        codes = re.findall(r'(?<![0-9])[0-9]{' + str(digit_count) + r'}(?![0-9])', paragraph)
    if len(codes) > 1:
        label = '十一位手机号' if digit_count == 11 else '六位数字'
        raise AmbiguousCode('识别区域中存在多个' + label + '，请缩小区域后继续')
    return codes[0] if codes else None


class CodeGate:
    def __init__(self, keyword, digit_count=6, allow_empty_keyword=False, use_first=None):
        self.keyword = keyword
        self.digit_count = digit_count
        self.allow_empty_keyword = allow_empty_keyword
        self.baseline = None
        self.use_first = digit_count == 6 if use_first is None else use_first

    def observe(self, text):
        code = extract_code(text, self.keyword, self.digit_count, self.allow_empty_keyword)
        if code is None:
            return 'missing', None
        if self.baseline is None:
            self.baseline = code
            return ('first' if self.use_first else 'baseline'), code
        if self.baseline == code:
            return 'unchanged', code
        self.baseline = code
        return 'new', code
