"""Cooperative executor; never imports desktop automation into core tests."""
import threading
import time
from core import CodeGate, AmbiguousCode, READ_KINDS, Step


class Stopped(Exception):
    pass


class Runner:
    def __init__(self, workflow, desktop, emit=None):
        self.workflow = workflow
        self.desktop = desktop
        self.emit = emit or (lambda event: None)
        self.state = 'idle'
        self.code = None
        self.phone = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._ready.set()
        self._active = 0.0
        self._last = time.monotonic()
        self._clock_lock = threading.Lock()
        self._deadlines = {}
        self._suspended_keys = []
        self._restore_pending = False
        self._pause_generation = 0

    def log(self, message, **fields):
        self.emit({'type': 'log', 'message': message, **fields})

    def _state(self, value):
        self.state = value
        self.emit({'type': 'state', 'state': value})

    def _tick(self):
        with self._clock_lock:
            now = time.monotonic()
            if self._ready.is_set():
                self._active += now - self._last
            self._last = now
            return self._active

    def pause(self, reason='已暂停；F9 继续，F10 停止'):
        if self.state in ('running', 'starting'):
            self._tick()
            self._ready.clear()
            self._pause_generation += 1
            if hasattr(self.desktop, 'suspend_keys'):
                self._suspended_keys = self.desktop.suspend_keys()
            else:
                self.desktop.release_all()
            self._state('paused')
            self.log(reason)

    def resume(self):
        if self.state == 'paused':
            self._tick()
            self._restore_pending = True
            self._ready.set()
            self._state('running')
            self.log('继续执行，保留本次运行的基准')

    def stop(self):
        self._stop.set()
        self._ready.set()
        self.desktop.release_all()

    def checkpoint(self):
        if self._stop.is_set():
            raise Stopped()
        while not self._ready.wait(0.05):
            self._tick()
            if self._stop.is_set():
                raise Stopped()
        if self._stop.is_set():
            raise Stopped()
        active = self._tick()
        expired = [sid for sid, (deadline, seconds) in self._deadlines.items() if active >= deadline]
        if expired:
            self.pause('等待新数据超时，已暂停。检查来源消息后按 F9 继续，或 F10 停止')
            while not self._ready.wait(0.05):
                self._tick()
                if self._stop.is_set():
                    raise Stopped()
            if self._stop.is_set():
                raise Stopped()
            active = self._tick()
            for sid in expired:
                self._deadlines[sid] = (active + self._deadlines[sid][1], self._deadlines[sid][1])
        if self._restore_pending:
            if self._suspended_keys and hasattr(self.desktop, 'restore_keys'):
                self.desktop.restore_keys(self._suspended_keys)
            self._suspended_keys = []
            self._restore_pending = False

    def wait(self, seconds):
        self.checkpoint()
        end = self._tick() + seconds
        while self._tick() < end:
            self.checkpoint()
            self._stop.wait(min(0.04, max(0, end - self._tick())))
        self.checkpoint()

    def run(self):
        gates = {}
        try:
            self.workflow.validate()
            self._state('starting')
            self.log(f'{self.workflow.start_delay:g} 秒后开始；请将目标窗口放在前台。F10 随时停止')
            self.wait(self.workflow.start_delay)
            self._state('running')
            index = 0
            round_index = 0
            self.log(f'开始第 1 / {self.workflow.repetitions} 次运行')
            while round_index < self.workflow.repetitions:
                self.checkpoint()
                if index == len(self.workflow.steps):
                    self.desktop.release_all()
                    round_index += 1
                    self.log(f'第 {round_index} / {self.workflow.repetitions} 次运行完成')
                    if round_index == self.workflow.repetitions:
                        break
                    index = 0
                    gates.clear()
                    self._deadlines.clear()
                    self.code = self.phone = None
                    self.emit({'type': 'code', 'code': '尚未获取', 'label': '六位数字', 'variable': 'code'})
                    self.log(f'开始第 {round_index + 1} / {self.workflow.repetitions} 次运行')
                step = self.workflow.steps[index]
                self.emit({'type': 'step', 'index': index})
                if step.kind not in READ_KINDS:
                    if step.kind == 'scroll' and step.data.get('scroll_events'):
                        for event in step.data['scroll_events']:
                            self.wait(event['delay'])
                            action = Step('scroll', {'x': step.data['x'], 'y': step.data['y'], 'amount': event['amount']}, wait=0)
                            self.desktop.perform(action, self.code, self.phone)
                    else:
                        self.desktop.perform(step, self.code, self.phone)
                    self.wait(step.wait)
                    index += 1
                    continue
                digits, label, variable = READ_KINDS[step.kind]
                keyword = '' if step.kind == 'read' else step.data.get('keyword', '')
                use_first = step.kind == 'read' and step.data.get('use_first', True)
                gate = gates.setdefault(step.id, CodeGate(keyword, digits, True, use_first=use_first))
                timeout = step.data.get('timeout', 60)
                if timeout:
                    self._deadlines.setdefault(step.id, (self._tick() + timeout, timeout))
                try:
                    generation = self._pause_generation
                    text = self.desktop.read(step.data)
                    # Pause/stop may happen while the OCR engine is busy.
                    self.checkpoint()
                    if generation != self._pause_generation:
                        # A paused OCR snapshot may be stale. Capture again.
                        continue
                    self.emit({'type': 'ocr', 'text': text})
                    status, code = gate.observe(text)
                except AmbiguousCode as error:
                    self.pause(str(error))
                    self.checkpoint()
                    continue
                if status in ('first', 'new'):
                    self._deadlines.pop(step.id, None)
                    setattr(self, variable, code)
                    self.emit({'type': 'code', 'code': code, 'label': label, 'variable': variable})
                    self.log(('首次识别到有效' if status == 'first' else '识别到不同的') + label + '，继续后面的步骤')
                    self.wait(step.wait)
                    index += 1
                else:
                    messages = {'baseline': '首次识别已建立基准，等待不同数字',
                                'unchanged': label + '未变化，返回重试起点',
                                'missing': '未找到匹配的' + label + '，返回重试起点'}
                    missing_code = step.kind == 'read' and status == 'missing'
                    if missing_code:
                        messages['missing'] = '未找到六位验证码，等待 5 秒后返回重试起点'
                    self.log(messages[status])
                    self.wait(5 if missing_code else max(0.2, step.wait))
                    index = next(i for i, s in enumerate(self.workflow.steps) if s.id == step.data['retry_from'])
            self._state('completed')
            self.log('本次流程执行完成')
        except Stopped:
            self._state('stopped')
            self.log('已停止')
        except Exception as error:
            self._state('failed')
            self.log('执行失败：' + str(error))
        finally:
            self.desktop.release_all()
