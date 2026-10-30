"""포커스된 창에 텍스트 붙여넣기. 한글 IME 충돌을 피하려고 키 타이핑 대신 클립보드 + Ctrl/Cmd+V 를 쓴다."""

import os
import platform
import shutil
import subprocess
import threading
import time

SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"
IS_WAYLAND = SYSTEM == "Linux" and bool(os.environ.get("WAYLAND_DISPLAY"))

# 붙여넣기 단축키(Ctrl+V)를 누르는 외부 명령. pynput 은 Windows/macOS/X11 에서 쓴다.
PASTE_COMMANDS = {
    "xdotool": ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
    "wtype": ["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
    "ydotool": ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],  # KEY_LEFTCTRL, KEY_V
}


def resolve_paste_backend(choice: str) -> str:
    if choice != "auto":
        return choice
    if SYSTEM != "Linux":
        return "pynput"
    preferred = ["wtype", "ydotool"] if IS_WAYLAND else ["xdotool"]
    found = next((name for name in preferred if shutil.which(name)), None)
    if found:
        return found
    if IS_WAYLAND:
        raise RuntimeError("Wayland 에서 붙여넣으려면 wtype(wlroots 계열) 또는 ydotool(GNOME/KDE)을 설치하세요.")
    try:
        import pynput  # noqa: F401
    except Exception:
        raise RuntimeError("X11 에서 붙여넣으려면 xdotool 을 설치하세요. (sudo apt install xdotool xclip)")
    return "pynput"


class Paster:
    """확정 텍스트를 포커스된 창에 붙여넣는다. 한글 IME 충돌을 피하려고 키 타이핑 대신 클립보드를 쓴다."""

    def __init__(self, dry_run: bool, backend: str = "auto", restore_delay: float = 0.3):
        self.dry_run = dry_run
        self.restore_delay = restore_delay
        self._lock = threading.Lock()
        self.backend = "dry-run" if dry_run else resolve_paste_backend(backend)
        if dry_run:
            return
        import pyperclip  # Linux 는 xclip/xsel(X11) 또는 wl-clipboard(Wayland)를 쓴다

        self._clip = pyperclip
        if self.backend == "pynput":
            from pynput.keyboard import Controller, Key

            self._kb = Controller()
            self._mod = Key.cmd if SYSTEM == "Darwin" else Key.ctrl

    def _press_paste(self) -> None:
        if self.backend == "pynput":
            with self._kb.pressed(self._mod):
                self._kb.press("v")
                self._kb.release("v")
        else:
            subprocess.run(PASTE_COMMANDS[self.backend], check=False)

    def paste(self, text: str) -> None:
        if self.dry_run:
            print(f"[paste] {text!r}", flush=True)
            return
        with self._lock:
            try:
                previous = self._clip.paste()
            except Exception:
                previous = None
            self._clip.copy(text)
            time.sleep(0.05)
            self._press_paste()
            time.sleep(self.restore_delay)
            if previous is not None:
                self._clip.copy(previous)
