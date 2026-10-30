"""설정 파일 (JSON). OS별 사용자 설정 폴더에 저장한다."""

import copy
import json
import os
import platform
import shutil
import sys
import threading
from pathlib import Path

APP_NAME = "MalJamak"
LEGACY_NAMES = ("VoiceKeyboard", "voice-keyboard")  # 예전 이름의 설정 폴더 (Windows·macOS, Linux)

DEFAULTS: dict = {
    "port": 8765,
    "input": {
        "hotkey": "<ctrl>+<alt>+<space>",
        "mode": "toggle",  # toggle: 누를 때마다 시작/정지, hold: 누르고 있는 동안만
        "lang": "ko-KR",
        "engine": "cloud",  # cloud: 구글 서버(정확), local: Chrome 기기 내 인식(오프라인, 덜 정확)
        "mic": "",  # Chrome deviceId, 빈 값이면 기본 마이크
        "separator": " ",
        "groq_correct": True,
        "correction": "aggressive",  # aggressive: 발음이 비슷한 단어까지 문맥으로 교정, conservative: 띄어쓰기·명백한 오류만
        "paste_backend": "auto",
    },
    "captions": {  # PC 소리 자막: 회의·강의·통화 소리를 내 화면 위 자막 창으로 (개인용, 검토 없음)
        "lang": "ko-KR",
        "translate": False,  # True 면 target_lang 으로 번역 (말하는 언어와 다를 때)
        "target_lang": "ko-KR",  # 번역해서 보여 줄 언어 (예: 한국어 설교 → 영어 자막이면 en-US)
        "engine": "cloud",
        "source": "loopback",  # loopback: 기본 스피커 출력, 그 외: 입력 장치 이름 (BlackHole 등)
        "translator": "auto",  # 번역할 때: auto(내장 번역 → Groq), builtin, groq
        "font_size": 26,
        "opacity": 0.85,
    },
    "live": {  # 현장 자막: 마이크 → 조각 → 조작자 검토 → 자막 화면
        "lang": "ko-KR",  # 자막 언어 (순차통역 모드에서는 통역사가 말하는 언어)
        # normal: 한 언어 그대로. interpret: 순차통역에서 통역 언어만 자막, 강사 원어는 참고.
        # dual: 영어 STT+번역과 한글 STT를 둘 다 자막 조각으로, 조작자가 나란히 비교 후 고른다
        "mode": "normal",
        "other_lang": "en-US",  # 순차통역 모드에서 강사가 쓰는 원어 (교정 화면 참고용으로도 인식)
        "engine": "cloud",
        "mic": "",  # 믹서 출력을 받는 USB 오디오 인터페이스 등
        "voice_processing": False,  # 잡음 제거·자동 음량. 믹서 직결이면 끄는 게 낫다
        "review": "auto",  # auto: 카운트다운 후 자동 내보내기, manual: 조작자가 내보내야 나감
        "countdown": 3.0,
        # 조각은 자연스러운 지점(문장 끝·말 멈춤·어미)에서 자른다. 이 값들은 그 판단 기준이다.
        "pause_seconds": 0.7,  # 이 시간 동안 새 말이 없으면 멈춘 것으로 보고 자른다
        "max_wait_seconds": 4.0,  # 자를 지점이 없어도 이 시간이 지나면 자른다
        "stable_seconds": 0.8,  # 이 시간 동안 바뀌지 않은 단어만 안정된 것으로 본다
        "font_size": 56,
        "lines": 2,  # 방송 자막 관례상 2줄
        "auto_break": False,  # 자동 줄바꿈(실험, 한국어 전용): 다음 조각이 오면 앞뒤 문맥으로 문장 경계를 추측. 기본은 조작자가 Shift+Enter
    },
    "groq": {"api_key": "", "model": "openai/gpt-oss-120b"},
    "autostart": False,
}


def config_dir() -> Path:
    return _config_dir(APP_NAME, "maljamak")


def _config_dir(name: str, linux_name: str) -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / name
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / name
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / linux_name


def migrate_legacy_dir() -> None:
    """예전 이름(Voice Keyboard)의 설정 폴더를 새 이름으로 옮긴다. 설정·기록·Chrome 프로필·테스트 소리가 이어진다.
    새 폴더가 이미 있으면 건드리지 않는다. 통째로 못 옮기면(파일이 잠김 등) 설정 파일만이라도 가져온다."""
    old, new = _config_dir(*LEGACY_NAMES), config_dir()
    if new.exists() or not old.is_dir():
        return
    try:
        old.rename(new)
        print(f"[config] 예전 설정 폴더를 옮김: {old} → {new}", flush=True)
    except OSError as err:
        print(f"[config] 예전 설정 폴더를 옮기지 못해 설정 파일만 복사: {err}", flush=True)
        new.mkdir(parents=True, exist_ok=True)
        if (old / "config.json").exists():
            shutil.copy2(old / "config.json", new / "config.json")


def resource_dir() -> Path:
    """웹 리소스 위치. PyInstaller 로 묶이면 압축 해제 폴더를 쓴다."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "maljamak" / "web"


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
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = _merge(DEFAULTS, raw)
                # v0.3 이전 설정: 자막은 늘 번역이었다. 원어가 외국어로 저장돼 있으면 번역을 켠 것으로 이어받는다.
                old_captions = raw.get("captions") if isinstance(raw, dict) else None
                if isinstance(old_captions, dict) and "translate" not in old_captions:
                    self.data["captions"]["translate"] = not str(self.data["captions"]["lang"]).startswith("ko")
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
