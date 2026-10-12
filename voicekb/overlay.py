"""자막 창: 항상 위에 떠 있는 반투명 창. 별도 프로세스로 돌며 서버에서 자막 줄을 받는다.

트레이(pystray)와 tkinter 가 macOS 에서 둘 다 메인 스레드를 요구하므로 프로세스를 나눈다.
드래그로 옮길 수 있고, 더블클릭하면 원어 표시를 켜고 끈다.
클릭해도 포커스를 가져가지 않는다 — 가져가면 다음 음성 입력이 자막 창에 붙여넣어진다.
"""

import asyncio
import json
import platform
import queue
import threading

ROWS = 3


def _receiver(port: int, inbox: queue.Queue) -> None:
    import aiohttp

    async def run():
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"http://localhost:{port}/ws?role=overlay") as ws:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                inbox.put(json.loads(msg.data))
            except Exception:  # 어떤 오류든 재연결한다 (스레드가 조용히 죽지 않게)
                pass
            await asyncio.sleep(1)

    asyncio.run(run())


def _parent_alive(pid: int | None) -> bool:
    if not pid:
        return True
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        return True


def _no_activate(root) -> None:
    """클릭해도 활성 창이 되지 않게 한다."""
    system = platform.system()
    if system == "Windows":
        import ctypes

        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
        hwnd = int(root.wm_frame(), 16)
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    elif system == "Linux":
        try:
            root.attributes("-type", "notification")
        except Exception:
            pass


def run_overlay(port: int, parent_pid: int | None = None) -> None:
    import tkinter as tk

    inbox: queue.Queue = queue.Queue()
    threading.Thread(target=_receiver, args=(port, inbox), daemon=True).start()

    root = tk.Tk()
    root.title("Voice Keyboard 자막")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.85)
    root.configure(bg="black")

    width = int(root.winfo_screenwidth() * 0.6)
    pos = {"x": (root.winfo_screenwidth() - width) // 2, "y": int(root.winfo_screenheight() * 0.78)}
    root.geometry(f"{width}x40+{pos['x']}+{pos['y']}")

    state = {"show_src": True, "font_size": 22, "data": {"lines": [], "live": None}}
    frame = tk.Frame(root, bg="black", padx=16, pady=10)
    frame.pack(fill="both", expand=True)

    # 줄마다 원문·번역 라벨을 한 번만 만들고 글자만 바꾼다 (깜빡임 방지).
    rows = []
    for _ in range(ROWS):
        src = tk.Label(frame, fg="#9a9a9a", bg="black", wraplength=width - 32, justify="center")
        ko = tk.Label(frame, bg="black", wraplength=width - 32, justify="center")
        rows.append((src, ko))

    def render() -> None:
        data = state["data"]
        items = list(data.get("lines") or [])
        if data.get("live"):
            items.append({**data["live"], "live": True})
        if not items:
            items = [{"src": "", "ko": "자막 대기 중…", "live": True}]
        items = items[-ROWS:]
        size = state["font_size"]
        for i, (src, ko) in enumerate(rows):
            src.pack_forget()
            ko.pack_forget()
            if i >= len(items):
                continue
            item = items[i]
            if state["show_src"] and item.get("src"):
                src.config(text=item["src"], font=("", max(size // 2, 11)))
                src.pack(fill="x")
            ko.config(text=item.get("ko") or "…", font=("", size, "bold"),
                      fg="#bbbbbb" if item.get("live") else "white")
            ko.pack(fill="x")
        root.update_idletasks()
        root.geometry(f"{width}x{frame.winfo_reqheight()}+{pos['x']}+{pos['y']}")

    def poll() -> None:
        if not _parent_alive(parent_pid):
            root.destroy()
            return
        changed = False
        while not inbox.empty():
            msg = inbox.get()
            if msg.get("type") == "captions":
                state["data"] = msg
                changed = True
            elif msg.get("type") == "style":
                state["font_size"] = int(msg.get("font_size", 22))
                root.attributes("-alpha", float(msg.get("opacity", 0.85)))
                changed = True
        if changed:
            render()
        root.after(50, poll)

    drag = {"x": 0, "y": 0}

    def on_press(e):
        drag["x"], drag["y"] = e.x_root - pos["x"], e.y_root - pos["y"]

    def on_drag(e):
        pos["x"], pos["y"] = e.x_root - drag["x"], e.y_root - drag["y"]
        root.geometry(f"+{pos['x']}+{pos['y']}")

    def on_double(_e):
        state["show_src"] = not state["show_src"]
        render()

    root.bind_all("<ButtonPress-1>", on_press)
    root.bind_all("<B1-Motion>", on_drag)
    root.bind_all("<Double-Button-1>", on_double)

    root.update_idletasks()
    _no_activate(root)
    render()
    poll()
    root.mainloop()
