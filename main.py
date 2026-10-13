import json
import sys
import traceback
from pathlib import Path
from desktop import enable_dpi_awareness


def main():
    enable_dpi_awareness()
    if '--headless-test' in sys.argv:
        from selftest import run_headless_test
        output = Path(sys.argv[sys.argv.index('--headless-test') + 1])
        return run_headless_test(output)
    if '--self-test' in sys.argv:
        from selftest import run_selftest
        output = Path(sys.argv[sys.argv.index('--self-test') + 1])
        return run_selftest(output)
    if '--demo' in sys.argv:
        from demo import run_demo
        run_demo()
        return 0
    try:
        from ui import App
        app = App()
        if '--flow' in sys.argv:
            file = Path(sys.argv[sys.argv.index('--flow') + 1])
            app.load_flow(file, relax_read='--relax-reading' in sys.argv)
            app.after(100, app.focus_force)
        if '--ready-file' in sys.argv:
            ready_path = Path(sys.argv[sys.argv.index('--ready-file') + 1])
            def ready():
                ready_path.parent.mkdir(parents=True, exist_ok=True)
                ready_path.write_text(json.dumps({'flow': str(app.path) if app.path else None,
                                                  'name': app.flow.name, 'steps': len(app.flow.steps),
                                                  'dirty': app.dirty}, ensure_ascii=False), encoding='utf-8')
            app.after(250, ready)
        app.mainloop()
        return 0
    except Exception:
        folder = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        details = traceback.format_exc()
        try:
            (folder / '启动错误.txt').write_text(details, encoding='utf-8')
        except OSError:
            pass
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('启动失败', '启动错误已保存到程序旁的“启动错误.txt”。\n\n' + details[-700:])
        root.destroy()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
