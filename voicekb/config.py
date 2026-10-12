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
        # normal: 한 언어 그대로. interpret: 순차통역(강사 원어와 통역 한국어가 번갈아 나옴)에서 한국어만 받는다
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
    "glossary": [],  # 자주 쓰는 고유명사·용어. Groq 교정·번역에 넘긴다.
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
