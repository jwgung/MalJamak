"""자막 창: 항상 위에 떠 있는 반투명 창. 별도 프로세스로 돌며 서버에서 자막 줄을 받는다.

트레이(pystray)와 tkinter 가 macOS 에서 둘 다 메인 스레드를 요구하므로 프로세스를 나눈다.
드래그로 옮길 수 있고, 더블클릭하면 원어 표시를 켜고 끈다. 마우스 휠로 지난 자막을 다시 볼 수 있다.
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

    # history: 받은 자막 줄을 id 순서로 모두 기억한다 (서버는 최근 몇 줄만 보내므로). scroll: 위로 올려 본 줄 수.
    state = {"show_src": True, "font_size": 26, "live": None, "history": {}, "scroll": 0}
    frame = tk.Frame(root, bg="black", padx=16, pady=10)
    frame.pack(fill="both", expand=True)

    # 줄마다 원문·번역 라벨을 한 번만 만들고 글자만 바꾼다 (깜빡임 방지).
    rows = []
    for _ in range(ROWS):
        src = tk.Label(frame, fg="#9a9a9a", bg="black", wraplength=width - 32, justify="center")
        ko = tk.Label(frame, bg="black", wraplength=width - 32, justify="center")
        rows.append((src, ko))

    hint = tk.Label(frame, fg="#facc15", bg="black", font=("", 11))

    def render() -> None:
        history = list(state["history"].values())
        scroll = min(state["scroll"], max(0, len(history) - 1))
        state["scroll"] = scroll
        if scroll:
            # 지난 자막 보는 중: 진행 중인 줄은 숨기고 과거 줄을 보여준다.
            items = history[max(0, len(history) - scroll - ROWS):len(history) - scroll]
        else:
            items = list(history)
            if state["live"]:
                items.append({**state["live"], "live": True})
        if not items:
            items = [{"src": "", "ko": "자막 대기 중…", "live": True}]
        items = items[-ROWS:]
        hint.pack_forget()
        if scroll:
            hint.config(text=f"▲ 지난 자막 보는 중 ({scroll}줄 전) — 휠을 내리면 최신으로")
            hint.pack(fill="x")
        size = state["font_size"]
        for i, (src, ko) in enumerate(rows):
            src.pack_forget()
            ko.pack_forget()
            if i >= len(items):
                continue
            item = items[i]
            # 번역이 없으면 원문과 자막이 같으니 한 번만 보여준다.
            if state["show_src"] and item.get("src") and item.get("src") != item.get("ko"):
                src.config(text=item["src"], font=("", max(size // 2, 11)))
                src.pack(fill="x")
            ko.config(text=item.get("ko") or item.get("src") or "…", font=("", size, "bold"),
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
                for line in msg.get("lines") or []:
                    if "id" in line:
                        state["history"][line["id"]] = line
                state["live"] = msg.get("live")
                # 위로 올려 보는 중이면 화면을 흔들지 않는다 (새 줄은 기록에만 쌓인다).
                changed = changed or not state["scroll"]
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

    def on_wheel(e):
        up = getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4
        state["scroll"] = max(0, state["scroll"] + (1 if up else -1))
        render()

    root.bind_all("<ButtonPress-1>", on_press)
    root.bind_all("<B1-Motion>", on_drag)
    root.bind_all("<Double-Button-1>", on_double)
    root.bind_all("<MouseWheel>", on_wheel)  # Windows·macOS
    root.bind_all("<Button-4>", on_wheel)  # Linux 휠 위
    root.bind_all("<Button-5>", on_wheel)  # Linux 휠 아래

    root.update_idletasks()
    _no_activate(root)
    render()
    poll()
    root.mainloop()
