"""WinForms UI 定时器：把全局按键脉冲推给小狗（失焦也有效，禁止同步 Invoke）"""

from __future__ import annotations

from backend import key_state

# pythonnet / WinForms 会回收未引用的 Timer 和委托，必须挂在模块上
_keepalive: list = []


def start(window) -> bool:
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        import System.Windows.Forms as WinForms
        from System import Func, Type
        from webview.platforms.winforms import BrowserView
    except Exception as exc:
        print(f"[desk-os] dog pusher import failed: {exc}", flush=True)
        return False

    form = BrowserView.instances.get(window.uid)
    if form is None:
        print("[desk-os] dog pusher: browser form not ready", flush=True)
        return False

    state = {"last": 0, "timer": None, "on_tick": None, "logged": False}

    def _setup_timer():
        timer = WinForms.Timer()
        timer.Interval = 30

        def on_tick(_sender, _args):
            pulse = key_state.read()
            if pulse == state["last"]:
                return
            wv = getattr(form, "webview", None)
            if wv is None:
                return
            core = wv.CoreWebView2
            if core is None:
                return
            payload = '{"type":"key-pulse","pulse":%d}' % pulse
            try:
                core.PostWebMessageAsJson(payload)
                state["last"] = pulse
            except Exception:
                try:
                    core.ExecuteScriptAsync(
                        f"window.PixelDog&&window.PixelDog.onPulse({pulse});"
                    )
                    state["last"] = pulse
                except Exception:
                    return
            if not state["logged"]:
                state["logged"] = True
                print(f"[desk-os] dog pusher delivered pulse {pulse}", flush=True)

        timer.Tick += on_tick
        timer.Start()
        state["timer"] = timer
        state["on_tick"] = on_tick
        form._desk_os_dog_state = state
        print("[desk-os] dog pusher started", flush=True)

    cb = Func[Type](_setup_timer)
    _keepalive.append(state)
    _keepalive.append(_setup_timer)
    _keepalive.append(cb)
    form.BeginInvoke(cb)
    return True
