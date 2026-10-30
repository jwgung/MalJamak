"""로컬 서버: 숨긴 Chrome 엔진 페이지, 자막 창, 설정 화면을 WebSocket/HTTP 로 잇는다.

역할(role)
  engine   숨긴 Chrome 의 engine.html. 음성 인식·자막 번역을 하고 결과를 보낸다.
  overlay  자막 창 프로세스. 자막 줄을 받아 그린다.
  settings 설정 화면. 상태를 실시간으로 받는다.

다른 웹사이트가 이 서버에 붙어 글자를 몰래 입력하지 못하도록 Origin 을 검사한다.
"""

import asyncio
import struct
import time
from collections.abc import Callable

from aiohttp import WSMsgType, web

from .config import Config, config_dir, resource_dir
from .groq import Groq
from .live import LiveSession
from .testsource import TestSource
from .paste import Paster


def _base(code: str) -> str:
    """언어 코드의 앞부분 (ko-KR → ko). 같은 언어인지 비교할 때 쓴다."""
    return str(code or "").split("-")[0].lower()


STT_QUEUE_MAX = 20  # Whisper 토막이 밀릴 때 쌓아 두는 최대 개수 (10초 토막은 약 320KB)
STT_WAV_MAX = 4 * 1024 * 1024  # 받는 Whisper 토막 최대 크기
WS_MAX_MSG = STT_WAV_MAX + 1024 * 1024  # WebSocket 한 메시지 최대 크기
STT_FLUSH_GRACE = 3.0  # 자막을 멈춘 뒤에도 엔진이 보내는 마지막 토막을 받는 시간(초)
STT_PROMPT_CHARS = 120  # 다음 토막에 힌트로 주는 직전 자막 길이 (Whisper 프롬프트는 224토큰까지)
EID_KEEP = 50  # "인식이 바뀜"을 달 수 있는 최근 조각 수 (엔진은 최근 8개만 지켜본다)


def pack_audio(pcm16: bytes, rate: int, channels: int) -> bytes:
    """엔진으로 보내는 소리 프레임: 샘플레이트(u32le) + 채널 수(u16le) + 0(u16) + s16le 인터리브 PCM.
    engine.html 의 pushAudio 와 짝이다."""
    return struct.pack("<IHH", rate, channels, 0) + pcm16


