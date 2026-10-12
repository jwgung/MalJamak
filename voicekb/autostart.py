"""로그인 시 자동 실행 등록/해제."""

import platform
import plistlib
import sys
from pathlib import Path

NAME = "VoiceKeyboard"
SYSTEM = platform.system()


def launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    python = Path(sys.executable)
    if SYSTEM == "Windows" and python.with_name("pythonw.exe").exists():
        python = python.with_name("pythonw.exe")  # 로그인할 때 콘솔 창이 뜨지 않게
    return [str(python), str(Path(__file__).resolve().parent.parent / "main.py")]


def set_autostart(enabled: bool) -> None:
    cmd = launch_command()
    if SYSTEM == "Windows":
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        with key:
            if enabled:
                winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, " ".join(f'"{c}"' for c in cmd))
            else:
                try:
                    winreg.DeleteValue(key, NAME)
                except FileNotFoundError:
                    pass
    elif SYSTEM == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "com.voicekeyboard.plist"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(plistlib.dumps({"Label": "com.voicekeyboard", "ProgramArguments": cmd, "RunAtLoad": True}))
        else:
            path.unlink(missing_ok=True)
    else:
        path = Path.home() / ".config" / "autostart" / "voice-keyboard.desktop"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            exec_line = " ".join(f'"{c}"' for c in cmd)
            path.write_text(f"[Desktop Entry]\nType=Application\nName=Voice Keyboard\nExec={exec_line}\n"
                            "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
