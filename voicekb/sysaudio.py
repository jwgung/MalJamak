"""시스템 소리 캡처. 숨긴 Chrome 은 화면 공유 선택 창을 띄울 수 없으므로 소리는 여기서 잡아 엔진에 보낸다.

loopback: 기본 스피커 출력을 그대로 녹음 (Windows WASAPI loopback, Linux PulseAudio/PipeWire monitor)
그 외 이름: 해당 입력 장치 (macOS BlackHole 등)
"""

import platform
import threading
from collections.abc import Callable

SAMPLE_RATE = 16000
BLOCK = 1600  # 100ms


def list_sources() -> list[str]:
    try:
        import soundcard as sc

        return [m.name for m in sc.all_microphones(include_loopback=True)]
    except Exception as err:
        print(f"[sysaudio] 장치 목록 실패: {err}", flush=True)
        return []


def _open(source: str):
    import soundcard as sc

    if source == "loopback":
        speaker = sc.default_speaker()
        return sc.get_microphone(id=str(speaker.name), include_loopback=True)
    return sc.get_microphone(id=source, include_loopback=True)


class SystemAudio:
    def __init__(self, on_pcm: Callable[[bytes], None], on_error: Callable[[str], None]):
        self.on_pcm = on_pcm
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, source: str) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(source,), daemon=True, name="sysaudio")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self, source: str) -> None:
        try:
            if platform.system() == "Windows":
                # soundcard 는 처음 import 한 스레드에서만 COM 을 초기화한다. 캡처 스레드는 매번 새로 만들므로 직접 한다.
                import ctypes

                ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
            import numpy as np

            mic = _open(source)
            print(f"[sysaudio] 캡처 시작: {mic.name}", flush=True)
            # 채널 수는 장치 기본값으로 받고 직접 모노로 섞는다 (WASAPI loopback 은 장치 채널 수를 요구할 수 있다).
            with mic.recorder(samplerate=SAMPLE_RATE, blocksize=BLOCK) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=BLOCK)  # float32 (n, channels)
                    mono = data.mean(axis=1) if data.ndim == 2 else data
                    pcm = (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()
                    self.on_pcm(pcm)
        except Exception as err:
            self.on_error(f"시스템 소리 캡처 실패: {err}")
        finally:
            print("[sysaudio] 캡처 종료", flush=True)