class Hub:
    def __init__(self, config: Config, dry_run: bool = False):
        self.config = config
        cfg = config.get()
        self.last_error = ""
        try:
            self.paster = Paster(dry_run=dry_run, backend=cfg["input"]["paste_backend"])
        except RuntimeError as err:  # 붙여넣기 도구가 없어도 앱은 뜨고, 상태로 알린다
            self.paster = Paster(dry_run=True)
            self.last_error = str(err)
        self.groq: Groq | None = None
        self._apply_groq(cfg)

        self.loop: asyncio.AbstractEventLoop | None = None
        self.engine: web.WebSocketResponse | None = None
        self.overlays: set[web.WebSocketResponse] = set()
        self.watchers: set[web.WebSocketResponse] = set()
        self.operators: set[web.WebSocketResponse] = set()
        self.displays: set[web.WebSocketResponse] = set()

        self.live = LiveSession(config_dir() / "transcripts")
        self.live_on = False
        self.live_preview = ""
        self.live_test = False  # 이번 현장 자막이 테스트 소리(유튜브)로 도는지
        self.live_other: list[str] = []  # 순차통역 모드: 강사 원어 인식 결과 (교정 화면 참고용)
        self._eids: dict[int, int] = {}  # 엔진 조각 번호 → 조각 id ("인식이 바뀜"을 어느 조각에 달지)
        # Whisper 엔진: 엔진이 보낸 말 토막(WAV)을 받은 순서대로 받아쓴다. 세대가 바뀌면(자막 다시 시작) 남은 토막은 버린다.
        self._stt_queue: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(maxsize=STT_QUEUE_MAX)
        self._stt_gen = 0
        self._stt_prompt = ""
        self._stt_accept_until = 0.0  # 멈춘 직후 엔진이 보내는 마지막 토막도 받는다
        self.live_whisper = False
        self._bg: set[asyncio.Task] = set()  # 번역 제안처럼 화면을 막지 않고 도는 작업 (참조를 잡아 둬야 사라지지 않는다)
        self.test = TestSource(config_dir() / "test-audio", self._test_changed)

        self.listening = False
        self.captions_on = False
        self.builtin_translator = "unknown"
        self.local_speech = "unknown"  # Chrome 기기 내 인식 API 지원 여부
        self.mics: list[dict] = []

        # 앱(트레이)이 연결하는 훅
        self.on_change: Callable[[], None] = lambda: None
        self.on_captions: Callable[[bool], None] = lambda on: None
        self.on_engine_setup: Callable[[bool], None] = lambda on: None  # 번역 모델 받기용 설치 모드 전환

        self._pasted_once = False
        self._finals: asyncio.Queue[str] = asyncio.Queue()
        # 정지 직후 엔진이 마지막 확정 문장을 보내므로 잠시 더 받는다.
        self._accept_until = 0.0
        # "누르고 있는 동안" 방식에서는 키를 뗄 때까지 붙여넣기를 미룬다.
        # (누른 채로 Ctrl+V 를 보내면 Ctrl+Alt+V 가 되고, 가짜 Ctrl 입력이 단축키 감지를 끊는다)
        self._paste_gate = asyncio.Event()
        self._paste_gate.set()
        self._mics_waiter: asyncio.Future | None = None
        self._last_captions: dict = {"lines": [], "live": None}
        self._caption_history: dict[int, dict] = {}  # PC 소리 자막 기록 (줄 id → {src, ko})
        self._caption_file = None

    # ───────── 상태 ─────────

    def status(self) -> dict:
        cfg = self.config.get()
        return {
            "engine": self.engine is not None,
            "listening": self.listening,
            "captions": self.captions_on,
            "live": self.live_on,
            "builtin_translator": self.builtin_translator,
            "local_speech": self.local_speech,
            "groq": bool(cfg["groq"]["api_key"]),
            "paste_backend": self.paster.backend,
            "last_error": self.last_error,
        }

    async def _changed(self) -> None:
        self.on_change()
        payload = {"type": "status", **self.status()}
        for ws in list(self.watchers):
            await self._send(ws, payload)

    @staticmethod
    async def _send(ws: web.WebSocketResponse | None, payload: dict) -> bool:
        if ws is None or ws.closed:
            return False
        try:
            await ws.send_json(payload)
            return True
        except ConnectionResetError:
            return False

    def _apply_groq(self, cfg: dict) -> None:
        key = cfg["groq"]["api_key"]
        old = self.groq
        self.groq = Groq(key, cfg["groq"]["model"], 6.0) if key else None
        if old and self.loop:
            asyncio.run_coroutine_threadsafe(old.close(), self.loop)

    # ───────── 다른 스레드(트레이·단축키)에서 부르는 진입점 ─────────

    def call(self, coro_fn, *args) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(coro_fn(*args), self.loop)

    # ───────── 음성 입력 ─────────

    async def _busy_with_live(self) -> bool:
        if self.live_on:
            self.last_error = "현장 자막이 켜져 있는 동안에는 쓸 수 없습니다."
            await self._changed()
            return True
        return False

    async def set_input(self, on: bool, hold: bool = False) -> None:
        if hold:
            if on:
                self._paste_gate.clear()
            else:
                self._paste_gate.set()
        if on == self.listening:
            return
        if on and self.engine is None:
            self.last_error = "엔진(Chrome)이 아직 준비되지 않았습니다."
            await self._changed()
            return
        if on and await self._busy_with_live():
            return
        cfg = self.config.get()["input"]
        self.listening = on
        if on:
            self._pasted_once = False
            await self._send(self.engine, {"cmd": "input_start", "lang": cfg["lang"], "mic": cfg["mic"],
                                           "local": cfg["engine"] == "local"})
        else:
            self._accept_until = asyncio.get_running_loop().time() + 3
            await self._send(self.engine, {"cmd": "input_stop"})
        await self._changed()

    def accepts_final(self) -> bool:
        return self.listening or asyncio.get_running_loop().time() < self._accept_until

    async def toggle_input(self) -> None:
        await self.set_input(not self.listening)

    async def run_paste_worker(self) -> None:
        """교정에 시간이 걸려도 말한 순서대로 붙여넣는다."""
        while True:
            text = await self._finals.get()
            full = self.config.get()
            cfg = full["input"]
            if self.groq and cfg["groq_correct"]:
                text = await self.groq.correct(text, cfg["correction"], cfg["lang"]) or text
            await self._paste_gate.wait()
            if self._pasted_once:
                text = cfg["separator"] + text
            self._pasted_once = True
            try:
                await asyncio.to_thread(self.paster.paste, text)
            except Exception as err:  # 붙여넣기 도구 문제는 상태로만 알린다
                self.last_error = f"붙여넣기 실패: {err}"
                await self._changed()

    # ───────── 자막 ─────────

    async def set_captions(self, on: bool) -> None:
        if on == self.captions_on:
            return
        if on and self.engine is None:
            self.last_error = "엔진(Chrome)이 아직 준비되지 않았습니다."
            await self._changed()
            return
        if on and await self._busy_with_live():
            return
        cfg = self.config.get()["captions"]
        self.captions_on = on
        if on:
            translator = cfg["translator"]
            if translator == "groq" and not self.groq:
                self.last_error = "Groq 번역을 쓰려면 설정에서 Groq API 키를 넣으세요."
            self._caption_history = {}
            self._caption_file = config_dir() / "transcripts" / f"PC자막_{time.strftime('%Y-%m-%d_%H%M%S')}.txt"
            await self._send(self.engine, {
                "cmd": "captions_start",
                "lang": cfg["lang"],
                # 말하는 언어와 번역할 언어가 같으면 번역하지 않는다
                "translate": bool(cfg["translate"]) and _base(cfg["lang"]) != _base(cfg["target_lang"]),
                "target_lang": cfg["target_lang"],
                "local": cfg["engine"] == "local",
                "translator": translator,
                "groq": self.groq is not None,
            })
        else:
            await self._send(self.engine, {"cmd": "captions_stop"})
            self._last_captions = {"lines": [], "live": None}
        # 시스템 소리 캡처·자막 창 시작/정지. 스레드 join 이 있어 이벤트 루프를 막지 않게 넘긴다.
        await asyncio.to_thread(self.on_captions, on)
        await self._changed()

    async def toggle_captions(self) -> None:
        await self.set_captions(not self.captions_on)

    # ───────── 현장 자막 ─────────

    def _test_changed(self) -> None:
        """다운로드 스레드에서 불린다."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast_live(display=False), self.loop)

    async def set_live(self, on: bool, test: bool = False, offset: float = 0.0) -> None:
        if on == self.live_on:
            return
        if on and test and self.test.path is None:
            self.last_error = "테스트 소리를 먼저 불러오세요."
            await self.broadcast_live(display=False)
            return
        if on:
            if self.engine is None:
                self.last_error = "엔진(Chrome)이 아직 준비되지 않았습니다."
                await self._changed()
                return
            cfg = self.config.get()["live"]
            whisper = cfg["engine"] == "whisper"
            if whisper and (self.groq is None or cfg["mode"] != "normal"):
                self.last_error = ("Whisper 인식을 쓰려면 설정에서 Groq API 키를 넣으세요." if self.groq is None
                                   else "Whisper 인식은 일반 방식에서만 쓸 수 있습니다. 인식 방식을 온라인으로 바꾸세요.")
                await self.broadcast_live(display=False)
                return
            # 같은 엔진·마이크를 쓰므로 다른 인식은 끈다.
            await self.set_input(False)
            await self.set_captions(False)
            self.live_whisper = whisper
            self._stt_gen += 1
            self._stt_prompt = ""
            self.live.start()
            self.live_on = True
            self.live_test = test
            self.live_other = []
            self._eids = {}
            self.live_preview = ""
            await self._send(self.engine, {
                "cmd": "live_start", "lang": cfg["lang"], "mic": cfg["mic"], "local": cfg["engine"] == "local",
                "test_audio": f"/live/test-audio?f={self.test.path.name}" if test else None,
                "mode": cfg["mode"], "other_lang": cfg["other_lang"],
                "offset": max(0.0, float(offset)),
                "processing": cfg["voice_processing"],
                "pause_ms": int(cfg["pause_seconds"] * 1000), "max_ms": int(cfg["max_wait_seconds"] * 1000),
                "stable_ms": int(cfg["stable_seconds"] * 1000), "chunk": cfg["chunk"], "whisper": whisper,
            })
        else:
            self.live_on = False
            self.live_test = False
            if self.live_whisper:
                self._stt_accept_until = time.monotonic() + STT_FLUSH_GRACE
            self.live_whisper = False
            self.live_preview = ""
            await self._send(self.engine, {"cmd": "live_stop"})
        await self._changed()
        await self.broadcast_live()

    async def toggle_live(self) -> None:
        await self.set_live(not self.live_on)

    def _live_status(self) -> dict:
        cfg = self.config.get()["live"]
        return {"live": self.live_on, "live_test": self.live_test, "test": self.test.view(), "mode": cfg["mode"],
                "recognizer": cfg["engine"],
                "test_audio": f"/live/test-audio?f={self.test.path.name}" if self.test.path else None,
                "engine": self.engine is not None, "review": cfg["review"], "paused": self.live.paused,
                "countdown": cfg["countdown"], "transcript": str(self.live.transcript_path()) if self.live.started else "",
                "last_error": self.last_error}

    async def broadcast_live(self, queue: bool = True, display: bool = True) -> None:
        if queue:
            payload = {"type": "queue", "items": self.live.queue_view(), "preview": self.live_preview,
                       "other": self.live_other[-20:],
                       "status": self._live_status()}
            for ws in list(self.operators):
                await self._send(ws, payload)
        if display:
            cfg = self.config.get()["live"]
            payload = {"type": "display", "items": self.live.display_view(),
                       "style": {"font_size": cfg["font_size"], "lines": cfg["lines"]}}
            for ws in list(self.displays):
                await self._send(ws, payload)

    async def on_draft(self, text: str, reason: str = "", side: str = "", pair_id: int | None = None,
                       source: str = "", eid: int | None = None, accept_stopped: bool = False) -> None:
        # accept_stopped: Whisper 는 멈춘 뒤에 받아쓰기가 끝나는 토막이 있어 그 세션 기록에 이어 붙인다
        if not self.live_on and not (accept_stopped and self.live.started):
            return
        cfg = self.config.get()["live"]
        # 자동 줄바꿈 추측은 한국어 어미·접속어 규칙이라 자막 언어가 한국어일 때만 쓴다 (다른 언어는 Shift+Enter)
        # dual 모드에서 영어(번역) 쪽은 한국어 어미 규칙이 맞지 않는다
        auto_break = cfg["auto_break"] and _base(cfg["lang"]) == "ko" and side != "translate"
        chunk, prev_changed = self.live.add_draft(text, cfg["review"], cfg["countdown"], reason, auto_break,
                                                  side=side, pair_id=pair_id)
        if chunk and source:
            chunk.source = source  # dual 번역 조각: 영어 원어를 보관 (조작자 참고용)
        if chunk and isinstance(eid, int):
            self._eids[eid] = chunk.id
            while len(self._eids) > EID_KEEP:
                self._eids.pop(next(iter(self._eids)))
        if chunk:
            # 앞 조각에 문장부호가 붙었고 이미 나간 조각이면 자막 화면도 갱신한다.
            await self.broadcast_live(display=prev_changed)

    def on_stt_audio(self, wav: bytes) -> None:
        """엔진(Whisper 방식): 말 한 토막. 받아쓰기는 run_stt_worker 가 순서대로 한다."""
        active = (self.live_on and self.live_whisper) or time.monotonic() < self._stt_accept_until
        if not (active and wav[:4] == b"RIFF" and len(wav) <= STT_WAV_MAX):
            return
        try:
            self._stt_queue.put_nowait((self._stt_gen, wav))
        except asyncio.QueueFull:
            print("[stt] 받아쓰기가 밀려 토막 하나를 버림", flush=True)
            self.last_error = "Whisper 받아쓰기가 밀려 말 일부를 놓쳤습니다 (Groq 응답이 느림). 빠진 말은 직접 입력으로 채워 주세요."

    async def run_stt_worker(self) -> None:
        while True:
            gen, wav = await self._stt_queue.get()
            if gen != self._stt_gen or self.groq is None:
                continue
            full = self.config.get()
            try:
                text = await self.groq.transcribe(wav, full["live"]["lang"], self._stt_prompt, full["groq"]["stt_model"])
            except Exception as err:  # 응답 하나가 이상해도 받아쓰기 일꾼은 계속 돈다
                print(f"[stt] 받아쓰기 오류: {type(err).__name__}: {err}", flush=True)
                text = None
            if gen != self._stt_gen:
                continue
            if text is None:
                self.last_error = "Whisper 인식에 실패한 토막이 있습니다 (Groq 한도·네트워크). 빠진 말은 직접 입력으로 채워 주세요."
                await self.broadcast_live(display=False)
            elif text:
                # 직전 자막을 다음 토막의 힌트로 준다 (이어지는 말투·고유명사 표기)
                self._stt_prompt = f"{self._stt_prompt} {text}".strip()[-STT_PROMPT_CHARS:]
                await self.on_draft(text, "pause", accept_stopped=True)

    async def on_revise(self, eid, text: str) -> None:
        """엔진: 이미 내보낸 조각의 말을 Chrome 이 고쳐 확정했다."""
        chunk_id = self._eids.get(eid) if isinstance(eid, int) else None
        if self.live_on and chunk_id is not None:
            self.live.revise(chunk_id, str(text))
            await self.broadcast_live(display=False)

    async def on_operator(self, data: dict) -> None:
        cmd = data.get("cmd")
        cfg = self.config.get()["live"]
        chunk_id = data.get("id")
        changed_display = False
        text = data.get("text")
        text = text if isinstance(text, str) else None  # 조각 글은 문자열만 받는다
        if cmd == "send":
            changed_display = self.live.send(chunk_id, text)
            if data.get("break_after"):
                self.live.toggle_break(chunk_id, True)
        elif cmd == "suggest":
            # 번역은 시간이 걸리므로 조작자 화면을 막지 않게 따로 돌린다
            task = asyncio.create_task(self.suggest_from_source(str(data.get("source", "")), data.get("after")))
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
            return
        elif cmd == "insert":
            # 조작자 직접 입력: after 조각 뒤(없으면 맨 끝)에 넣고 바로 내보낸다
            changed_display = self.live.add_manual(str(data.get("text", "")), data.get("after"), True) is not None
        elif cmd == "toggle_break":
            chunk = self.live.find(chunk_id)
            changed_display = self.live.toggle_break(chunk_id) and chunk.status == "sent"
        elif cmd == "discard":
            changed_display = self.live.discard(chunk_id)
        elif cmd == "update":
            chunk = self.live.find(chunk_id)
            was_sent = chunk is not None and chunk.status == "sent"
            self.live.update_text(chunk_id, str(data.get("text", "")), cfg["countdown"])
            changed_display = was_sent
        elif cmd == "dismiss_revision":
            self.live.dismiss_revision(chunk_id)
        elif cmd == "editing":
            self.live.set_editing(chunk_id, bool(data.get("on")), cfg["countdown"])
        elif cmd == "send_all":
            changed_display = self.live.send_all_pending() > 0
        elif cmd == "send_upto":
            changed_display = self.live.send_upto(chunk_id, text) > 0
        elif cmd == "choose":
            # dual: 이 차례에서 고른 쪽을 내보낸다. id·text 가 오면 고친 내용을 먼저 반영한다.
            if chunk_id is not None and text is not None:
                self.live.update_text(chunk_id, text, cfg["countdown"])
            pair_id = data.get("pair_id")
            changed_display = isinstance(pair_id, int) and self.live.choose(pair_id, str(data.get("side", ""))) > 0
        elif cmd == "pause":
            self.live.set_paused(bool(data.get("on")), cfg["countdown"])
        elif cmd == "start":
            await self.set_live(True, bool(data.get("test")), data.get("offset") or 0)
            return
        elif cmd == "test_load":
            self.test.load(str(data.get("url", "")))
            return
        elif cmd == "test_clear":
            self.test.clear()
            return
        elif cmd == "stop":
            await self.set_live(False)
            return
        await self.broadcast_live(display=changed_display)

    async def suggest_from_source(self, source: str, after_id: int | None) -> None:
        """조작자가 고른 강사 원어 문장을 번역해 제안 조각으로 넣는다 (빠진 통역 채우기).
        Groq 키가 없으면 빈 제안을 넣어 조작자가 원어를 보고 직접 쓰게 한다."""
        source = source.strip()
        if not source:
            return
        ko = ""
        if self.groq:
            cfg = self.config.get()
            # 강사 원어 → 자막 언어(통역 언어)
            ko = await self.groq.translate(source, cfg["live"]["other_lang"], [], cfg["live"]["lang"]) or ""
        self.live.add_suggestion(ko, source, after_id)
        await self.broadcast_live(display=False)

    async def run_live_ticker(self) -> None:
        """auto 방식에서 카운트다운이 끝난 조각을 내보낸다."""
        while True:
            await asyncio.sleep(0.2)
            due = self.live.due()
            for chunk in due:
                self.live.send(chunk.id)
            if due:
                await self.broadcast_live()

    def record_captions(self, lines: list[dict]) -> None:
        """확정된 자막 줄을 기록 파일에 남긴다. 번역이 늦게 와서 줄이 바뀌면 다시 쓴다."""
        changed = False
        for line in lines:
            if "id" in line and self._caption_history.get(line["id"]) != line:
                self._caption_history[line["id"]] = line
                changed = True
        if not changed or self._caption_file is None:
            return
        out = []
        for line in self._caption_history.values():
            src, ko = line.get("src", ""), line.get("ko", "")
            out.append(src if not ko or ko == src else f"{ko}\n    ({src})")
        self._caption_file.parent.mkdir(parents=True, exist_ok=True)
        self._caption_file.write_text("\n".join(out) + "\n", encoding="utf-8")

    def push_audio(self, pcm16: bytes, rate: int, channels: int) -> None:
        """시스템 소리 캡처 스레드에서 호출. s16le 인터리브. 엔진에는 형식 머리(8바이트)를 붙여 보낸다."""
        if self.loop and self.engine is not None and self.captions_on:
            self.loop.call_soon_threadsafe(self._send_audio, pack_audio(pcm16, rate, channels))

    def _send_audio(self, frame: bytes) -> None:
        ws = self.engine
        if ws is not None and not ws.closed:
            asyncio.ensure_future(ws.send_bytes(frame))

    async def _translate(self, ws: web.WebSocketResponse, data: dict) -> None:
        if not self.groq:
            return
        ko = await self.groq.translate(data.get("text", ""), data.get("source", ""), data.get("context") or [],
                                       data.get("target") or "ko-KR")
        if ko:
            await self._send(ws, {"type": "translation", "id": data.get("id"), "ko": ko})

    # ───────── 설정 ─────────

    async def list_mics(self) -> list[dict]:
        if self.engine is None:
            return self.mics
        self._mics_waiter = asyncio.get_running_loop().create_future()
        await self._send(self.engine, {"cmd": "list_mics"})
        try:
            self.mics = await asyncio.wait_for(self._mics_waiter, 3)
        except asyncio.TimeoutError:
            pass
        return self.mics

    async def apply_settings(self, patch: dict) -> dict:
        old_review = self.config.get()["live"]["review"]
        cfg = self.config.update(patch)
        self._apply_groq(cfg)
        if cfg["live"]["review"] != old_review:
            self.live.set_review(cfg["live"]["review"], cfg["live"]["countdown"])
        await self.broadcast_live()
        backend = cfg["input"]["paste_backend"]
        if backend != "auto" and backend != self.paster.backend and self.paster.backend != "dry-run":
            self.paster = Paster(dry_run=False, backend=backend)
        await self._changed()
        return cfg


# ───────── HTTP / WebSocket ─────────


def _origin_ok(request: web.Request) -> bool:
    """브라우저 요청은 Origin 이 우리 주소일 때만 허용한다. Origin 이 없으면 로컬 프로그램(자막 창, curl)."""
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    port = request.app["port"]
    return origin in (f"http://localhost:{port}", f"http://127.0.0.1:{port}")


@web.middleware
async def origin_guard(request: web.Request, handler):
    # Host 검사는 DNS 리바인딩(외부 도메인을 127.0.0.1 로 돌려 같은 출처처럼 읽기)을 막는다.
    port = request.app["port"]
    if request.host not in (f"localhost:{port}", f"127.0.0.1:{port}") or not _origin_ok(request):
        return web.Response(status=403, text="forbidden origin\n")
    return await handler(request)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    hub: Hub = request.app["hub"]
    role = request.query.get("role", "")
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=WS_MAX_MSG)
    await ws.prepare(request)

    if role == "engine":
        if hub.engine is not None and not hub.engine.closed:
            await hub.engine.close()
        hub.engine = ws
        print("[engine] connected", flush=True)
        await hub._changed()
    elif role == "overlay":
        hub.overlays.add(ws)
        await hub._send(ws, {"type": "captions", **hub._last_captions})
        await hub._send(ws, {"type": "style", **hub.config.get()["captions"]})
    elif role == "settings":
        hub.watchers.add(ws)
        await hub._send(ws, {"type": "status", **hub.status()})
    elif role == "operator":
        hub.operators.add(ws)
        await hub.broadcast_live(display=False)
    elif role == "display":
        hub.displays.add(ws)
        await hub.broadcast_live(queue=False)
    else:
        await ws.close()
        return ws

    pending: set[asyncio.Task] = set()
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY and role == "engine":
                hub.on_stt_audio(msg.data)  # Whisper 방식: 말 한 토막(WAV)
                continue
            if msg.type != WSMsgType.TEXT or role not in ("engine", "operator"):
                continue
            data = msg.json()
            if role == "operator":
                await hub.on_operator(data)
                continue
            kind = data.get("type")
            if kind == "final":
                text = data.get("text")
                text = text.strip() if isinstance(text, str) else ""
                if text and hub.accepts_final():
                    hub._finals.put_nowait(text)
            elif kind == "input_stopped":
                # 엔진이 오류로 스스로 멈춘 경우
                hub.listening = False
                hub.last_error = data.get("reason", "")
                await hub._changed()
            elif kind == "draft":
                if not isinstance(data.get("text"), str):
                    continue
                await hub.on_draft(data["text"], str(data.get("reason", "")),
                                   side=data.get("side", ""), pair_id=data.get("pair_id"),
                                   source=data.get("source", ""), eid=data.get("eid"))
            elif kind == "revise":
                await hub.on_revise(data.get("eid"), data.get("text", ""))
            elif kind == "live_other":
                hub.live_other.append(data.get("text", ""))
                hub.live_other = hub.live_other[-200:]
                await hub.broadcast_live(display=False)
            elif kind == "live_preview":
                hub.live_preview = data.get("text", "")
                await hub.broadcast_live(display=False)
            elif kind == "live_stopped":
                hub.last_error = data.get("reason", "")
                await hub.set_live(False)
            elif kind == "captions_stopped":
                hub.last_error = data.get("reason", "")
                await hub.set_captions(False)
            elif kind == "captions":
                hub._last_captions = {"lines": data.get("lines", []), "live": data.get("live")}
                hub.record_captions(data.get("lines", []))
                for o in list(hub.overlays):
                    await hub._send(o, {"type": "captions", **hub._last_captions})
            elif kind == "translate":
                task = asyncio.create_task(hub._translate(ws, data))
                pending.add(task)
                task.add_done_callback(pending.discard)
            elif kind == "mics":
                if hub._mics_waiter and not hub._mics_waiter.done():
                    hub._mics_waiter.set_result(data.get("mics", []))
            elif kind == "setup_done":
                await asyncio.to_thread(hub.on_engine_setup, False)
            elif kind == "engine_info":
                hub.builtin_translator = data.get("builtin_translator", "unknown")
                hub.local_speech = data.get("local_speech", hub.local_speech)
                await hub._changed()
            elif kind == "error":
                print(f"[engine error] {data.get('where')}: {data.get('error')}", flush=True)
    finally:
        if role == "engine" and hub.engine is ws:
            hub.engine = None
            hub.listening = False
            print("[engine] disconnected", flush=True)
            if hub.captions_on:
                await hub.set_captions(False)
            if hub.live_on:
                await hub.set_live(False)
            await hub._changed()
        hub.overlays.discard(ws)
        hub.watchers.discard(ws)
        hub.operators.discard(ws)
        hub.displays.discard(ws)
    return ws


async def toggle_handler(request: web.Request) -> web.Response:
    """OS 단축키에서 호출: curl -X POST http://localhost:8765/toggle  (자막은 /captions/toggle)"""
    hub: Hub = request.app["hub"]
    if hub.engine is None:
        return web.Response(status=409, text="엔진(Chrome)이 아직 준비되지 않았습니다.\n")
    if request.path == "/live/toggle":
        await hub.toggle_live()
        return web.Response(text=f"live {'on' if hub.live_on else 'off'}\n")
    if request.path == "/captions/toggle":
        await hub.toggle_captions()
        return web.Response(text=f"captions {'on' if hub.captions_on else 'off'}\n")
    await hub.toggle_input()
    return web.Response(text=f"input {'on' if hub.listening else 'off'}\n")


