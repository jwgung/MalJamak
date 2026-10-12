"""로컬 서버: 숨긴 Chrome 엔진 페이지, 자막 창, 설정 화면을 WebSocket/HTTP 로 잇는다.

역할(role)
  engine   숨긴 Chrome 의 engine.html. 음성 인식·자막 번역을 하고 결과를 보낸다.
  overlay  자막 창 프로세스. 자막 줄을 받아 그린다.
  settings 설정 화면. 상태를 실시간으로 받는다.

다른 웹사이트가 이 서버에 붙어 글자를 몰래 입력하지 못하도록 Origin 을 검사한다.
"""

import asyncio
from collections.abc import Callable

from aiohttp import WSMsgType, web

from .config import Config, config_dir, resource_dir
from .groq import Groq
from .live import LiveSession
from .paste import Paster


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

        self.listening = False
        self.captions_on = False
        self.builtin_translator = "unknown"
        self.local_speech = "unknown"  # Chrome 기기 내 인식 API 지원 여부
        self.mics: list[dict] = []

        # 앱(트레이)이 연결하는 훅
        self.on_change: Callable[[], None] = lambda: None
        self.on_captions: Callable[[bool], None] = lambda on: None

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
                text = await self.groq.correct(text, cfg["correction"], full["glossary"]) or text
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
            await self._send(self.engine, {
                "cmd": "captions_start",
                "lang": cfg["lang"],
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

    async def set_live(self, on: bool) -> None:
        if on == self.live_on:
            return
        if on:
            if self.engine is None:
                self.last_error = "엔진(Chrome)이 아직 준비되지 않았습니다."
                await self._changed()
                return
            # 같은 엔진·마이크를 쓰므로 다른 인식은 끈다.
            await self.set_input(False)
            await self.set_captions(False)
            cfg = self.config.get()["live"]
            self.live.start()
            self.live_on = True
            self.live_preview = ""
            await self._send(self.engine, {
                "cmd": "live_start", "lang": cfg["lang"], "mic": cfg["mic"], "local": cfg["engine"] == "local",
                "processing": cfg["voice_processing"],
                "pause_ms": int(cfg["pause_seconds"] * 1000), "max_ms": int(cfg["max_wait_seconds"] * 1000),
                "stable_ms": int(cfg["stable_seconds"] * 1000),
            })
        else:
            self.live_on = False
            self.live_preview = ""
            await self._send(self.engine, {"cmd": "live_stop"})
        await self._changed()
        await self.broadcast_live()

    async def toggle_live(self) -> None:
        await self.set_live(not self.live_on)

    def _live_status(self) -> dict:
        cfg = self.config.get()["live"]
        return {"live": self.live_on, "engine": self.engine is not None, "review": cfg["review"],
                "countdown": cfg["countdown"], "transcript": str(self.live.transcript_path()) if self.live.started else "",
                "last_error": self.last_error}

    async def broadcast_live(self, queue: bool = True, display: bool = True) -> None:
        if queue:
            payload = {"type": "queue", "items": self.live.queue_view(), "preview": self.live_preview,
                       "status": self._live_status()}
            for ws in list(self.operators):
                await self._send(ws, payload)
        if display:
            cfg = self.config.get()["live"]
            payload = {"type": "display", "items": self.live.display_view(),
                       "style": {"font_size": cfg["font_size"], "lines": cfg["lines"]}}
            for ws in list(self.displays):
                await self._send(ws, payload)

    async def on_draft(self, text: str) -> None:
        if not self.live_on:
            return
        cfg = self.config.get()["live"]
        if self.live.add_draft(text, cfg["review"], cfg["countdown"]):
            await self.broadcast_live(display=False)

    async def on_operator(self, data: dict) -> None:
        cmd = data.get("cmd")
        cfg = self.config.get()["live"]
        chunk_id = data.get("id")
        changed_display = False
        if cmd == "send":
            changed_display = self.live.send(chunk_id, data.get("text"))
        elif cmd == "discard":
            changed_display = self.live.discard(chunk_id)
        elif cmd == "update":
            chunk = self.live.find(chunk_id)
            was_sent = chunk is not None and chunk.status == "sent"
            self.live.update_text(chunk_id, data.get("text", ""), cfg["countdown"])
            changed_display = was_sent
        elif cmd == "editing":
            self.live.set_editing(chunk_id, bool(data.get("on")), cfg["countdown"])
        elif cmd == "send_all":
            changed_display = self.live.send_all_pending() > 0
        elif cmd == "start":
            await self.set_live(True)
            return
        elif cmd == "stop":
            await self.set_live(False)
            return
        await self.broadcast_live(display=changed_display)

    async def run_live_ticker(self) -> None:
        """auto 방식에서 카운트다운이 끝난 조각을 내보낸다."""
        while True:
            await asyncio.sleep(0.2)
            due = self.live.due()
            for chunk in due:
                self.live.send(chunk.id)
            if due:
                await self.broadcast_live()

    def push_audio(self, pcm16: bytes) -> None:
        """시스템 소리 캡처 스레드에서 호출. 16kHz mono s16le."""
        if self.loop and self.engine is not None and self.captions_on:
            self.loop.call_soon_threadsafe(self._send_audio, pcm16)

    def _send_audio(self, pcm16: bytes) -> None:
        ws = self.engine
        if ws is not None and not ws.closed:
            asyncio.ensure_future(ws.send_bytes(pcm16))

    async def _translate(self, ws: web.WebSocketResponse, data: dict) -> None:
        if not self.groq:
            return
        ko = await self.groq.translate(data.get("text", ""), data.get("source", ""), data.get("context") or [],
                                       self.config.get()["glossary"])
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
        if "glossary" in patch:
            raw = patch["glossary"]
            items = raw.replace("\n", ",").split(",") if isinstance(raw, str) else raw
            if not isinstance(items, list):
                items = []
            seen: dict[str, None] = {}
            for item in items:
                word = str(item).strip()[:60]
                if word:
                    seen.setdefault(word, None)
            patch = {**patch, "glossary": list(seen)[:200]}
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
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
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
            if msg.type != WSMsgType.TEXT or role not in ("engine", "operator"):
                continue
            data = msg.json()
            if role == "operator":
                await hub.on_operator(data)
                continue
            kind = data.get("type")
            if kind == "final":
                text = data.get("text", "").strip()
                if text and hub.accepts_final():
                    hub._finals.put_nowait(text)
            elif kind == "input_stopped":
                # 엔진이 오류로 스스로 멈춘 경우
                hub.listening = False
                hub.last_error = data.get("reason", "")
                await hub._changed()
            elif kind == "draft":
                await hub.on_draft(data.get("text", ""))
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
                for o in list(hub.overlays):
                    await hub._send(o, {"type": "captions", **hub._last_captions})
            elif kind == "translate":
                task = asyncio.create_task(hub._translate(ws, data))
                pending.add(task)
                task.add_done_callback(pending.discard)
            elif kind == "mics":
                if hub._mics_waiter and not hub._mics_waiter.done():
                    hub._mics_waiter.set_result(data.get("mics", []))
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


def _public(cfg: dict) -> dict:
    """Groq 키는 화면에 돌려주지 않는다. 설정 여부와 끝 4자리만 알려준다."""
    key = cfg["groq"]["api_key"]
    cfg["groq"] = {**cfg["groq"], "api_key": "", "key_set": bool(key), "key_hint": key[-4:] if key else ""}
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
    app.router.add_get("/display", lambda r: web.FileResponse(web_dir / "display.html"))
    app.router.add_post("/live/toggle", toggle_handler)
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

    async def on_cleanup(_app: web.Application) -> None:
        _app["paste_worker"].cancel()
        _app["live_ticker"].cancel()
        if hub.groq:
            await hub.groq.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
