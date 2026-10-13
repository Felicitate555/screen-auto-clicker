"""Windows input, local OCR and explicit-session recording adapters."""
import copy
import ctypes
from ctypes import wintypes
import statistics
import subprocess
import threading
import time
from pathlib import Path
from PIL import ImageGrab
from pynput import keyboard, mouse
from core import Step, AmbiguousCode, number, validate_scroll_events


def enable_dpi_awareness():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def screen_bounds():
    u = ctypes.windll.user32
    return tuple(u.GetSystemMetrics(n) for n in (76, 77, 78, 79))


def parse_key(name):
    aliases = {'control': 'ctrl', 'escape': 'esc', 'return': 'enter', 'win': 'cmd',
               'windows': 'cmd', 'plus': '+', 'spacebar': 'space'}
    name = aliases.get(name.lower(), name)
    if name.startswith('vk:'):
        try:
            value = int(name[3:])
            if not 0 <= value <= 255:
                raise ValueError()
            return keyboard.KeyCode.from_vk(value)
        except ValueError as error:
            raise ValueError('无效的虚拟键码') from error
    if len(name) == 1:
        return name
    key = getattr(keyboard.Key, name.lower(), None)
    if key is None:
        raise ValueError('未知按键：' + name)
    return key


def key_name(key):
    if isinstance(key, keyboard.Key):
        return key.name
    if getattr(key, 'vk', None) is not None:
        return 'vk:' + str(key.vk)
    return key.char


def ocr_text(rows, confidence):
    if not rows:
        return ''
    items = []
    for box, text, score in rows:
        if not text.strip():
            continue
        if score < confidence:
            raise AmbiguousCode(f'区域中有低置信度文字（{score:.0%}），请放大消息或缩小区域后继续')
        xs, ys = zip(*box)
        items.append((min(xs), min(ys), max(ys), text))
    if not items:
        return ''
    height = statistics.median(max(1, item[2] - item[1]) for item in items)
    items.sort(key=lambda item: ((item[1] + item[2]) / 2, item[0]))
    lines = []
    for item in items:
        center = (item[1] + item[2]) / 2
        if lines and abs(center - lines[-1]['center']) < height * 0.5:
            lines[-1]['items'].append(item)
            lines[-1]['bottom'] = max(lines[-1]['bottom'], item[2])
        else:
            lines.append({'center': center, 'top': item[1], 'bottom': item[2], 'items': [item]})
    result = ''
    last_bottom = None
    for line in lines:
        if last_bottom is not None:
            result += '\n\n' if line['top'] - last_bottom > height * 0.9 else '\n'
        result += ' '.join(item[3] for item in sorted(line['items'], key=lambda item: item[0]))
        last_bottom = line['bottom']
    return result


class LocalOCR:
    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def recognize(self, image, confidence=0):
        with self._lock:
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self._engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                                        text_score=0.0, use_cls=False)
            # PIL uses RGB; RapidOCR accepts a numpy BGR array.
            import numpy as np
            result, _ = self._engine(np.asarray(image.convert('RGB'))[:, :, ::-1].copy(),
                                     use_cls=False, text_score=0.0)
            return ocr_text(result, confidence)


class Clipboard:
    def __init__(self):
        self.u = ctypes.windll.user32
        self.k = ctypes.windll.kernel32
        self.k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.k.GlobalAlloc.restype = ctypes.c_void_p
        self.k.GlobalLock.argtypes = [ctypes.c_void_p]
        self.k.GlobalLock.restype = ctypes.c_void_p
        self.k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.k.GlobalFree.argtypes = [ctypes.c_void_p]
        self.u.GetClipboardData.argtypes = [wintypes.UINT]
        self.u.GetClipboardData.restype = ctypes.c_void_p
        self.u.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        self.u.SetClipboardData.restype = ctypes.c_void_p

    def _open(self):
        for _ in range(20):
            if self.u.OpenClipboard(None):
                return
            time.sleep(0.015)
        raise RuntimeError('剪贴板正被其他程序占用，请稍后重试')

    def get(self):
        self._open()
        try:
            handle = self.u.GetClipboardData(13)
            if not handle:
                return None
            pointer = self.k.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.wstring_at(pointer)
            finally:
                self.k.GlobalUnlock(handle)
        finally:
            self.u.CloseClipboard()

    def set(self, text):
        raw = text.encode('utf-16-le') + b'\x00\x00'
        handle = self.k.GlobalAlloc(0x0002, len(raw))
        if not handle:
            raise RuntimeError('无法分配剪贴板内存')
        transferred = False
        try:
            pointer = self.k.GlobalLock(handle)
            if not pointer:
                raise RuntimeError('无法锁定剪贴板内存')
            ctypes.memmove(pointer, raw, len(raw))
            self.k.GlobalUnlock(handle)
            self._open()
            try:
                if not self.u.EmptyClipboard() or not self.u.SetClipboardData(13, handle):
                    raise RuntimeError('无法写入剪贴板')
                transferred = True
            finally:
                self.u.CloseClipboard()
        finally:
            if not transferred:
                self.k.GlobalFree(handle)


