# Screen Auto Clicker · 屏幕连点器

Windows 本地桌面流程助手，最终版本 **v1.7**。手动编排、录制并编辑鼠标键盘动作，保存流程后重复执行。

## 功能

- 打开 EXE、坐标单击/双击、快捷键、输入文字、等待与滚动。
- 录制后编辑；实际滚到合适位置后记录滚动格数和节奏。
- 输入文字默认 Ctrl+A 后粘贴替换；取消“选中输入框原文字并替换”可普通粘贴。
- 运行次数 1–99999，随 JSON 流程保存；每次从头开始执行，日志显示进度。
- 固定区域离线 OCR 读取六位验证码或十一位手机号，分别使用 `{{code}}`、`{{phone}}`。
- 验证码默认首次有效读取即使用，优先提取“验证码”后的完整六位数字，保留开头的 0；没读到时等待 5 秒再从指定起点重试。
- 可直接读取 ema 的短信框文字，避开小字体 OCR；ema 需保持“操作中心”页。
- 最长等待秒数覆盖整个重试过程，超时暂停；设置为 0 表示不限时。

| 快捷键 | 操作 |
| --- | --- |
| F6 | 鼠标取点 |
| F8 | 开始/结束录制或结束滚动录入 |
| F9 | 暂停/继续 |
| F10 | 停止 |

## 从源码运行

需要 Windows 10/11 x64、Python 3.12。坐标取决于窗口位置、分辨率和缩放；改变后请重新取点。输入前先安排点击目标输入框。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

点击“打开”加载自己的 JSON 流程，或手动添加步骤。开始前将目标应用准备好；程序会按设定的坐标执行操作。

## 检查与打包

以下检查不打开窗口、不发送真实鼠标键盘输入：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_core tests.test_runner tests.test_desktop tests.test_window_text tests.test_quick_features
.\.venv\Scripts\python.exe main.py --headless-test qa
.\.venv\Scripts\python.exe build.py
```

`dist/屏幕流程助手/` 是完整便携目录，需要一起保留 `_internal`。`tests.test_ui`、`tests.test_integration` 和 `--self-test` 会打开测试窗口或操作桌面，请只在空闲时手动运行。

## 源码结构

- `core.py`：流程数据、保存恢复、数字提取与读取基准。
- `runner.py`：执行、次数、暂停、停止和超时。
- `desktop.py`：Windows 输入、剪贴板、截图 OCR、录制与滚动记录。
- `ui.py`：中文流程编辑器。
- `window_text.py`：只读 ema 短信控件适配器。
- `demo.py`：练习窗口；`selftest.py` 和 `tests/`：验证。
- `build.py`：PyInstaller 构建；`requirements.txt`：固定依赖版本。

## 数据与许可

OCR 在本地运行。录制仅在主动启动后记录；账号、消息和个人流程不包含在仓库中。输入使用系统剪贴板，完成后会保留最后输入的文本。六位数字和手机号样例均使用测试数据。

项目自有代码采用 [MIT License](LICENSE)。依赖及 OCR 模型遵循各自许可证，见 [第三方许可](THIRD_PARTY_LICENSES/)。该目录的许可证不会被项目的 MIT 许可证替代。
