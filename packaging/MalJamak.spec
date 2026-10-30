# PyInstaller 빌드 설정: pyinstaller packaging/MalJamak.spec
# onedir 로 묶는다 (자막 창이 같은 exe 를 --overlay 로 다시 실행하므로 onefile 의 압축 해제 지연을 피한다).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
hidden = []
# 설치 파일을 가볍게: 트레이 아이콘은 Pillow 의 그리기만 쓰므로 무거운 형식·글꼴·색 관리 확장은 뺀다 (약 11MB).
excludes = ["PIL._avif", "PIL.AvifImagePlugin", "PIL._webp", "PIL.WebPImagePlugin", "PIL._imagingcms",
            "PIL.ImageCms", "PIL._imagingft", "PIL.ImageTk", "PIL._imagingtk",
            # 테스트 소리 내려받기(yt-dlp)는 처음 쓸 때 실행 파일을 받는다 (maljamak/testsource.py)
            "yt_dlp"]
if sys.platform == "win32":
    hidden += ["pystray._win32", "pynput.keyboard._win32", "pynput.mouse._win32"]
    excludes += ["numpy", "soundcard"]  # Windows 소리 캡처는 PyAudioWPatch (maljamak/sysaudio.py)
elif sys.platform == "darwin":
    hidden += ["pystray._darwin", "pynput.keyboard._darwin", "pynput.mouse._darwin"]
else:
    hidden += ["pystray._appindicator", "pystray._xorg"]

datas = [(str(root / "maljamak" / "web"), "maljamak/web")]
if sys.platform != "win32":
    datas += collect_data_files("soundcard")

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
)
pyz = PYZ(a.pure)
icon = root / "packaging" / "icon.ico"
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MalJamak",
    console=False,
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MalJamak")
