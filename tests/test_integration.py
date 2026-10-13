"""Synthetic target only: actual clicks, Unicode input and OCR, no user apps."""
import time
import tkinter as tk
import unittest
import threading
import ctypes
from PIL import ImageGrab
from core import Step, extract_code
from desktop import Desktop, InputService, Recorder, enable_dpi_awareness, recorded_scroll_data
from runner import Runner
from core import Workflow
from selftest import make_fixture

enable_dpi_awareness()


class SyntheticDesktopTests(unittest.TestCase):
    def test_actual_wheel_capture_and_replay_reaches_same_position(self):
        desktop = Desktop()
        recorder = Recorder()
        service = InputService(lambda event: None, recorder)
        root = tk.Tk()
        root.title('滚动校准 · 自建测试窗口')
        root.geometry('460x240+120+120')
        root.attributes('-topmost', True)
        text = tk.Text(root)
        text.pack(fill='both', expand=True)
        text.insert('1.0', '\n'.join(f'测试行 {i}' for i in range(200)))
        original_position = desktop.mouse.position
        runner = None
        thread = None
        try:
            root.update()
            root.focus_force()
            text.focus_set()
            x, y = text.winfo_rootx()+50, text.winfo_rooty()+50
            service.start()
            service.mouse_listener.wait()
            service.keyboard_listener.wait()
            # pynput marks its thread ready before installing the Windows
            # hook. Wait for the actual hook before generating test input.
            from pynput._util.win32 import SystemHook
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                hook = SystemHook._HOOKS.get(service.mouse_listener.ident)
                if hook is not None and hook._hook:
                    break
                root.update()
                time.sleep(0.01)
            self.assertIsNotNone(hook)
            self.assertTrue(hook._hook)
            recorder.start(kinds={'scroll'})
            desktop.mouse.position = (x, y)
            root.update()
            for amount in (-1, -2):
                # Inject through Windows rather than pynput's Controller:
                # Controller also notifies same-process listeners itself,
                # which would count its native hook event twice in this test.
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, ctypes.c_uint(amount*120), 0)
                for _ in range(10):
                    root.update()
                    time.sleep(0.015)
            position = text.yview()[0]
            self.assertGreater(position, 0)
            data = recorded_scroll_data(recorder.finish())
            self.assertEqual(data['amount'], -3)
            self.assertEqual(len(data['scroll_events']), 2)
            text.yview_moveto(0)
            root.update()
            runner = Runner(Workflow('trial', [Step('scroll', data, wait=0)], start_delay=0), desktop)
            thread = threading.Thread(target=runner.run)
            thread.start()
            deadline = time.monotonic() + 3
            while thread.is_alive() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            root.update()
            self.assertEqual(runner.state, 'completed')
            self.assertAlmostEqual(text.yview()[0], position, places=5)
        finally:
            if runner:
                runner.stop()
            if thread:
                thread.join(1)
            service.stop()
            desktop.mouse.position = original_position
            root.destroy()

    def test_offline_chinese_ocr_and_leading_zero(self):
        desktop = Desktop()
        text = desktop.ocr.recognize(make_fixture('001234'))
        self.assertEqual(extract_code(text, '学生账号'), '001234')

    def test_click_and_unicode_paste_into_owned_window(self):
        desktop = Desktop()
        root = tk.Tk()
        root.title('屏幕流程助手 · 自动测试窗口')
        root.geometry('460x180+100+100')
        root.attributes('-topmost', True)
        label = tk.Label(root, text='这是自建测试窗口，只验证本软件的输入能力')
        label.pack(pady=15)
        entry = tk.Entry(root, font=('Microsoft YaHei UI', 16))
        entry.pack(padx=20, fill='x')
        original = desktop.clipboard.get()
        original_position = desktop.mouse.position
        try:
            root.update()
            root.focus_force()
            entry.focus_set()
            x = entry.winfo_rootx()+30
            y = entry.winfo_rooty()+15
            desktop.perform(Step('click', {'x': x, 'y': y}), None)
            root.update()
            desktop.perform(Step('paste', {'text': '测试账号 {{code}} 手机号 {{phone}}'}), '001234', '13800138000')
            root.update()
            self.assertEqual(entry.get(), '测试账号 001234 手机号 13800138000')
        finally:
            desktop.release_all()
            if original is not None:
                desktop.clipboard.set(original)
            desktop.mouse.position = original_position
            root.destroy()

    def test_screen_region_capture_reads_owned_message(self):
        desktop = Desktop()
        root = tk.Tk()
        root.geometry('850x160+120+120')
        root.attributes('-topmost', True)
        label = tk.Label(root, text='【学生账号】验证码为：001234。', bg='white', font=('Microsoft YaHei UI', 24))
        label.pack(fill='both', expand=True)
        try:
            root.update()
            time.sleep(0.1)
            region = [label.winfo_rootx(), label.winfo_rooty(), label.winfo_rootx()+label.winfo_width(), label.winfo_rooty()+label.winfo_height()]
            text = desktop.read({'region': region, 'confidence': 0.8})
            self.assertEqual(extract_code(text, '学生账号'), '001234')
        finally:
            root.destroy()


if __name__ == '__main__':
    enable_dpi_awareness()
    unittest.main()
