"""모니터 목록과 자막 화면(프로젝터)을 띄울 모니터 고르기.

지금은 Windows 만 모니터를 읽는다. 다른 OS 는 빈 목록이라 자막 화면이 예전처럼 보통 창으로 뜬다.
"""

import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class Screen:
    left: int
    top: int
    width: int
    height: int
    primary: bool


def list_screens() -> list[Screen]:
    if platform.system() != "Windows":
        return []
    try:
        return _windows_screens()
    except Exception as err:  # 모니터를 못 읽어도 자막 화면은 보통 창으로 뜬다
        print(f"[screens] 모니터 목록 실패: {err}", flush=True)
        return []


def pick_projector(screens: list[Screen]) -> Screen | None:
    """주 모니터가 아닌 첫 모니터(보통 프로젝터). 모니터가 하나뿐이면 None."""
    return next((s for s in screens if not s.primary), None)


def window_args(screen: Screen) -> list[str]:
    """그 모니터 안쪽에 작은 창을 놓고 전체 화면으로 시작하는 Chrome 인자.
    창을 모니터 한가운데 작게 두는 것은 화면 배율(DPI) 차이로 좌표가 조금 어긋나도 그 모니터 안에 떨어지게 하려는 것이다."""
    width, height = min(800, screen.width // 2), min(450, screen.height // 2)
    x = screen.left + (screen.width - width) // 2
    y = screen.top + (screen.height - height) // 2
    return [f"--window-position={x},{y}", f"--window-size={width},{height}", "--start-fullscreen"]


def _windows_screens() -> list[Screen]:
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    MONITORINFOF_PRIMARY = 1
    user32 = ctypes.windll.user32
    screens: list[Screen] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                   ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            screens.append(Screen(r.left, r.top, r.right - r.left, r.bottom - r.top,
                                  bool(info.dwFlags & MONITORINFOF_PRIMARY)))
        return True

    user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    return screens
