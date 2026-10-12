"""숨긴(headless) Chrome 엔진을 띄우고, 죽으면 다시 띄운다.

전용 프로필을 쓰므로 사용자의 평소 Chrome 과 섞이지 않는다.
이 프로필은 우리 로컬 페이지만 열기 때문에 마이크 권한 자동 허용 플래그를 쓴다.
"""

import os
import platform
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

SYSTEM = platform.system()


def find_chrome() -> str | None:
    override = os.environ.get("VK_CHROME")
    if override:
        return override
    candidates = {
        "Windows": [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ],
        "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "Linux": [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable")],
    }.get(SYSTEM, [])
    return next((p for p in candidates if p and Path(p).exists()), None)


class ChromeEngine:
    MAX_RESTARTS_PER_MIN = 5

    def __init__(self, url: str, profile_dir: Path, on_fail):
        self.url = url
        self.profile_dir = profile_dir
        self.on_fail = on_fail  # 실행할 수 없을 때 사유 문자열로 호출
        self._proc: subprocess.Popen | None = None
        self._running = False
        self._lock = threading.Lock()  # stop() 과 재시작 사이의 경쟁 방지
        self._restarts: list[float] = []

    def _command(self, chrome: str) -> list[str]:
        cmd = [
            chrome,
            "--headless=new",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--use-fake-ui-for-media-stream",  # 권한 창을 띄울 수 없으므로 마이크 권한 자동 허용
            "--disable-features=Translate",
        ]
        # 테스트용 추가 인자 (가짜 마이크 등)
        cmd += shlex.split(os.environ.get("VK_CHROME_ARGS", ""))
        cmd.append(self.url)
        return cmd

    def start(self) -> None:
        chrome = find_chrome()
        if not chrome:
            self.on_fail("Google Chrome 을 찾지 못했습니다. Chrome 을 설치하세요.")
            return
        self._kill_stale()
        self._running = True
        threading.Thread(target=self._supervise, args=(chrome,), daemon=True, name="chrome").start()

    def _kill_stale(self) -> None:
        """앱이 비정상 종료해 남은 엔진 Chrome 을 정리한다. 남아 있으면 프로필 잠금 때문에 새 엔진이 바로 꺼진다."""
        try:
            import psutil
        except ImportError:
            return
        marker = f"--user-data-dir={self.profile_dir}"
        stale = []
        for proc in psutil.process_iter(["cmdline"]):
            try:
                if marker in (proc.info["cmdline"] or []):
                    stale.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for proc in stale:
            proc.terminate()
        if stale:
            psutil.wait_procs(stale, timeout=5)
            print(f"[chrome] 남아 있던 엔진 {len(stale)}개 정리", flush=True)

    def _supervise(self, chrome: str) -> None:
        while True:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                if not self._running:
                    break
                self._proc = subprocess.Popen(
                    self._command(chrome),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            print(f"[chrome] 엔진 시작 (pid {self._proc.pid})", flush=True)
            self._proc.wait()
            if not self._running:
                break
            now = time.time()
            self._restarts = [t for t in self._restarts if now - t < 60] + [now]
            if len(self._restarts) > self.MAX_RESTARTS_PER_MIN:
                self.on_fail("Chrome 엔진이 계속 종료됩니다. Chrome 설치 상태를 확인하세요.")
                self._running = False
                break
            print("[chrome] 엔진 종료됨, 다시 시작", flush=True)
            time.sleep(2)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