class Desktop:
    def __init__(self):
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()
        self.ocr = LocalOCR()
        self.clipboard = Clipboard()
        self.held = set()
        self.lock = threading.RLock()

    def validate(self, workflow):
        for step in workflow.steps:
            if step.kind == 'hotkey':
                for key in step.data['keys']:
                    parse_key(key)
            elif step.kind == 'key_event':
                parse_key(step.data['key'])
            elif step.kind == 'launch' and not Path(step.data['path']).is_file():
                raise ValueError('找不到软件文件：' + step.data['path'])

    def perform(self, step, code, phone=None):
        data = step.data
        with self.lock:
            if step.kind == 'launch':
                # Shell-free executable launch; optional arguments are a list.
                subprocess.Popen([data['path'], *data.get('args', [])], cwd=str(Path(data['path']).parent))
            elif step.kind == 'click':
                self.mouse.position = (int(data['x']), int(data['y']))
                self.mouse.click(getattr(mouse.Button, data.get('button', 'left')), data.get('count', 1))
            elif step.kind == 'scroll':
                self.mouse.position = (int(data['x']), int(data['y']))
                self.mouse.scroll(0, int(data['amount']))
            elif step.kind == 'hotkey':
                keys = [parse_key(k) for k in data['keys']]
                try:
                    for key in keys:
                        self.keyboard.press(key)
                        self.held.add(key)
                finally:
                    for key in reversed(keys):
                        self.keyboard.release(key)
                        self.held.discard(key)
            elif step.kind == 'key_event':
                key = parse_key(data['key'])
                if data['action'] == 'press':
                    self.keyboard.press(key)
                    self.held.add(key)
                else:
                    self.keyboard.release(key)
                    self.held.discard(key)
            elif step.kind == 'paste':
                text = data['text']
                if '{{code}}' in text:
                    if code is None:
                        raise ValueError('本次运行还没有获取到新六位数字')
                    text = text.replace('{{code}}', code)
                if '{{phone}}' in text:
                    if phone is None:
                        raise ValueError('本次运行还没有获取到新十一位手机号')
                    text = text.replace('{{phone}}', phone)
                if '{{praise}}' in text:
                    from praise_library import next_praise
                    text = text.replace('{{praise}}', next_praise())
                self.clipboard.set(text)
                self.keyboard.press(keyboard.Key.ctrl)
                try:
                    if data.get('replace_existing', True):
                        self.keyboard.press('a')
                        self.keyboard.release('a')
                    self.keyboard.press('v')
                    self.keyboard.release('v')
                finally:
                    self.keyboard.release(keyboard.Key.ctrl)
                # Keep the text available until the target processes Ctrl+V;
                # early restoration can paste stale clipboard contents.

    def read(self, data):
        if data.get('source') == 'ema_text':
            from window_text import read_ema_text
            return read_ema_text()
        image = ImageGrab.grab(bbox=tuple(int(v) for v in data['region']), all_screens=True)
        return self.ocr.recognize(image, data.get('confidence', 0))

    def release_all(self):
        with self.lock:
            for key in list(self.held):
                try:
                    self.keyboard.release(key)
                except Exception:
                    pass
            self.held.clear()

    def suspend_keys(self):
        with self.lock:
            modifiers = {getattr(keyboard.Key, name) for name in
                         ('ctrl', 'ctrl_l', 'ctrl_r', 'alt', 'alt_l', 'alt_r', 'alt_gr',
                          'shift', 'shift_l', 'shift_r', 'cmd', 'cmd_l', 'cmd_r')}
            saved = [key for key in self.held if key in modifiers]
            self.release_all()
            return saved

    def restore_keys(self, keys):
        with self.lock:
            for key in keys:
                self.keyboard.press(key)
                self.held.add(key)


