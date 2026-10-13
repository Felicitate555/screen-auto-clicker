import contextlib
import unittest
from types import SimpleNamespace
from window_text import read_ema_text


class FakeEdit:
    NativeWindowHandle = 0

    def Exists(self, *args, **kwargs):
        return True

    def GetValuePattern(self):
        return SimpleNamespace(Value='【百度】验证码为：006321。')


class FakeWindow:
    Name = 'E码云短信'
    AutomationId = 'MainForm'

    def EditControl(self, **kwargs):
        assert kwargs['AutomationId'] == 'msgTextBox'
        return FakeEdit()


class WindowTextTests(unittest.TestCase):
    def module(self, windows):
        return SimpleNamespace(UIAutomationInitializerInThread=contextlib.nullcontext,
                               GetRootControl=lambda: SimpleNamespace(GetChildren=lambda: windows))

    def test_reading_sms_value_without_screenshot_or_focus(self):
        self.assertEqual(read_ema_text(self.module([FakeWindow()])), '【百度】验证码为：006321。')

    def test_no_ema_or_multiple_ema_windows_rejected(self):
        for windows in [[], [FakeWindow(), FakeWindow()]]:
            with self.assertRaises(ValueError):
                read_ema_text(self.module(windows))
