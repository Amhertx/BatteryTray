"""崩溃与生命周期日志。

打包成 windowed exe 后没有控制台，任何 Python 异常、线程异常、hidapi 的原生崩溃
都会让进程「无声消失」。这里把三条通道都落到 %APPDATA%\\BatteryTray\\error.log：

- sys.excepthook    主线程未捕获异常
- threading.excepthook  后台线程未捕获异常（采集线程、托盘线程）
- faulthandler      原生层段错误（hidapi 之类）也能留下 Python 栈

另外写 start / exit 标记，能直接看出某次运行是正常退出还是被打断。
"""
from __future__ import annotations

import atexit
import faulthandler
import os
import sys
import threading
import time
import traceback

from .config import APP_DIR

LOG = APP_DIR / "error.log"
MAX_BYTES = 256 * 1024
_fh = None


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _trim() -> None:
    try:
        if LOG.exists() and LOG.stat().st_size > MAX_BYTES:
            data = LOG.read_text("utf-8", "replace").splitlines()[-800:]
            LOG.write_text("\n".join(data) + "\n", encoding="utf-8")
    except OSError:
        pass


def note(msg: str) -> None:
    """写一行生命周期标记（不写 traceback）。"""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _trim()
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{_stamp()} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


def install() -> None:
    global _fh
    APP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        _fh = open(LOG, "a", encoding="utf-8")  # 常驻句柄，faulthandler 需要
        faulthandler.enable(file=_fh, all_threads=True)
    except OSError:
        pass

    def _hook(exc_type, exc, tb):
        note("CRASH " + "".join(traceback.format_exception(exc_type, exc, tb)).strip())

    sys.excepthook = _hook

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        note(f"THREAD-CRASH {args.thread.name if args.thread else '?'} "
             + "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                  args.exc_traceback)).strip())

    threading.excepthook = _thread_hook
    atexit.register(note, "exit (atexit)")
    note(f"start frozen={getattr(sys, 'frozen', False)} py={sys.version.split()[0]}")