def recorded_scroll_data(steps):
    scrolls = [step for step in steps if step.kind == 'scroll' and step.data.get('amount')]
    if not scrolls:
        raise ValueError('没有记录到竖直滚动，请重新录入')
    events = [{'amount': step.data['amount'], 'delay': 0 if index == 0 else scrolls[index-1].wait}
              for index, step in enumerate(scrolls)]
    validate_scroll_events(events)
    amount = sum(event['amount'] for event in events)
    number(amount, '滚动总格数', -1000, 1000)
    return {'x': scrolls[0].data['x'], 'y': scrolls[0].data['y'], 'amount': amount, 'scroll_events': events}


class Recorder:
    def __init__(self):
        self.active = False
        self.steps = []
        self.last = 0
        self.lock = threading.RLock()
        self.kinds = None

    def start(self, now=None, kinds=None):
        with self.lock:
            self.steps = []
            self.last = time.monotonic() if now is None else now
            self.active = True
            self.kinds = kinds

    def record(self, kind, data, now=None):
        with self.lock:
            if not self.active or (self.kinds is not None and kind not in self.kinds):
                return
            now = time.monotonic() if now is None else now
            gap = round(max(0, now - self.last), 3)
            if self.steps:
                self.steps[-1].wait = gap
            elif gap > 0.15:
                self.steps.append(Step('wait', wait=gap, title='录制开始等待'))
            self.steps.append(Step(kind, data, wait=0))
            self.last = now

    def finish(self, now=None):
        with self.lock:
            self.active = False
            now = time.monotonic() if now is None else now
            if self.steps:
                self.steps[-1].wait = round(max(0, now - self.last), 3)
            # Guarantee held recording keys are released on replay even when
            # the user finishes a recording mid-chord.
            held = {}
            for step in self.steps:
                if step.kind == 'key_event':
                    key = step.data['key']
                    if step.data['action'] == 'press':
                        held[key] = True
                    else:
                        held.pop(key, None)
            for key in held:
                self.steps.append(Step('key_event', {'key': key, 'action': 'release'}, wait=0))
            return copy.deepcopy(self.steps)


class InputService:
    """Listeners send UI work to a queue; callbacks never touch Tk widgets."""
    def __init__(self, emit, recorder):
        self.emit = emit
        self.recorder = recorder
        self.pressed = set()
        self.keyboard_listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.mouse_listener = mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll)

    def start(self):
        self.keyboard_listener.start()
        self.mouse_listener.start()

    def stop(self):
        self.keyboard_listener.stop()
        self.mouse_listener.stop()

    def on_press(self, key):
        name = key_name(key)
        if name in ('f6', 'f8', 'f9', 'f10'):
            if name not in self.pressed:
                self.pressed.add(name)
                if name == 'f8' and self.recorder.active:
                    steps = self.recorder.finish()
                    self.emit({'type': 'recorded', 'steps': steps})
                else:
                    self.emit({'type': 'hotkey', 'key': name})
            return
        if name:
            self.recorder.record('key_event', {'key': name, 'action': 'press'})

    def on_release(self, key):
        name = key_name(key)
        if name in ('f6', 'f8', 'f9', 'f10'):
            self.pressed.discard(name)
            return
        if name:
            self.recorder.record('key_event', {'key': name, 'action': 'release'})

    def on_click(self, x, y, button, pressed):
        if pressed:
            self.recorder.record('click', {'x': int(x), 'y': int(y), 'button': button.name, 'count': 1})

    def on_scroll(self, x, y, dx, dy):
        self.recorder.record('scroll', {'x': int(x), 'y': int(y), 'amount': int(dy)})
