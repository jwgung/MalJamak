"""앱 본체: 트레이 아이콘, 로컬 서버, 숨긴 Chrome 엔진, 단축키, 시스템 소리, 자막 창을 묶는다."""

import asyncio
import os
import signal
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from aiohttp import web

from . import sysaudio
from .autostart import set_autostart
from .chrome import ChromeEngine, find_chrome
from .config import Config, config_dir
from .hotkey import Hotkey
from .server import Hub, build_app


def _self_command(*args: str) -> list[str]:
    """자기 자신을 다른 모드로 실행하는 명령 (PyInstaller 로 묶여도 동작)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "main.py"), *args]


class App:
    def __init__(self, port: int | None, dry_run: bool, use_tray: bool):
        self.config = Config()
        cfg = self.config.get()
        self.port = port or cfg["port"]
        self.use_tray = use_tray
        self.hub = Hub(self.config, dry_run=dry_run)
        self.hub.on_change = self._on_change
        self.hub.on_captions = self._on_captions
        self.audio = sysaudio.SystemAudio(on_pcm=self.hub.push_audio, on_error=self._on_audio_error)
        self.engine = ChromeEngine(f"http://localhost:{self.port}/engine", config_dir() / "chrome-profile",
                                   on_fail=self._notify)
        self.hotkey = Hotkey(on_toggle=lambda: self.hub.call(self.hub.toggle_input),
                             on_hold=lambda on: self.hub.call(self.hub.set_input, on, True))
        self.tray = None
        self._overlay: subprocess.Popen | None = None
        self._overlay_lock = threading.Lock()
        self._server_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = threading.Event()

    # ───────── 시작 / 종료 ─────────

    def run(self) -> None:
        if not self._start_server():
            # 이미 실행 중이면 설정 화면만 열고 끝낸다.
            print(f"[app] 이미 실행 중입니다 (포트 {self.port}). 설정 화면을 엽니다.", flush=True)
            self.open_settings()
            return
        self.engine.start()
        self._apply_hotkey(self.config.get())
        print(f"[app] 실행 중 — 설정: http://localhost:{self.port}/settings", flush=True)

        if self.use_tray:
            from .tray import Tray

            self.tray = Tray(self)
            self.tray.run()  # 메인 스레드에서 돈다 (macOS 요구사항)
        else:
            signal.signal(signal.SIGINT, lambda *_: self.quit())
            signal.signal(signal.SIGTERM, lambda *_: self.quit())
            self._stopped.wait()

    def _start_server(self) -> bool:
        app = build_app(self.hub, self.port, on_settings=self._on_settings, audio_sources=sysaudio.list_sources,
                        open_display=self.open_display)
        ready = threading.Event()
        result = {"ok": False}

        def serve() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            try:
                loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", self.port).start())
                result["ok"] = True
            except OSError:
                ready.set()
                return
            ready.set()
            loop.run_forever()
            loop.run_until_complete(runner.cleanup())

        self._server_thread = threading.Thread(target=serve, daemon=True, name="server")
        self._server_thread.start()
        ready.wait()
        return result["ok"]

    def quit(self) -> None:
        print("[app] 종료", flush=True)
        self.hotkey.stop()
        self.audio.stop()
        self._stop_overlay()
        self.engine.stop()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._server_thread:
            self._server_thread.join(timeout=3)  # runner.cleanup 까지 마치게
        if self.tray:
            self.tray.stop()
        self._stopped.set()

    # ───────── 동작 ─────────

    def toggle_input(self) -> None:
        self.hub.call(self.hub.toggle_input)

    def toggle_captions(self) -> None:
        self.hub.call(self.hub.toggle_captions)

    def open_settings(self) -> None:
        webbrowser.open(f"http://localhost:{self.port}/settings")

    def open_operator(self) -> None:
        webbrowser.open(f"http://localhost:{self.port}/operator")

    def open_display(self) -> None:
        """자막 화면은 주소창 없는 Chrome 앱 창으로 띄운다. 프로젝터로 옮겨 더블클릭하면 전체 화면."""
        url = f"http://localhost:{self.port}/display"
        chrome = find_chrome()
        if chrome:
            subprocess.Popen([chrome, f"--app={url}", "--new-window"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)

    # ───────── 훅 ─────────

    def _on_change(self) -> None:
        if self.tray:
            self.tray.refresh()

    def _on_captions(self, on: bool) -> None:
        if on:
            self.audio.start(self.config.get()["captions"]["source"])
            self._start_overlay()
        else:
            self.audio.stop()
            self._stop_overlay()

    def _on_audio_error(self, message: str) -> None:
        self._notify(message)
        self.hub.call(self.hub.set_captions, False)

    def _on_settings(self, cfg: dict) -> None:
        self._apply_hotkey(cfg)
        try:
            set_autostart(cfg["autostart"])
        except Exception as err:
            self._notify(f"자동 실행 설정 실패: {err}")
        if self.hub.captions_on:
            self.audio.start(cfg["captions"]["source"])

    def _apply_hotkey(self, cfg: dict) -> None:
        reason = self.hotkey.start(cfg["input"]["hotkey"], cfg["input"]["mode"])
        if reason:
            self._notify(reason)

    def _notify(self, message: str) -> None:
        print(f"[app] {message}", flush=True)
        self.hub.last_error = message
        if self.tray:
            self.tray.notify(message)

    def _start_overlay(self) -> None:
        with self._overlay_lock:
            if self._overlay and self._overlay.poll() is None:
                return
            # 부모가 비정상 종료해도 자막 창이 남지 않도록 부모 PID 를 넘긴다.
            self._overlay = subprocess.Popen(
                _self_command("--overlay", "--port", str(self.port), "--parent", str(os.getpid())),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    def _stop_overlay(self) -> None:
        with self._overlay_lock:
            proc, self._overlay = self._overlay, None
        if proc and proc.poll() is None:
            proc.terminate()
