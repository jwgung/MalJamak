# PyInstaller 빌드 설정: pyinstaller packaging/VoiceKeyboard.spec
# onedir 로 묶는다 (자막 창이 같은 exe 를 --overlay 로 다시 실행하므로 onefile 의 압축 해제 지연을 피한다).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
hidden = []
if sys.platform == "win32":
    hidden += ["pystray._win32", "pynput.keyboard._win32", "pynput.mouse._win32"]
elif sys.platform == "darwin":
    hidden += ["pystray._darwin", "pynput.keyboard._darwin", "pynput.mouse._darwin"]
else:
    hidden += ["pystray._appindicator", "pystray._xorg"]

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=[(str(root / "voicekb" / "web"), "voicekb/web")] + collect_data_files("soundcard"),
    hiddenimports=hidden,
)
pyz = PYZ(a.pure)
icon = root / "packaging" / "icon.ico"
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceKeyboard",
    console=False,
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VoiceKeyboard")
