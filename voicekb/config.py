"""설정 파일 (JSON). OS별 사용자 설정 폴더에 저장한다."""

import copy
import json
import os
import platform
import sys
import threading
from pathlib import Path

APP_NAME = "VoiceKeyboard"

DEFAULTS: dict = {
    "port": 8765,
    "input": {
        "hotkey": "<ctrl>+<alt>+<space>",
        "mode": "toggle",  # toggle: 누를 때마다 시작/정지, hold: 누르고 있는 동안만
        "lang": "ko-KR",
        "mic": "",  # Chrome deviceId, 빈 값이면 기본 마이크
        "separator": " ",
        "groq_correct": True,
        "paste_backend": "auto",
    },
    "captions": {
        "lang": "en-US",
        "source": "loopback",  # loopback: 기본 스피커 출력, 그 외: 입력 장치 이름 (BlackHole 등)
        "translator": "auto",  # auto: 내장 번역 → Groq, builtin, groq
        "font_size": 22,
        "opacity": 0.85,
    },
    "groq": {"api_key": "", "model": "openai/gpt-oss-20b"},
    "autostart": False,
}


def config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "voice-keyboard"


def resource_dir() -> Path:
    """웹 리소스 위치. PyInstaller 로 묶이면 압축 해제 폴더를 쓴다."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "voicekb" / "web"


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        elif key in out:
            out[key] = value
    return out


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "config.json"
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                self.data = _merge(DEFAULTS, json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as err:
                print(f"[config] 읽기 실패, 기본값 사용: {err}", flush=True)
        # 설정 파일에 키가 없으면 환경변수를 쓴다.
        if not self.data["groq"]["api_key"]:
            self.data["groq"]["api_key"] = os.environ.get("GROQ_API_KEY", "").strip()

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def update(self, patch: dict) -> dict:
        with self._lock:
            self.data = _merge(self.data, patch)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            if os.name != "nt":
                os.chmod(tmp, 0o600)  # Groq 키가 들어 있다
            tmp.replace(self.path)
            return copy.deepcopy(self.data)
