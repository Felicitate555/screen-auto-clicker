import tempfile
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace


class CustomLibraryTests(unittest.TestCase):
    def test_new_library_starts_empty_without_seed_data(self):
        from custom_library import CustomLibrary
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '私人文字库.json'
            library = CustomLibrary(path)
            self.assertEqual(library.items, [])
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                library.next_value()

    def test_paste_uses_one_entry_for_each_input(self):
        from custom_library import CustomLibrary
        from desktop import Desktop
        with tempfile.TemporaryDirectory() as folder:
            library = CustomLibrary(Path(folder) / 'local.json')
            library.save(['第一条', '第二条'])
            received = []
            desktop = Desktop.__new__(Desktop)
            desktop._custom_library = library
            desktop.lock = threading.RLock()
            desktop.clipboard = SimpleNamespace(set=received.append)
            desktop.keyboard = SimpleNamespace(press=lambda key: None, release=lambda key: None)
            from core import Step
            desktop.perform(Step('paste', {'text': '{{custom}} / {{custom}}'}), None)
            desktop.perform(Step('paste', {'text': '{{custom}}'}), None)
            self.assertEqual(received, ['第一条 / 第一条', '第二条'])

    def test_sequential_values_wrap_and_continue_after_reload(self):
        from custom_library import CustomLibrary
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'local.json'
            library = CustomLibrary(path)
            library.save(['第一条', '第二条'], 'sequential')
            self.assertEqual(library.next_value(), '第一条')
            restored = CustomLibrary(path)
            self.assertEqual(restored.next_value(), '第二条')
            self.assertEqual(restored.next_value(), '第一条')

    def test_save_edit_and_all_mode(self):
        from custom_library import CustomLibrary
        with tempfile.TemporaryDirectory() as folder:
            library = CustomLibrary(Path(folder) / 'local.json')
            library.save([' 原内容 ', '', '下一条'], 'all')
            self.assertEqual(library.next_value(), '原内容\n下一条')
            library.save(['修改内容'], 'sequential')
            self.assertEqual(library.next_value(), '修改内容')
