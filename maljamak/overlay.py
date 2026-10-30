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


# 자막 창 색: 완전한 검정보다 살짝 띄운 어두운 회색이 다른 창 위에서 덜 무겁다.
BG = "#121418"
FG = "#ffffff"
FG_LIVE = "#b8bec9"  # 아직 말하는 중인 줄
FG_SRC = "#8a919e"  # 번역 원문
FG_HINT = "#fcc419"
KOREAN_FONTS = ("Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic")


def _pick_font(root) -> str:
    """설치된 한글 글꼴 중 먼저 찾은 것. 없으면 시스템 기본."""
    from tkinter import font as tkfont

    families = set(tkfont.families(root))
    return next((f for f in KOREAN_FONTS if f in families), "")


def run_overlay(port: int, parent_pid: int | None = None) -> None:
    import tkinter as tk

    inbox: queue.Queue = queue.Queue()
    threading.Thread(target=_receiver, args=(port, inbox), daemon=True).start()

    root = tk.Tk()
    root.title("말자막 자막")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.85)
    root.configure(bg=BG)
    family = _pick_font(root)

    width = int(root.winfo_screenwidth() * 0.6)
    pos = {"x": (root.winfo_screenwidth() - width) // 2, "y": int(root.winfo_screenheight() * 0.78)}
    root.geometry(f"{width}x40+{pos['x']}+{pos['y']}")

    # history: 받은 자막 줄을 id 순서로 모두 기억한다 (서버는 최근 몇 줄만 보내므로). scroll: 위로 올려 본 줄 수.
    state = {"show_src": True, "font_size": 26, "live": None, "history": {}, "scroll": 0}
    frame = tk.Frame(root, bg=BG, padx=24, pady=14)
    frame.pack(fill="both", expand=True)

    # 줄마다 원문·번역 라벨을 한 번만 만들고 글자만 바꾼다 (깜빡임 방지).
    rows = []
    for _ in range(ROWS):
        src = tk.Label(frame, fg=FG_SRC, bg=BG, wraplength=width - 48, justify="center")
        ko = tk.Label(frame, bg=BG, wraplength=width - 48, justify="center")
        rows.append((src, ko))

    hint = tk.Label(frame, fg=FG_HINT, bg=BG, font=(family, 11))
    # 마우스를 올렸을 때만 보이는 사용법 (평소엔 자막만)
    tip = tk.Label(frame, fg=FG_SRC, bg=BG, font=(family, 10),
                   text="드래그: 옮기기 · 휠: 지난 자막 · 더블클릭: 원문 표시")

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
        tip.pack_forget()
        if state.get("hover"):
            tip.pack(fill="x", pady=(0, 4))
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
                src.config(text=item["src"], font=(family, max(size // 2, 11)))
                src.pack(fill="x")
            ko.config(text=item.get("ko") or item.get("src") or "…", font=(family, size, "bold"),
                      fg=FG_LIVE if item.get("live") else FG)
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

    def on_hover(on: bool):
        state["hover"] = on
        render()

    def on_wheel(e):
        up = getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4
        state["scroll"] = max(0, state["scroll"] + (1 if up else -1))
        render()

    root.bind_all("<ButtonPress-1>", on_press)
    root.bind_all("<B1-Motion>", on_drag)
    root.bind_all("<Double-Button-1>", on_double)
    # 창 안의 글자 위를 지날 때마다 들어옴/나감이 반복되지 않게, 창 자체의 이벤트만 쓴다
    root.bind("<Enter>", lambda e: e.widget is root and on_hover(True))
    root.bind("<Leave>", lambda e: e.widget is root and on_hover(False))
    root.bind_all("<MouseWheel>", on_wheel)  # Windows·macOS
    root.bind_all("<Button-4>", on_wheel)  # Linux 휠 위
    root.bind_all("<Button-5>", on_wheel)  # Linux 휠 아래

    root.update_idletasks()
    _no_activate(root)
    render()
    poll()
    root.mainloop()
