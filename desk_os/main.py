"""
Desk OS 进程入口。

启动顺序：本地 API → 后台采集 → 副屏窗口。
新功能的接口挂到 backend.routes，窗口无关的后台任务挂到 backend.boot。
"""

import multiprocessing
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_WEBVIEW2_SETUP = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def _prepare_stdio() -> None:
    """窗口程序没有控制台时，把输出写到本机日志，避免 print 直接崩掉。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from backend.paths import DATA_DIR

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stream = open(DATA_DIR.parent / "desk_os.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _webview2_ready() -> bool:
    if sys.platform != "win32":
        return True
    import winreg

    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(env, "")
        if not root:
            continue
        folder = Path(root) / "Microsoft" / "EdgeWebView" / "Application"
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if (child / "msedgewebview2.exe").is_file():
                return True

    keys = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
    )
    for hive, path in keys:
        try:
            with winreg.OpenKey(hive, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if str(version).strip():
            return True
    return False


def _ensure_webview2() -> None:
    if not getattr(sys, "frozen", False) or _webview2_ready():
        return
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        None,
        "没有找到 WebView2 运行库，窗口开不起来。\n将打开微软的安装页面，装好后重新启动 Desk OS。",
        "Desk OS",
        0x30,
    )
    webbrowser.open(_WEBVIEW2_SETUP)
    raise SystemExit(1)


def _pack_check() -> int:
    """打包后自检：前端文件在包里，后端模块能导入。不打开窗口。"""
    try:
        from backend.paths import FRONTEND_DIR

        if not (FRONTEND_DIR / "index.html").is_file():
            print(f"missing frontend: {FRONTEND_DIR / 'index.html'}", flush=True)
            return 1
        import backend.boot  # noqa: F401
        import backend.routes  # noqa: F401
        import backend.shell  # noqa: F401
    except Exception:
        import traceback

        traceback.print_exc()
        return 1
    print("pack-check ok", flush=True)
    return 0


def main():
    _ensure_webview2()
    from backend.boot import start_workers
    from backend.shell import open_window, serve

    port = serve()
    start_workers()
    open_window(port)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _prepare_stdio()
    if "--pack-check" in sys.argv:
        raise SystemExit(_pack_check())
    main()
