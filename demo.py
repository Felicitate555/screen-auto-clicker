"""An optional isolated practice window with synthetic messages."""
import tkinter as tk
from tkinter import ttk


def run_demo():
    root = tk.Tk()
    root.title('练习窗口 · 所有数字都是虚构示例')
    root.geometry('850x460')
    root.configure(bg='#F4F6F9')
    tk.Label(root, text='先在这个窗口练习流程', font=('Microsoft YaHei UI', 20, 'bold'),
             bg='#F4F6F9', fg='#172B46').pack(anchor='w', padx=25, pady=(22, 8))
    tk.Label(root, text='用“刷新消息”作为重试起点，框选下面的白色消息区域。\n'
                        '新数字出现后，点击输入框并输入 {{code}}。',
             font=('Microsoft YaHei UI', 12), bg='#F4F6F9', justify='left', fg='#526178').pack(anchor='w', padx=25)
    values = ['661886', '661886', '001234', '001234', '552211', '002345']
    index = [0]
    message = tk.StringVar(value='【学生账号】验证码为：661886。')
    tk.Label(root, textvariable=message, font=('Microsoft YaHei UI', 23), bg='white',
             fg='#172B46', anchor='w', padx=20, pady=20).pack(fill='x', padx=25, pady=18)

    def refresh():
        index[0] = (index[0] + 1) % len(values)
        message.set('【学生账号】验证码为：' + values[index[0]] + '。')

    tk.Button(root, text='刷新消息（模拟重复消息和新消息）', command=refresh,
              font=('Microsoft YaHei UI', 12), bg='#E5EBF4', fg='#172B46', relief='flat',
              padx=14, pady=8).pack(anchor='w', padx=25)
    tk.Label(root, text='获取结果输入到这里：', font=('Microsoft YaHei UI', 12),
             bg='#F4F6F9', fg='#172B46').pack(anchor='w', padx=25, pady=(20, 6))
    tk.Entry(root, font=('Microsoft YaHei UI', 18), relief='solid', borderwidth=1).pack(fill='x', padx=25, ipady=6)
    tk.Label(root, text='练习窗口不会打开网站、发送消息或执行点赞。',
             font=('Microsoft YaHei UI', 11), bg='#F4F6F9', fg='#526178').pack(anchor='w', padx=25, pady=14)
    root.mainloop()