def mask_key(key: str) -> str:
    """API 키를 앞 4자·끝 4자만 보이게 가린다 (gsk_••••••••••••3f9a). 전체 키는 화면에 보내지 않는다."""
    if not key:
        return ""
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 12}{key[-4:]}"


def _public(cfg: dict) -> dict:
    """Groq 키는 화면에 돌려주지 않는다. 설정 여부와 끝 4자리만 알려준다."""
    key = cfg["groq"]["api_key"]
    cfg["groq"] = {**cfg["groq"], "api_key": "", "key_set": bool(key), "key_mask": mask_key(key)}
    return cfg


async def settings_get(request: web.Request) -> web.Response:
    hub: Hub = request.app["hub"]
    return web.json_response({"settings": _public(hub.config.get()), "status": hub.status()})


async def settings_post(request: web.Request) -> web.Response:
    """부분 설정을 받는다. groq.api_key 는 보낸 경우에만 바뀐다 (빈 문자열이면 삭제)."""
    hub: Hub = request.app["hub"]
    patch = await request.json()
    if not isinstance(patch, dict):
        return web.json_response({"error": "object expected"}, status=400)
    cfg = await hub.apply_settings(patch)
    await asyncio.to_thread(request.app["on_settings"], cfg)
    return web.json_response({"settings": _public(cfg), "status": hub.status()})


