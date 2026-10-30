"""전역 단축키. toggle: 누를 때마다 시작/정지, hold: 누르고 있는 동안만 듣기.

Linux Wayland 처럼 전역 단축키를 잡을 수 없는 환경에서는 OS 단축키에 /toggle 호출을 건다.
"""

import os
import platform
from collections.abc import Callable

IS_WAYLAND = platform.system() == "Linux" and bool(os.environ.get("WAYLAND_DISPLAY"))


class Hotkey:
    def __init__(self, on_toggle: Callable[[], None], on_hold: Callable[[bool], None]):
        self.on_toggle = on_toggle
        self.on_hold = on_hold
        self._listener = None

    def start(self, combo: str, mode: str) -> str | None:
        """시작하고, 쓸 수 없으면 사유를 돌려준다."""
        self.stop()
        if IS_WAYLAND:
            return "Wayland 는 전역 단축키를 잡을 수 없습니다. OS 단축키에 /toggle 호출을 등록하세요."
        try:
            from pynput import keyboard
        except Exception as err:
            return f"전역 단축키를 쓸 수 없습니다({err}). OS 단축키에 /toggle 호출을 등록하세요."
        try:
            keys = keyboard.HotKey.parse(combo)
        except ValueError as err:
            return f"단축키 형식이 잘못되었습니다: {combo} ({err})"

        if mode == "hold":
            self._listener = self._hold_listener(keyboard, keys)
        else:
            self._listener = keyboard.GlobalHotKeys({combo: self.on_toggle})
        self._listener.daemon = True
        self._listener.start()
        return None

    def _hold_listener(self, keyboard, keys):
        target = set(keys)
        pressed: set = set()
        active = False

        def canonical(listener, key):
            return listener.canonical(key) if key is not None else None

        def on_press(key):
            nonlocal active
            pressed.add(canonical(listener, key))
            if not active and target <= pressed:
                active = True
                self.on_hold(True)

        def on_release(key):
            nonlocal active
            pressed.discard(canonical(listener, key))
            if active and not target <= pressed:
                active = False
                self.on_hold(False)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        return listener

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
