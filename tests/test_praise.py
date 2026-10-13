import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from core import Step
from desktop import Desktop


class PraiseTests(unittest.TestCase):
    def test_library_has_one_hundred_distinct_short_lines(self):
        from praise_library import PRAISE_LINES
        self.assertEqual(len(PRAISE_LINES), 100)
        self.assertEqual(len(set(PRAISE_LINES)), 100)
        self.assertTrue(all(0 < len(line) <= 10 for line in PRAISE_LINES))

    def test_paste_expands_praise_variable_once(self):
        received = []
        desktop = Desktop.__new__(Desktop)
        desktop.lock = threading.RLock()
        desktop.clipboard = SimpleNamespace(set=received.append)
        desktop.keyboard = SimpleNamespace(press=lambda key: None, release=lambda key: None)
        with patch('praise_library.random.choice', return_value='家国情怀动人') as choose:
            desktop.perform(Step('paste', {'text': '{{praise}}，{{praise}} {{code}}'}), '142716')
            choose.assert_called_once()
        self.assertEqual(received, ['家国情怀动人，家国情怀动人 142716'])
