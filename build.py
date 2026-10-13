"""Run with the project's Python environment; emits a portable directory."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir',
           '--name', '屏幕流程助手', '--collect-data', 'customtkinter',
           '--collect-data', 'rapidocr_onnxruntime', '--collect-all', 'onnxruntime',
           '--hidden-import', 'pynput.keyboard._win32', '--hidden-import', 'pynput.mouse._win32',
           '--collect-all', 'uiautomation', '--collect-submodules', 'comtypes.gen',
           '--distpath', str(root / 'dist'), '--workpath', str(root / 'build'),
           '--specpath', str(root / 'build'), str(root / 'main.py')]
raise SystemExit(subprocess.call(command, cwd=root))
