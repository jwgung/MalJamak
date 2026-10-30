"""시스템 소리 캡처. 숨긴 Chrome 은 화면 공유 선택 창을 띄울 수 없으므로 소리는 여기서 잡아 엔진에 보낸다.

loopback: 기본 스피커 출력을 그대로 녹음 (Windows WASAPI loopback, Linux PulseAudio/PipeWire monitor)
그 외 이름: 해당 입력 장치 (macOS BlackHole 등)

Windows 는 PyAudioWPatch(PortAudio WASAPI)로 받는다. numpy 가 필요 없어 설치 파일이 가볍다.
소리는 장치 기본 형식(s16, 장치 샘플레이트·채널) 그대로 넘기고, 엔진(Chrome)이 리샘플·모노로 섞는다.
macOS·Linux 는 soundcard 로 16kHz 모노를 받는다.
"""

import platform
import threading
import time
from collections.abc import Callable

IS_WINDOWS = platform.system() == "Windows"
SAMPLE_RATE = 16000  # soundcard 경로
BLOCK_SEC = 0.1
SILENCE_GAP = 0.15  # WASAPI loopback 은 재생 중인 소리가 없으면 데이터를 안 준다. 이만큼 끊기면 무음을 채운다.

# on_pcm(pcm s16le 인터리브, 샘플레이트, 채널 수)
OnPcm = Callable[[bytes, int, int], None]


def _wasapi_inputs(p) -> list[dict]:
    """WASAPI 입력 장치 (스피커의 loopback 짝도 입력 장치로 끝에 붙어 있다)."""
    import pyaudiowpatch as pyaudio

    return [d for d in p.get_device_info_generator_by_host_api(host_api_type=pyaudio.paWASAPI)
            if d["maxInputChannels"] > 0 and d["name"]]


def list_sources() -> list[str]:
    try:
        if IS_WINDOWS:
            import pyaudiowpatch as pyaudio

            with pyaudio.PyAudio() as p:
                return [d["name"] for d in _wasapi_inputs(p)]
        import soundcard as sc

        return [m.name for m in sc.all_microphones(include_loopback=True)]
    except Exception as err:
        print(f"[sysaudio] 장치 목록 실패: {err}", flush=True)
        return []


def _find_wasapi(p, source: str) -> dict:
    if source == "loopback":
        return p.get_default_wasapi_loopback()
    devices = _wasapi_inputs(p)
    for d in devices:
        if d["name"] == source:
            return d
    # 예전 버전(soundcard)에 저장된 이름은 "[Loopback]" 같은 꼬리가 없어 포함 관계로 찾는다.
    for d in devices:
        if source and source in d["name"]:
            return d
    raise LookupError(f"장치를 찾지 못했습니다: {source}")


class SystemAudio:
    def __init__(self, on_pcm: OnPcm, on_error: Callable[[str], None]):
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
            (self._run_wasapi if IS_WINDOWS else self._run_soundcard)(source)
        except Exception as err:
            self.on_error(f"시스템 소리 캡처 실패: {err}")
        finally:
            print("[sysaudio] 캡처 종료", flush=True)

    def _run_wasapi(self, source: str) -> None:
        import pyaudiowpatch as pyaudio

        with pyaudio.PyAudio() as p:
            dev = _find_wasapi(p, source)
            rate, channels = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])
            block = int(rate * BLOCK_SEC)
            silence = bytes(block * channels * 2)
            last = time.monotonic()

            def callback(data, frames, _time, _status):
                nonlocal last
                last = time.monotonic()
                self.on_pcm(data, rate, channels)
                return None, pyaudio.paContinue

            # WASAPI 공유 모드는 장치 형식대로만 열린다(리샘플은 엔진이 한다).
            with p.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                        input_device_index=dev["index"], frames_per_buffer=block, stream_callback=callback):
                print(f"[sysaudio] 캡처 시작: {dev['name']} ({rate}Hz, {channels}ch)", flush=True)
                while not self._stop.wait(BLOCK_SEC):
                    # 소리가 끊긴 동안 무음을 채워야 인식기가 말 끝을 알아채고 문장을 확정한다.
                    if time.monotonic() - last >= SILENCE_GAP:
                        last += BLOCK_SEC
                        self.on_pcm(silence, rate, channels)

    def _run_soundcard(self, source: str) -> None:
        import numpy as np  # soundcard 가 numpy 배열로 돌려준다 (macOS·Linux 전용 의존성)
        import soundcard as sc

        if source == "loopback":
            mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
        else:
            mic = sc.get_microphone(id=source, include_loopback=True)
        block = int(SAMPLE_RATE * BLOCK_SEC)
        print(f"[sysaudio] 캡처 시작: {mic.name}", flush=True)
        # 채널 수는 장치 기본값으로 받고 직접 모노로 섞는다.
        with mic.recorder(samplerate=SAMPLE_RATE, blocksize=block) as rec:
            while not self._stop.is_set():
                data = rec.record(numframes=block)  # float32 (n, channels)
                mono = data.mean(axis=1) if data.ndim == 2 else data
                self.on_pcm((np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes(), SAMPLE_RATE, 1)