async def sources_get(request: web.Request) -> web.Response:
    hub: Hub = request.app["hub"]
    return web.json_response({
        "mics": await hub.list_mics(),
        "audio_sources": request.app["audio_sources"](),
    })


async def translator_setup(request: web.Request) -> web.Response:
    """번역 모델 받기: 엔진 Chrome 을 작은 창으로 띄워 사용자가 한 번 클릭하게 한다."""
    hub: Hub = request.app["hub"]
    await asyncio.to_thread(hub.on_engine_setup, True)
    return web.Response(text="ok\n")


async def test_audio(request: web.Request) -> web.StreamResponse:
    """불러온 테스트 소리 파일. 엔진(숨긴 Chrome)과 교정 화면이 재생한다. 구간 이동(Range)을 지원한다."""
    hub: Hub = request.app["hub"]
    if hub.test.path is None or not hub.test.path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(hub.test.path)


async def _open_display(request: web.Request) -> web.Response:
    """자막 화면을 보이는 Chrome 앱 창으로 띄운다. 프로젝터 모니터로 옮겨 F11 로 전체 화면."""
    await asyncio.to_thread(request.app["open_display"])
    return web.Response(text="ok\n")


def build_app(hub: Hub, port: int, on_settings: Callable[[dict], None],
              audio_sources: Callable[[], list[str]], open_display: Callable[[], None] = lambda: None) -> web.Application:
    app = web.Application(middlewares=[origin_guard])
    app["hub"] = hub
    app["port"] = port
    app["on_settings"] = on_settings
    app["audio_sources"] = audio_sources
    app["open_display"] = open_display
    web_dir = resource_dir()
    app.router.add_get("/", lambda r: web.HTTPFound("/settings"))
    app.router.add_get("/engine", lambda r: web.FileResponse(web_dir / "engine.html"))
    app.router.add_get("/settings", lambda r: web.FileResponse(web_dir / "settings.html"))
    app.router.add_get("/operator", lambda r: web.FileResponse(web_dir / "operator.html"))
    app.router.add_get("/ui.css", lambda r: web.FileResponse(web_dir / "ui.css"))
    app.router.add_get("/langs.js", lambda r: web.FileResponse(web_dir / "langs.js"))
    app.router.add_get("/display", lambda r: web.FileResponse(web_dir / "display.html"))
    app.router.add_post("/live/toggle", toggle_handler)
    app.router.add_get("/live/test-audio", test_audio)
    app.router.add_post("/engine/translator-setup", translator_setup)
    app.router.add_post("/live/display-window", lambda r: _open_display(r))
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/toggle", toggle_handler)
    app.router.add_post("/captions/toggle", toggle_handler)
    app.router.add_get("/api/settings", settings_get)
    app.router.add_post("/api/settings", settings_post)
    app.router.add_get("/api/sources", sources_get)

    async def on_startup(_app: web.Application) -> None:
        hub.loop = asyncio.get_running_loop()
        _app["paste_worker"] = asyncio.create_task(hub.run_paste_worker())
        _app["live_ticker"] = asyncio.create_task(hub.run_live_ticker())
        _app["stt_worker"] = asyncio.create_task(hub.run_stt_worker())

    async def on_cleanup(_app: web.Application) -> None:
        _app["paste_worker"].cancel()
        _app["live_ticker"].cancel()
        _app["stt_worker"].cancel()
        if hub.groq:
            await hub.groq.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
