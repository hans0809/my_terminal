"""
Desk OS — 个人桌面终端
Phase 1: 墨水屏默认主页
"""

import os
import socket
import sys
import threading
import time
from pathlib import Path

# WebView2 失焦时不要把渲染进程/定时器打入休眠，否则小狗收不到推送
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--disable-background-timer-throttling "
    "--disable-renderer-backgrounding "
    "--disable-backgrounding-occluded-windows "
    "--disable-features=CalculateNativeWinOcclusion"
)

import uvicorn
import webview

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api import app  # noqa: E402
from backend.display_utils import (  # noqa: E402
    TARGET_MONITOR,
    get_window_monitor_index,
    move_window_to_monitor,
)
from backend import key_state  # noqa: E402
from backend.cursor_usage import start as start_cursor_usage  # noqa: E402
from backend.dog_pusher import start as start_dog_pusher  # noqa: E402
from backend.flow import start as start_flow  # noqa: E402
from backend.keyboard_hook import start_global_keyboard_listener  # noqa: E402


def _patch_webview2_args() -> None:
    """在 WebView2 创建环境前追加反节流参数（CreationProperties 会覆盖环境变量）。"""
    extra = (
        "--disable-background-timer-throttling "
        "--disable-renderer-backgrounding "
        "--disable-backgrounding-occluded-windows"
    )
    try:
        from webview.platforms import edgechromium as ec
    except Exception:
        return

    orig = ec.EdgeChrome.__init__

    def wrapped(self, form, window, cache_dir):
        patched = False
        real_add = None
        try:
            real_add = form.Controls.Add

            def add(ctrl):
                try:
                    props = ctrl.CreationProperties
                    current = str(props.AdditionalBrowserArguments or "")
                    if "disable-background-timer-throttling" not in current:
                        props.AdditionalBrowserArguments = f"{current} {extra}".strip()
                        ctrl.CreationProperties = props
                except Exception:
                    pass
                return real_add(ctrl)

            form.Controls.Add = add
            patched = True
        except Exception:
            pass
        try:
            orig(self, form, window, cache_dir)
        finally:
            if patched and real_add is not None:
                try:
                    form.Controls.Add = real_add
                except Exception:
                    pass

    ec.EdgeChrome.__init__ = wrapped


_patch_webview2_args()

HOST = "127.0.0.1"
PORT = 8765

# 窗口模式下的固定尺寸（紧凑，适合副屏预览 / 调试）
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 720


def _find_free_port(start: int = PORT) -> int:
    """若默认端口被占用，自动寻找可用端口"""
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    return start


def start_server(port: int):
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def main():
    port = _find_free_port()
    url = f"http://{HOST}:{port}"

    server_thread = threading.Thread(
        target=start_server,
        args=(port,),
        daemon=True,
    )
    server_thread.start()
    start_cursor_usage()
    start_flow()

    # 等待服务就绪
    for _ in range(50):
        try:
            with socket.create_connection((HOST, port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)

    active_monitor = TARGET_MONITOR

    placed_on_target = False

    def _place_on_target_monitor(retry: int = 0):
        """窗口完全启动后再移到目标屏"""
        nonlocal placed_on_target
        if placed_on_target:
            return

        if move_window_to_monitor(window, TARGET_MONITOR, WINDOW_WIDTH, WINDOW_HEIGHT):
            # 确认窗口确实到了目标屏
            if get_window_monitor_index(window) == TARGET_MONITOR:
                placed_on_target = True
                return

        if retry < 15:
            delay = 0.05 if retry < 5 else 0.15
            threading.Timer(delay, lambda: _place_on_target_monitor(retry + 1)).start()

    window = webview.create_window(
        title="Desk OS",
        url=url,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        fullscreen=False,
        resizable=True,
        frameless=False,
        background_color="#121212",
    )

    def _apply_cursor():
        """WebView2 需绝对路径 URL 才可靠加载自定义光标"""
        cursor_css = f"""
        html, body, #view-dashboard, #view-dashboard * {{
            cursor: url('{url}/assets/cursor-cross.png?v=2') 16 16, crosshair !important;
        }}
        .crt__key,
        .app-tile,
        .crt__home,
        .task-new__input,
        .task-log__input,
        .task-detail__name,
        .task-beat__text,
        .task-beat__edit,
        .task-beat__drop,
        .task-row,
        .task-heading,
        .task-drop,
        .task-drop-ask button,
        .flow-tab,
        .flow-cat,
        .flow-row,
        .flow-feed,
        .flow-act,
        .flow-search__input,
        .flow-form__input,
        .flow-read__body {{
            cursor: url('{url}/assets/cursor-block.png?v=2') 16 16, text !important;
        }}
        """
        window.load_css(cursor_css)

    pusher_started = False

    def _try_start_pusher(retry: int = 0):
        nonlocal pusher_started
        if pusher_started:
            return
        if start_dog_pusher(window):
            pusher_started = True
        elif retry < 10:
            threading.Timer(0.3, lambda: _try_start_pusher(retry + 1)).start()

    def _on_loaded():
        _place_on_target_monitor()
        _apply_cursor()
        _try_start_pusher()

    window.events.shown += lambda: _place_on_target_monitor()
    window.events.loaded += _on_loaded

    is_fullscreen = False

    def _set_display_mode(mode: str):
        window.evaluate_js(f'document.body.dataset.mode = "{mode}";')

    def toggle_fullscreen():
        nonlocal is_fullscreen, active_monitor

        # 切换前记录当前所在显示器，避免跳回主屏
        active_monitor = get_window_monitor_index(window)

        if not is_fullscreen:
            # 进入全屏前先确保窗口在目标显示器上
            move_window_to_monitor(window, active_monitor, WINDOW_WIDTH, WINDOW_HEIGHT)

        window.toggle_fullscreen()
        is_fullscreen = not is_fullscreen

        if is_fullscreen:
            _set_display_mode("fullscreen")
        else:
            window.restore()
            window.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
            move_window_to_monitor(window, active_monitor, WINDOW_WIDTH, WINDOW_HEIGHT)
            _set_display_mode("windowed")

    window.expose(toggle_fullscreen)

    def get_key_pulse() -> int:
        return key_state.read()

    def consume_key_pulses() -> int:
        return key_state.consume()

    window.expose(get_key_pulse, consume_key_pulses)

    if sys.platform == "win32":
        start_global_keyboard_listener(key_state.bump, ignore_vk=frozenset({0x1B, 0x7A}))

    webview.start(debug=False)


if __name__ == "__main__":
    main()
