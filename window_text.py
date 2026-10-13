"""Read-only EMA textbox access. No clicks, focus changes or network calls."""
import ctypes
from ctypes import wintypes


def native_edit_text(handle):
    user = ctypes.windll.user32
    send = user.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    send.restype = ctypes.c_ssize_t
    length = ctypes.c_size_t()
    if not send(handle, 0x000E, 0, 0, 2, 1000, ctypes.byref(length)):
        return None
    if length.value > 200000:
        raise ValueError('短信内容过长，无法读取')
    buffer = ctypes.create_unicode_buffer(length.value + 1)
    copied = ctypes.c_size_t()
    if not send(handle, 0x000D, len(buffer), ctypes.addressof(buffer), 2, 1000, ctypes.byref(copied)):
        return None
    return buffer.value


def read_ema_text(auto_module=None):
    if auto_module is None:
        import uiautomation as auto_module
    with auto_module.UIAutomationInitializerInThread():
        windows = [window for window in auto_module.GetRootControl().GetChildren()
                   if window.Name == 'E码云短信' and window.AutomationId == 'MainForm']
        if not windows:
            raise ValueError('未找到 ema 的“E码云短信”窗口，请先打开软件')
        if len(windows) != 1:
            raise ValueError('有多个 ema 窗口，请保留一个后再试读')
        edit = windows[0].EditControl(searchDepth=10, AutomationId='msgTextBox')
        if not edit.Exists(maxSearchSeconds=1, searchIntervalSeconds=0.1):
            raise ValueError('未找到收取短信框，请将 ema 切换到“操作中心”页')
        if edit.NativeWindowHandle:
            text = native_edit_text(edit.NativeWindowHandle)
            if text is not None:
                return text
        pattern = edit.GetValuePattern()
        if pattern is None:
            raise ValueError('短信框不支持直接读取，可切换回截图识别')
        return pattern.Value or ''
