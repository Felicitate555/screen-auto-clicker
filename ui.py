"""Chinese workflow editor. Tk only runs on the main thread."""
import copy
import ctypes
import queue
import sys
import threading
import time
import subprocess
import tkinter as tk
import uuid
from dataclasses import asdict
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from core import Step, Workflow, KINDS, READ_KINDS, extract_code, number
from desktop import Desktop, InputService, Recorder, screen_bounds, recorded_scroll_data
from runner import Runner

BG = '#F4F6F9'
INK = '#172B46'
MUTED = '#526178'
BLUE = '#245DCC'


def app_folder():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent


class App(ctk.CTk):
    def __init__(self, listeners=True):
        ctk.set_appearance_mode('light')
        super().__init__()
        self.title('屏幕流程助手 · 本地版 v1.7')
        self.geometry('1160x820')
        self.minsize(1020, 720)
        self.configure(fg_color=BG)
        self.font = ('Microsoft YaHei UI', 13)
        self.flow = Workflow('我的流程')
        self.path = None
        self.selected = None
        self.fields = {}
        self.retry_ids = {}
        self.dirty = False
        self.refreshing = False
        self.events = queue.Queue()
        self.runner = None
        self.worker = None
        self.desktop = Desktop()
        self.recorder = Recorder()
        self.record_pending = False
        self.record_generation = 0
        self.scroll_capture_id = None
        self.trial_step_id = None
        self.point_pending = None
        self.preview_busy = False
        self.closed = False
        self.edit_buttons = []
        self.name_var = tk.StringVar(value=self.flow.name)
        self.repeat_var = tk.StringVar(value=str(self.flow.repetitions))
        self.status_var = tk.StringVar(value='就绪')
        self.code_var = tk.StringVar(value='本次新数据：尚未获取')
        self.ocr_var = tk.StringVar(value='验证码默认首次有效识别直接使用；手机号首次建立基准。')
        self._layout()
        self.service = InputService(self.events.put, self.recorder) if listeners else None
        if self.service:
            self.service.start()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-s>', lambda event: self.save_flow())
        self.bind('<Control-o>', lambda event: self.open_flow())
        self.timer = self.after(50, self.process_events)
        self.build_editor()

    def button(self, parent, text, command, primary=False, editable=False, **kwargs):
        button = ctk.CTkButton(parent, text=text, command=command, height=34, width=kwargs.pop('width', 92),
                              font=self.font, corner_radius=6,
                              fg_color=BLUE if primary else '#E5EBF4',
                              text_color='white' if primary else INK,
                              hover_color='#194BA8' if primary else '#D3DEEE', **kwargs)
        if editable:
            self.edit_buttons.append(button)
        return button

    def _layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(self, fg_color='white', corner_radius=0)
        header.grid(row=0, column=0, sticky='ew')
        ctk.CTkLabel(header, text='屏幕流程助手', font=('Microsoft YaHei UI', 25, 'bold'),
                     text_color=INK).pack(side='left', padx=24, pady=16)
        ctk.CTkLabel(header, text='手动编排 / 本地保存', font=self.font,
                     text_color=MUTED).pack(side='left', padx=8)
        ctk.CTkLabel(header, text='运行次数', font=self.font, text_color=MUTED).pack(side='left', padx=(12, 5))
        self.repeat_entry = ctk.CTkEntry(header, textvariable=self.repeat_var, width=70, height=34, font=self.font)
        self.repeat_entry.pack(side='left')
        ctk.CTkLabel(header, textvariable=self.status_var, font=self.font, text_color=BLUE,
                     fg_color='#EDF3FF', corner_radius=5, width=95, height=30).pack(side='right', padx=24)
        self.button(header, '练习窗口', self.open_demo).pack(side='right', padx=8)

        toolbar = ctk.CTkFrame(self, fg_color='transparent')
        toolbar.grid(row=1, column=0, sticky='ew', padx=22, pady=(12, 10))
        ctk.CTkLabel(toolbar, text='流程名称', font=self.font, text_color=MUTED).pack(side='left')
        self.name_entry = ctk.CTkEntry(toolbar, textvariable=self.name_var, width=180, font=self.font, height=34)
        self.name_entry.pack(side='left', padx=(8, 14))
        for text, command in [('新建', self.new_flow), ('打开', self.open_flow), ('保存', self.save_flow)]:
            self.button(toolbar, text, command, editable=True, width=65).pack(side='left', padx=3)
        self.record_button = self.button(toolbar, '录制 F8', self.toggle_record, editable=True)
        self.record_button.pack(side='left', padx=(14, 3))
        self.stop_button = self.button(toolbar, '停止 F10', self.stop_run)
        self.stop_button.pack(side='right', padx=(6, 0))
        self.pause_button = self.button(toolbar, '暂停 F9', self.toggle_pause)
        self.pause_button.pack(side='right', padx=3)
        self.start_button = self.button(toolbar, '开始运行', self.start_run, primary=True)
        self.start_button.pack(side='right', padx=3)

        middle = ctk.CTkFrame(self, fg_color='transparent')
        middle.grid(row=2, column=0, sticky='nsew', padx=22)
        middle.grid_columnconfigure(0, weight=6, minsize=420)
        middle.grid_columnconfigure(1, weight=5, minsize=420)
        middle.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(middle, fg_color='white', corner_radius=9)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(left, text='操作步骤', font=('Microsoft YaHei UI', 17, 'bold'),
                     text_color=INK).grid(row=0, column=0, sticky='w', padx=16, pady=(12, 5))
        addbar = ctk.CTkFrame(left, fg_color='transparent')
        addbar.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 10))
        self.kind_menu = ctk.CTkOptionMenu(addbar, values=[v for k, v in KINDS.items() if k != 'key_event'],
                                         font=self.font, dropdown_font=self.font, width=190,
                                         fg_color='#E5EBF4', text_color=INK, button_color='#D3DEEE',
                                         button_hover_color='#BFCFE6')
        self.kind_menu.set('点击')
        self.kind_menu.pack(side='left')
        self.button(addbar, '添加步骤', self.add_selected, primary=True, editable=True).pack(side='left', padx=8)

        table = tk.Frame(left, bg='white')
        table.grid(row=2, column=0, sticky='nsew', padx=16)
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.theme_use('clam')
        scale = left._get_widget_scaling()
        style.configure('Flow.Treeview', background='white', foreground=INK, font=('Microsoft YaHei UI', 11),
                        rowheight=int(34*scale), borderwidth=0, fieldbackground='white')
        style.configure('Flow.Treeview.Heading', font=('Microsoft YaHei UI', 10), background='#EEF2F7',
                        foreground=MUTED, borderwidth=0, padding=7)
        style.map('Flow.Treeview', background=[('selected', '#E2ECFF')], foreground=[('selected', INK)])
        self.tree = ttk.Treeview(table, columns=('index', 'kind', 'title', 'wait'), show='headings',
                                 selectmode='browse', style='Flow.Treeview')
        for column, title, width in [('index', '#', 36), ('kind', '动作', 135),
                                      ('title', '名称 / 内容', 185), ('wait', '等待', 64)]:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=int(width*scale), minwidth=int((width if column != 'title' else 90)*scale),
                             stretch=column == 'title', anchor='w' if column == 'title' else 'center')
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(table, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        order = ctk.CTkFrame(left, fg_color='transparent')
        order.grid(row=3, column=0, sticky='ew', padx=16, pady=12)
        for text, command in [('上移', lambda: self.move_step(-1)), ('下移', lambda: self.move_step(1)),
                               ('复制', self.duplicate_step), ('删除', self.delete_step)]:
            self.button(order, text, command, editable=True, width=70).pack(side='left', padx=(0, 7))

        right = ctk.CTkFrame(middle, fg_color='white', corner_radius=9)
        right.grid(row=0, column=1, sticky='nsew')
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(right, text='步骤设置', font=('Microsoft YaHei UI', 17, 'bold'),
                     text_color=INK).grid(row=0, column=0, sticky='w', padx=16, pady=(12, 6))
        self.editor = ctk.CTkScrollableFrame(right, fg_color='white', corner_radius=0)
        self.editor.grid(row=1, column=0, sticky='nsew', padx=6)
        self.editor.grid_columnconfigure(0, weight=1)
        self.apply_button = self.button(right, '应用当前设置', self.apply_editor, primary=True, editable=True)
        self.apply_button.grid(row=2, column=0, sticky='ew', padx=16, pady=(8, 14))

        lower = ctk.CTkFrame(self, fg_color='white', corner_radius=9)
        lower.grid(row=3, column=0, sticky='ew', padx=22, pady=(12, 8))
        lower.grid_columnconfigure(0, weight=1)
        lower.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(lower, text='运行记录', font=('Microsoft YaHei UI', 14, 'bold'),
                     text_color=INK).grid(row=0, column=0, sticky='w', padx=16, pady=(9, 4))
        ctk.CTkLabel(lower, textvariable=self.code_var, font=('Microsoft YaHei UI', 14, 'bold'),
                     text_color=BLUE).grid(row=0, column=1, sticky='w', padx=16, pady=(9, 4))
        self.log_box = ctk.CTkTextbox(lower, height=115, font=('Microsoft YaHei UI', 11),
                                     fg_color='#F8FAFD', text_color=INK, corner_radius=5)
        self.log_box.grid(row=1, column=0, sticky='ew', padx=(16, 8), pady=(0, 12))
        self.log_box.configure(state='disabled')
        self.ocr_label = ctk.CTkLabel(lower, textvariable=self.ocr_var, font=self.font,
                                    text_color=MUTED, justify='left', anchor='nw', wraplength=450)
        self.ocr_label.grid(row=1, column=1, sticky='nsew', padx=16, pady=(3, 12))
        ctk.CTkLabel(self, text='F6 鼠标取点    ·    F8 录制 / 结束    ·    F9 暂停 / 继续    ·    F10 停止    |    坐标按屏幕位置执行',
                     font=('Microsoft YaHei UI', 11), text_color=MUTED).grid(row=4, column=0, pady=(0, 9))

    def busy(self):
        return bool(self.worker and self.worker.is_alive()) or self.recorder.active or self.record_pending or self.preview_busy

    def log(self, message):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', time.strftime('%H:%M:%S') + '  ' + message + '\n')
        if int(self.log_box.index('end-1c').split('.')[0]) > 600:
            self.log_box.delete('1.0', '101.0')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def field(self, key, label, value, multiline=False):
        ctk.CTkLabel(self.editor, text=label, font=self.font, text_color=INK, anchor='w').pack(fill='x', pady=(8, 4))
        if multiline:
            widget = ctk.CTkTextbox(self.editor, height=95, font=self.font, border_width=1, border_color='#CCD5E2')
            widget.insert('1.0', str(value))
        else:
            widget = ctk.CTkEntry(self.editor, font=self.font, height=33)
            widget.insert(0, str(value))
        widget.pack(fill='x', padx=(0, 6))
        self.fields[key] = widget
        return widget

    def hint(self, text):
        label = ctk.CTkLabel(self.editor, text=text, font=('Microsoft YaHei UI', 11),
                            text_color=MUTED, justify='left', anchor='w', wraplength=380)
        label.pack(fill='x', pady=(5, 3))

    def current(self):
        return next((step for step in self.flow.steps if step.id == self.selected), None)

    def build_editor(self):
        for widget in self.editor.winfo_children():
            widget.destroy()
        self.fields = {}
        self.retry_ids = {}
        step = self.current()
        if step is None:
            self.hint('从左侧添加操作步骤。\n\n先安排“刷新消息”等操作，再添加读取六位数字或十一位手机号步骤，最后添加点击输入框和输入文字。\n\n保存后，下次可打开整个流程继续编辑。')
            return
        ctk.CTkLabel(self.editor, text=KINDS[step.kind], font=('Microsoft YaHei UI', 16, 'bold'),
                     text_color=BLUE).pack(anchor='w', pady=(4, 5))
        self.field('title', '步骤名称（可选）', step.title)
        data = step.data
        if step.kind == 'launch':
            self.field('path', '软件路径（EXE）', data.get('path', ''))
            self.button(self.editor, '选择软件', self.choose_exe).pack(anchor='w', pady=6)
        elif step.kind in ('click', 'scroll'):
            if step.kind == 'scroll':
                tools = ctk.CTkFrame(self.editor, fg_color='transparent')
                tools.pack(fill='x', pady=8)
                self.button(tools, '实际滚动录入', self.capture_scroll, width=135).pack(side='left', padx=(0, 8))
                self.button(tools, '试滚当前步骤', self.preview_scroll, width=135).pack(side='left')
                if data.get('scroll_events'):
                    self.hint(f"已录入 {len(data['scroll_events'])} 个动作，保留原节奏。修改总刻度会切换为手动设置。")
                self.hint('2 秒后开始录入。亲自滚到合适位置，F8 完成，F10 取消；鼠标位置也会记录。试滚前恢复同一起点。')
                self.field('amount', '滚轮刻度：正数向上，负数向下（不是像素）', data.get('amount', -3))
            self.field('x', '屏幕 X 坐标', data.get('x', 0))
            self.field('y', '屏幕 Y 坐标', data.get('y', 0))
            self.button(self.editor, '鼠标取点 F6', self.pick_point).pack(anchor='w', pady=7)
            self.hint('点击取点后，将鼠标移到目标位置，按 F6。窗口位置或分辨率改变后需要重新取点。')
            if step.kind == 'click':
                self.field('button', '鼠标按键：left / right / middle', data.get('button', 'left'))
                self.field('count', '点击次数：1 单击 / 2 双击', data.get('count', 1))
        elif step.kind == 'hotkey':
            self.field('keys', '按键，用 + 连接', '+'.join(data.get('keys', ['ctrl', 'r'])))
            self.hint('例如 ctrl+r、alt+tab、enter、ctrl+shift+a。单独的加号使用 plus。')
        elif step.kind == 'key_event':
            self.field('key', '录制按键', data.get('key', 'enter'))
            self.field('action', '动作：press / release', data.get('action', 'press'))
        elif step.kind == 'paste':
            self.field('text', '输入内容', data.get('text', ''), multiline=True)
            self.replace_var = tk.BooleanVar(value=data.get('replace_existing', True))
            ctk.CTkCheckBox(self.editor, text='选中输入框原文字并替换', variable=self.replace_var,
                           font=self.font, text_color=INK).pack(anchor='w', pady=(8, 4))
            tools = ctk.CTkFrame(self.editor, fg_color='transparent')
            tools.pack(fill='x', pady=7)
            self.button(tools, '插入验证码', self.insert_code, width=130).pack(side='left', padx=(0, 8))
            self.button(tools, '插入手机号', self.insert_phone, width=130).pack(side='left')
            self.button(self.editor, '插入视频评价', self.insert_praise, width=150).pack(anchor='w', pady=(0, 6))
            self.hint('{{praise}} 从 100 句爱国主题视频评价中随机选一句，每句不超过 10 字。{{code}} 为六位数字；{{phone}} 为手机号。先安排点击输入框。')
        elif step.kind in READ_KINDS:
            phone_mode = step.kind == 'read_phone'
            if phone_mode:
                self.field('keyword', '关键词（可选；留空读取整个框选区域）', data.get('keyword', ''))
            else:
                self.hint('验证码不需要关键词。可以选择直接读取 ema 的短信文字，或继续使用截图识别。')
                ctk.CTkLabel(self.editor, text='读取来源', font=self.font, text_color=INK).pack(anchor='w', pady=(5, 4))
                self.source_menu = ctk.CTkOptionMenu(self.editor, values=['截图识别', 'ema 短信框文字'],
                                                    command=self.change_read_source, font=self.font,
                                                    dropdown_font=self.font, fg_color='#E5EBF4', text_color=INK,
                                                    button_color='#D3DEEE')
                self.source_menu.pack(fill='x', padx=(0, 6), pady=(0, 6))
                self.source_menu.set('ema 短信框文字' if data.get('source') == 'ema_text' else '截图识别')
                self.first_read_var = tk.BooleanVar(value=data.get('use_first', True))
                ctk.CTkCheckBox(self.editor, text='首次识别到验证码就直接使用', variable=self.first_read_var,
                               font=self.font, text_color=INK).pack(anchor='w', pady=(5, 8))
            direct_text = step.kind == 'read' and data.get('source') == 'ema_text'
            if direct_text:
                self.hint('直接读取 ema 的收取短信框，不需要放大文字、框选区域或设置置信度。ema 请保持在“操作中心”页。')
            else:
                region = data.get('region', [0, 0, 0, 0])
                self.field('region', '识别区域：左, 上, 右, 下', ', '.join(map(str, region)))
            tools = ctk.CTkFrame(self.editor, fg_color='transparent')
            tools.pack(fill='x', pady=7)
            if not direct_text:
                self.button(tools, '框选区域', self.pick_region).pack(side='left', padx=(0, 8))
            self.button(tools, '试读短信' if direct_text else '试读区域', self.preview_region).pack(side='left')
            ctk.CTkLabel(self.editor, text='没有变化时返回哪一步', font=self.font, text_color=INK).pack(anchor='w', pady=(8, 4))
            index = self.flow.steps.index(step)
            self.retry_ids = {f'{i+1}. {s.title or KINDS[s.kind]}': s.id for i, s in enumerate(self.flow.steps[:index])}
            options = list(self.retry_ids) or ['先在前面添加重试操作']
            self.retry_menu = ctk.CTkOptionMenu(self.editor, values=options, font=self.font, dropdown_font=self.font,
                                              fg_color='#E5EBF4', text_color=INK, button_color='#D3DEEE')
            self.retry_menu.pack(fill='x', padx=(0, 6))
            self.retry_menu.set(next((key for key, sid in self.retry_ids.items() if sid == data.get('retry_from')), options[0]))
            self.field('timeout', '最长等待秒数（0 表示不限；超时暂停）', data.get('timeout', 60))
            if not direct_text:
                self.field('confidence', '最低识别置信度（0–1；0 表示不拦截）', data.get('confidence', 0))
            self.hint(('手机号首次只建立基准。' if phone_mode else '勾选时首次有效识别直接使用；取消勾选时先建立基准。') +
                      '后续数字变化才继续。重试包含起点到当前识别步骤。')
        self.field('wait', '执行后等待（秒）', step.wait)
        if step.kind in READ_KINDS:
            self.hint('未读到六位验证码时等待 5 秒再重试；优先提取“验证码”后的六位数字。' if not phone_mode else
                      '重试时至少间隔 0.2 秒，避免连续空转。试读不会建立运行基准。')
        if self.busy():
            self.disable_editor()

    def disable_editor(self):
        def disable(widget):
            if isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox, ctk.CTkButton, ctk.CTkOptionMenu, ctk.CTkCheckBox)):
                widget.configure(state='disabled')
            else:
                for child in widget.winfo_children():
                    disable(child)
        disable(self.editor)

    def get_field(self, key):
        widget = self.fields[key]
        return widget.get('1.0', 'end-1c') if isinstance(widget, ctk.CTkTextbox) else widget.get()

    def put_field(self, key, value):
        widget = self.fields.get(key)
        if widget is None:
            return
        if isinstance(widget, ctk.CTkTextbox):
            widget.delete('1.0', 'end')
            widget.insert('1.0', str(value))
        else:
            widget.delete(0, 'end')
            widget.insert(0, str(value))

    def commit_editor(self):
        if self.busy():
            return
        try:
            repetitions = int(self.repeat_var.get().strip())
        except ValueError as error:
            raise ValueError('运行次数必须是 1 到 99999 的整数') from error
        if not 1 <= repetitions <= 99999:
            raise ValueError('运行次数必须是 1 到 99999 的整数')
        if repetitions != self.flow.repetitions:
            self.flow.repetitions = repetitions
            self.dirty = True
        name = self.name_var.get().strip() or '我的流程'
        if name != self.flow.name:
            self.flow.name = name
            self.dirty = True
        step = self.current()
        if step is None or not self.fields:
            return
        before = asdict(step)
        data = copy.deepcopy(step.data)
        try:
            wait = float(self.get_field('wait'))
            number(wait, '等待秒数')
            if step.kind == 'launch':
                data['path'] = self.get_field('path').strip()
            elif step.kind in ('click', 'scroll'):
                data.update(x=int(self.get_field('x')), y=int(self.get_field('y')))
                if step.kind == 'click':
                    data.update(button=self.get_field('button').strip().lower(), count=int(self.get_field('count')))
                else:
                    data['amount'] = int(self.get_field('amount'))
                    if data['amount'] != step.data.get('amount'):
                        data.pop('scroll_events', None)
            elif step.kind == 'hotkey':
                data['keys'] = [k.strip() for k in self.get_field('keys').split('+') if k.strip()]
            elif step.kind == 'key_event':
                data.update(key=self.get_field('key').strip(), action=self.get_field('action').strip())
            elif step.kind == 'paste':
                data['text'] = self.get_field('text')
                data['replace_existing'] = self.replace_var.get()
            elif step.kind in READ_KINDS:
                data.update(keyword=self.get_field('keyword').strip() if step.kind == 'read_phone' else '',
                            timeout=float(self.get_field('timeout')),
                            retry_from=self.retry_ids.get(self.retry_menu.get(), ''))
                if data.get('source', 'screen') != 'ema_text':
                    data.update(region=[int(x.strip()) for x in self.get_field('region').replace('，', ',').split(',')],
                                confidence=float(self.get_field('confidence')))
                if step.kind == 'read':
                    data['use_first'] = self.first_read_var.get()
            step.data = data
            step.wait = wait
            step.title = self.get_field('title').strip()
        except (TypeError, ValueError) as error:
            raise ValueError('设置格式错误，请检查坐标、区域和等待秒数：' + str(error)) from error
        if before != asdict(step):
            self.dirty = True

    def apply_editor(self):
        try:
            self.commit_editor()
            self.refresh_list()
            self.build_editor()
            self.log('当前设置已应用；保存后可在下次打开')
        except ValueError as error:
            messagebox.showerror('设置有误', str(error), parent=self)

    def refresh_list(self):
        self.refreshing = True
        self.tree.delete(*self.tree.get_children())
        for i, step in enumerate(self.flow.steps):
            summary = step.title
            if not summary:
                if step.kind == 'click':
                    summary = f"({step.data.get('x', 0)}, {step.data.get('y', 0)})"
                elif step.kind == 'paste':
                    summary = step.data.get('text', '').replace('\n', ' ')[:28]
                elif step.kind in READ_KINDS:
                    summary = step.data.get('keyword', '')
                elif step.kind == 'hotkey':
                    summary = '+'.join(step.data.get('keys', []))
                elif step.kind == 'launch':
                    summary = Path(step.data.get('path', '')).name
            self.tree.insert('', 'end', iid=step.id, values=(i+1, KINDS[step.kind], summary, f'{step.wait:g}s'))
        if self.selected and self.tree.exists(self.selected):
            self.tree.selection_set(self.selected)
            self.tree.see(self.selected)
        self.refreshing = False

    def on_select(self, event=None):
        if self.refreshing:
            return
        choice = self.tree.selection()
        if not choice or choice[0] == self.selected:
            return
        try:
            self.commit_editor()
        except ValueError as error:
            self.refresh_list()
            messagebox.showerror('设置有误', str(error), parent=self)
            return
        self.selected = choice[0]
        self.build_editor()

    def add_selected(self):
        kind = next(k for k, label in KINDS.items() if label == self.kind_menu.get())
        try:
            self.add_step(kind)
        except ValueError as error:
            messagebox.showerror('设置有误', str(error), parent=self)

    def add_step(self, kind):
        if self.busy():
            return
        self.commit_editor()
        defaults = {'click': {'x': 0, 'y': 0, 'button': 'left', 'count': 1},
                    'scroll': {'x': 0, 'y': 0, 'amount': -3}, 'launch': {'path': ''},
                    'hotkey': {'keys': ['ctrl', 'r']}, 'paste': {'text': ''},
                    'read': {'keyword': '', 'region': [0, 0, 0, 0], 'timeout': 60,
                             'confidence': 0, 'retry_from': self.selected or '', 'use_first': True},
                    'read_phone': {'keyword': '', 'region': [0, 0, 0, 0], 'timeout': 60,
                                   'confidence': 0, 'retry_from': self.selected or ''}}
        step = Step(kind, defaults.get(kind, {}), wait=1 if kind == 'wait' else 0.5)
        # New steps append; order controls remain explicit and predictable.
        self.flow.steps.append(step)
        self.selected = step.id
        self.dirty = True
        self.refresh_list()
        self.build_editor()

    def duplicate_step(self):
        if self.busy() or self.current() is None:
            return
        self.commit_editor()
        source = self.current()
        step = copy.deepcopy(source)
        step.id = uuid.uuid4().hex
        self.flow.steps.insert(self.flow.steps.index(source)+1, step)
        self.selected = step.id
        self.dirty = True
        self.refresh_list()
        self.build_editor()

    def move_step(self, direction):
        if self.busy() or self.current() is None:
            return
        try:
            self.commit_editor()
            index = self.flow.steps.index(self.current())
            target = index + direction
            if 0 <= target < len(self.flow.steps):
                self.flow.steps[index], self.flow.steps[target] = self.flow.steps[target], self.flow.steps[index]
                self.dirty = True
                self.refresh_list()
                self.build_editor()
        except ValueError as error:
            messagebox.showerror('设置有误', str(error), parent=self)

    def delete_step(self):
        if self.busy() or self.current() is None:
            return
        step = self.current()
        if any(s.kind in READ_KINDS and s.data.get('retry_from') == step.id for s in self.flow.steps):
            if not messagebox.askyesno('删除重试起点', '这个步骤被用作重试起点。删除后需要重新选择起点，继续删除？', parent=self):
                return
        index = self.flow.steps.index(step)
        self.flow.steps.remove(step)
        self.selected = self.flow.steps[min(index, len(self.flow.steps)-1)].id if self.flow.steps else None
        self.dirty = True
        self.refresh_list()
        self.build_editor()

    def confirm_discard(self):
        try:
            self.commit_editor()
        except ValueError:
            self.dirty = True
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel('保存流程', '当前流程有未保存的修改。是否先保存？', parent=self)
        if answer is None:
            return False
        return self.save_flow() if answer else True

    def new_flow(self):
        if self.busy() or not self.confirm_discard():
            return
        self.flow = Workflow('我的流程')
        self.name_var.set(self.flow.name)
        self.repeat_var.set(str(self.flow.repetitions))
        self.path = None
        self.selected = None
        self.dirty = False
        self.fields = {}
        self.refresh_list()
        self.build_editor()

    def open_flow(self):
        if self.busy() or not self.confirm_discard():
            return
        file = filedialog.askopenfilename(parent=self, title='打开流程', filetypes=[('流程文件', '*.json')],
                                          initialdir=str(app_folder() / 'flows'))
        if not file:
            return
        try:
            self.load_flow(file)
        except (OSError, ValueError) as error:
            messagebox.showerror('无法打开', str(error), parent=self)

    def load_flow(self, file, relax_read=False):
        flow = Workflow.load(file)
        changed = False
        for step in flow.steps:
            if step.kind == 'read' and step.data.get('keyword'):
                step.data['keyword'] = ''
                changed = True
            if relax_read and step.kind in READ_KINDS and step.data.get('confidence') != 0:
                step.data['confidence'] = 0
                changed = True
        self.flow = flow
        self.path = Path(file)
        self.name_var.set(flow.name)
        self.repeat_var.set(str(flow.repetitions))
        self.selected = flow.steps[0].id if flow.steps else None
        self.fields = {}
        self.dirty = changed
        self.refresh_list()
        self.build_editor()
        self.title('屏幕流程助手 · ' + flow.name + ' · v1.7')
        self.log('已打开流程：' + self.path.name)
        if changed:
            self.log('读取选项已调整；当前修改尚未写回文件，请验证后保存')

    def save_flow(self):
        if self.busy():
            return False
        try:
            self.commit_editor()
            folder = app_folder() / 'flows'
            folder.mkdir(exist_ok=True)
            file = filedialog.asksaveasfilename(parent=self, title='保存流程', defaultextension='.json',
                                                filetypes=[('流程文件', '*.json')], initialdir=str(folder),
                                                initialfile=self.path.name if self.path else '我的流程.json')
            if not file:
                return False
            self.flow.save(file)
            self.path = Path(file)
            self.dirty = False
            self.log('已保存完整流程：' + self.path.name)
            return True
        except (OSError, ValueError) as error:
            messagebox.showerror('无法保存', str(error), parent=self)
            return False

    def choose_exe(self):
        if self.busy():
            return
        file = filedialog.askopenfilename(parent=self, title='选择软件', filetypes=[('Windows 软件', '*.exe')])
        if file:
            self.put_field('path', file)

    def open_demo(self):
        command = [sys.executable, '--demo'] if getattr(sys, 'frozen', False) else [sys.executable, str(app_folder() / 'main.py'), '--demo']
        subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)

    def insert_code(self):
        if not self.busy() and 'text' in self.fields:
            self.fields['text'].insert('insert', '{{code}}')

    def insert_phone(self):
        if not self.busy() and 'text' in self.fields:
            self.fields['text'].insert('insert', '{{phone}}')

    def insert_praise(self):
        if not self.busy() and 'text' in self.fields:
            self.fields['text'].insert('insert', '{{praise}}')

    def change_read_source(self, label):
        if self.busy() or not self.current() or self.current().kind != 'read':
            return
        try:
            self.commit_editor()
            self.current().data['source'] = 'ema_text' if label == 'ema 短信框文字' else 'screen'
            self.dirty = True
            self.build_editor()
        except ValueError as error:
            self.build_editor()
            messagebox.showerror('设置有误', str(error), parent=self)

    def pick_point(self):
        if self.busy() or not self.current() or self.current().kind not in ('click', 'scroll'):
            return
        self.point_pending = self.selected
        self.status_var.set('等待 F6 取点')
        self.log('将鼠标移到目标位置，按 F6 记录；按 F10 取消取点')
        self.iconify()

    def picked_point(self):
        if self.point_pending and self.selected == self.point_pending:
            x, y = self.desktop.mouse.position
            self.put_field('x', int(x))
            self.put_field('y', int(y))
            self.point_pending = None
            self.deiconify()
            self.lift()
            self.status_var.set('就绪')
            self.apply_editor()

    def pick_region(self):
        if self.busy() or not self.current() or self.current().kind not in READ_KINDS:
            return
        self.withdraw()
        self.after(200, self.region_overlay)

    def region_overlay(self):
        left, top, width, height = screen_bounds()
        overlay = tk.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.geometry(f'{width}x{height}+0+0')
        overlay.attributes('-topmost', True)
        overlay.attributes('-alpha', 0.35)
        canvas = tk.Canvas(overlay, background='#061E3C', highlightthickness=0, cursor='crosshair')
        canvas.pack(fill='both', expand=True)
        canvas.create_text(width//2, 70, text='拖动鼠标框选消息区域 · 松开完成 · Esc 取消',
                           fill='white', font=('Microsoft YaHei UI', 24, 'bold'))
        overlay.update()
        handle = ctypes.windll.user32.GetParent(overlay.winfo_id())
        ctypes.windll.user32.SetWindowPos(handle, -1, left, top, width, height, 0x0040)
        start = []
        rectangle = [None]

        def done(region=None):
            overlay.destroy()
            self.deiconify()
            self.lift()
            if region:
                self.put_field('region', ', '.join(map(str, region)))
                self.apply_editor()

        def press(event):
            start[:] = [event.x, event.y]
            if rectangle[0]:
                canvas.delete(rectangle[0])
            rectangle[0] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#FFFFFF', width=3)

        def move(event):
            if start:
                canvas.coords(rectangle[0], *start, event.x, event.y)

        def release(event):
            if not start:
                return
            x1, x2 = sorted((start[0], event.x))
            y1, y2 = sorted((start[1], event.y))
            if x2-x1 >= 10 and y2-y1 >= 10:
                done([left+x1, top+y1, left+x2, top+y2])
            else:
                done()

        canvas.bind('<ButtonPress-1>', press)
        canvas.bind('<B1-Motion>', move)
        canvas.bind('<ButtonRelease-1>', release)
        overlay.bind('<Escape>', lambda event: done())
        overlay.focus_force()

    def preview_region(self):
        if self.busy():
            return
        try:
            self.commit_editor()
            step = self.current()
            if step is None or step.kind not in READ_KINDS:
                raise ValueError('请先选择读取步骤')
            direct_text = step.kind == 'read' and step.data.get('source') == 'ema_text'
            if not direct_text and (len(step.data['region']) != 4 or step.data['region'][2] <= step.data['region'][0] or step.data['region'][3] <= step.data['region'][1]):
                raise ValueError('请先框选有效识别区域')
            data = copy.deepcopy(step.data)
            digits, label, _ = READ_KINDS[step.kind]
            phone_mode = step.kind == 'read_phone'
        except ValueError as error:
            messagebox.showerror('无法试读', str(error), parent=self)
            return
        self.preview_busy = True
        self.set_controls()
        self.status_var.set('试读中')
        if not direct_text:
            self.withdraw()

        def work():
            try:
                text = self.desktop.read(data)
                keyword = data.get('keyword', '') if phone_mode else ''
                code = extract_code(text, keyword, digits, True)
                self.events.put({'type': 'preview', 'text': text, 'code': code, 'label': label})
            except Exception as error:
                self.events.put({'type': 'preview', 'error': str(error)})

        self.after(250, lambda: threading.Thread(target=work, daemon=True).start())

    def set_controls(self):
        disabled = self.busy()
        for button in self.edit_buttons:
            button.configure(state='disabled' if disabled else 'normal')
        self.name_entry.configure(state='disabled' if disabled else 'normal')
        self.repeat_entry.configure(state='disabled' if disabled else 'normal')
        self.kind_menu.configure(state='disabled' if disabled else 'normal')
        self.start_button.configure(state='disabled' if disabled else 'normal')
        if disabled:
            self.disable_editor()

    def start_run(self):
        if self.busy():
            return
        try:
            self.commit_editor()
            self.flow.validate()
            self.desktop.validate(self.flow)
        except ValueError as error:
            messagebox.showerror('流程需要调整', str(error), parent=self)
            return
        self.code_var.set('本次新数据：尚未获取')
        self.ocr_var.set('验证码默认首次有效识别直接使用；手机号首次建立基准。')
        self.runner = Runner(copy.deepcopy(self.flow), self.desktop, self.events.put)
        self.trial_step_id = None
        self.worker = threading.Thread(target=self.runner.run, daemon=True)
        self.worker.start()
        self.set_controls()
        self.iconify()

    def toggle_pause(self):
        if self.runner and self.worker and self.worker.is_alive():
            if self.runner.state == 'paused':
                # The editor is brought forward on pause; hide it before any
                # coordinate action resumes against the underlying windows.
                self.iconify()
                self.after(250, self.runner.resume)
            else:
                self.runner.pause()

    def stop_run(self):
        if self.point_pending:
            self.point_pending = None
            self.deiconify()
            self.status_var.set('就绪')
        if self.record_pending:
            self.record_pending = False
            self.record_generation += 1
            self.scroll_capture_id = None
            self.deiconify()
            self.status_var.set('就绪')
            self.set_controls()
            self.build_editor()
        if self.recorder.active:
            if self.scroll_capture_id:
                self.recorder.finish()
                self.scroll_capture_id = None
                self.deiconify()
                self.status_var.set('就绪')
                self.set_controls()
                self.build_editor()
                self.log('已取消滚动录入，保留原设置')
            else:
                self.finish_recording(self.recorder.finish())
        if self.runner:
            self.runner.stop()

    def toggle_record(self):
        if self.recorder.active:
            self.finish_recording(self.recorder.finish())
            return
        if self.busy():
            return
        try:
            self.commit_editor()
        except ValueError as error:
            messagebox.showerror('设置有误', str(error), parent=self)
            return
        self.record_pending = True
        self.record_generation += 1
        generation = self.record_generation
        self.status_var.set('2 秒后录制')
        self.set_controls()
        self.log('2 秒后开始记录点击、滚动和按键；F8 结束后追加到流程')
        self.iconify()

        def start():
            if self.record_pending and generation == self.record_generation:
                self.record_pending = False
                self.recorder.start()
                self.status_var.set('录制中')
        self.after(2000, start)

    def capture_scroll(self):
        if self.busy() or not self.current() or self.current().kind != 'scroll':
            return
        try:
            self.commit_editor()
        except ValueError as error:
            messagebox.showerror('设置有误', str(error), parent=self)
            return
        self.scroll_capture_id = self.selected
        self.record_pending = True
        self.record_generation += 1
        generation = self.record_generation
        self.status_var.set('2 秒后录入')
        self.log('2 秒后录入滚动；亲自滚到满意的位置，按 F8 完成，F10 取消。只记录滚动动作')
        self.set_controls()
        self.iconify()

        def start():
            if self.record_pending and generation == self.record_generation:
                self.record_pending = False
                self.recorder.start(kinds={'scroll'})
                self.status_var.set('滚动录入中')
        self.after(2000, start)

    def preview_scroll(self):
        if self.busy() or not self.current() or self.current().kind != 'scroll':
            return
        try:
            self.commit_editor()
            step = copy.deepcopy(self.current())
            workflow = Workflow('单步试滚', [step], start_delay=3)
            workflow.validate()
        except ValueError as error:
            messagebox.showerror('无法试滚', str(error), parent=self)
            return
        self.trial_step_id = self.selected
        self.log('只试滚当前步骤。请将目标窗口放在前台，并恢复到校准时的页面起点')
        self.runner = Runner(workflow, self.desktop, self.events.put)
        self.worker = threading.Thread(target=self.runner.run, daemon=True)
        self.worker.start()
        self.set_controls()
        self.iconify()

    def finish_recording(self, steps):
        if self.scroll_capture_id:
            sid = self.scroll_capture_id
            self.scroll_capture_id = None
            self.deiconify()
            self.lift()
            self.status_var.set('就绪')
            try:
                data = recorded_scroll_data(steps)
                step = next(s for s in self.flow.steps if s.id == sid)
                step.data.update(data)
                self.selected = sid
                self.dirty = True
                self.log(f"已录入 {len(data['scroll_events'])} 个滚动动作，总刻度 {data['amount']}；位置与节奏已保存到当前步骤")
            except (ValueError, StopIteration) as error:
                self.log('录入未应用：' + str(error))
            self.set_controls()
            self.refresh_list()
            self.build_editor()
            return
        self.flow.steps.extend(steps)
        self.selected = steps[0].id if steps else self.selected
        self.dirty = bool(steps) or self.dirty
        self.deiconify()
        self.lift()
        self.status_var.set('就绪')
        self.set_controls()
        self.refresh_list()
        self.build_editor()
        self.log(f'录制结束，追加 {len(steps)} 步；可以编辑每一步的等待时间')

    def process_events(self):
        if self.closed:
            return
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event['type']
            if kind == 'log':
                self.log(event['message'])
            elif kind == 'hotkey':
                {'f6': self.picked_point, 'f8': self.toggle_record, 'f9': self.toggle_pause, 'f10': self.stop_run}[event['key']]()
            elif kind == 'recorded':
                self.finish_recording(event['steps'])
            elif kind == 'state':
                states = {'starting': '准备运行', 'running': '运行中', 'paused': '已暂停',
                          'completed': '已完成', 'stopped': '已停止', 'failed': '执行失败'}
                self.status_var.set(states.get(event['state'], event['state']))
                self.pause_button.configure(text='继续 F9' if event['state'] == 'paused' else '暂停 F9')
                if event['state'] in ('paused', 'completed', 'stopped', 'failed'):
                    self.deiconify()
                    self.lift()
                if event['state'] in ('completed', 'stopped', 'failed'):
                    self.after(100, self.end_run_ui)
            elif kind == 'step':
                if event['index'] < len(self.flow.steps):
                    sid = self.trial_step_id or self.flow.steps[event['index']].id
                    self.tree.selection_set(sid)
                    self.tree.see(sid)
            elif kind == 'ocr':
                self.ocr_var.set(event['text'][:500] or '区域里没有识别出文字')
            elif kind == 'code':
                self.code_var.set('新' + event.get('label', '六位数字') + '：' + event['code'])
            elif kind == 'preview':
                self.preview_busy = False
                self.deiconify()
                self.lift()
                self.status_var.set('就绪')
                self.set_controls()
                self.build_editor()
                if 'error' in event:
                    self.log('试读失败：' + event['error'])
                    messagebox.showerror('试读失败', event['error'], parent=self)
                else:
                    self.ocr_var.set(event['text'][:500] or '未识别出文字')
                    self.log('试读完成：' + ('提取到 ' + event['code'] if event['code'] else '未找到匹配的' + event.get('label', '六位数字')) + '；未建立运行基准')
        self.timer = self.after(50, self.process_events)

    def end_run_ui(self):
        if self.closed:
            return
        if self.worker and self.worker.is_alive():
            self.after(100, self.end_run_ui)
            return
        self.set_controls()
        self.trial_step_id = None
        self.build_editor()

    def close(self, force=False):
        if not force:
            if self.busy() and not messagebox.askyesno('退出', '当前正在执行、录制或试读。停止并退出？', parent=self):
                return
            self.stop_run()
            if not self.confirm_discard():
                return
        if self.runner:
            self.runner.stop()
        if self.service:
            self.service.stop()
        self.desktop.release_all()
        self.closed = True
        # CustomTkinter schedules widget/DPI updates. Cancel pending Tcl calls
        # before destroying their Python command bindings (including tests).
        for callback in self.tk.call('after', 'info'):
            try:
                # Cancel the timer only. Child widgets own their Tcl command
                # bindings and must remove them themselves during destroy.
                self.tk.call('after', 'cancel', callback)
            except tk.TclError:
                pass
        self.destroy()
