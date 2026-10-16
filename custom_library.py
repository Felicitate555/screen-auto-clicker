"""Editable local text, persisted separately from workflows and public code."""
import json
import os
import random
import tempfile
from pathlib import Path


class CustomLibrary:
    def __init__(self, path):
        self.path = Path(path)
        self.items, self.mode, self.index = [], 'sequential', 0
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            self.items = self.clean(data.get('items', []))
            self.mode = data.get('mode', 'sequential')
            if self.mode not in ('sequential', 'random', 'all'):
                raise ValueError('自定义文字库取值方式无效')
            index = data.get('next_index', 0)
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValueError('自定义文字库位置无效')
            self.index = index % len(self.items) if self.items else 0

    @staticmethod
    def clean(items):
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError('每条自定义内容必须是文字')
        result = [item.strip() for item in items if item.strip()]
        if len(result) > 5000 or any(len(item) > 10000 for item in result):
            raise ValueError('最多 5000 条内容，每条不超过 10000 字')
        return result

    def _write(self, items, mode, index):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent, delete=False) as stream:
                temporary = stream.name
                json.dump({'version': 1, 'items': items, 'mode': mode, 'next_index': index}, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, items, mode='sequential'):
        items = self.clean(items)
        if mode not in ('sequential', 'random', 'all'):
            raise ValueError('不支持的自定义文字取值方式')
        self._write(items, mode, 0)
        self.items, self.mode, self.index = items, mode, 0

    def next_value(self):
        if not self.items:
            raise ValueError('自定义文字库为空，请先点击“自定义文字库”添加内容')
        if self.mode == 'all':
            return '\n'.join(self.items)
        if self.mode == 'random':
            return random.choice(self.items)
        value = self.items[self.index]
        next_index = (self.index + 1) % len(self.items)
        self._write(self.items, self.mode, next_index)
        self.index = next_index
        return value
