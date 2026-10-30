"""테스트용 소리: 유튜브 등 영상의 소리를 내려받아 현장 자막 입력으로 쓴다 (마이크 대신).

받은 파일은 설정 폴더의 test-audio/ 에 영상 ID 로 캐시한다. ffmpeg 없이 받을 수 있는 소리 형식만 고른다.

내려받기는 yt-dlp 명령으로 한다. 시험용 기능이라 설치 파일에는 넣지 않고(약 13MB),
설치본에서는 처음 쓸 때 yt-dlp 실행 파일을 설정 폴더의 bin/ 에 받아 둔다. 소스 실행은 설치된 yt_dlp 모듈을 쓴다.
"""

import hashlib
import importlib.util
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
UPDATE_AFTER = 7 * 24 * 3600  # 유튜브가 자주 바뀌어 받아 둔 실행 파일이 이보다 오래되면 새로 받는다
# Chrome 이 재생·구간 이동을 확실히 지원하는 webm(opus) 우선. 변환(ffmpeg)이 필요 없는 형식만.
# 영상에 따라 특정 형식이 403 으로 막히므로 차례로 시도한다.
FORMATS = ("bestaudio[ext=webm]", "bestaudio[ext=m4a]", "bestaudio")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_SUMS = 64 * 1024
MAX_TOOL = 100 * 1024 * 1024  # 실행 파일은 17~40MB. 이보다 크면 잘못된 응답으로 본다


def _number(text: str) -> float:
    """yt-dlp 출력의 숫자. 값이 없으면 "NA" 로 찍힌다."""
    try:
        return float(text)
    except ValueError:
        return 0


def _binary_name() -> str:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        return "yt-dlp.exe"
    if system == "Darwin":
        return "yt-dlp_macos"
    return "yt-dlp_linux_aarch64" if machine in ("aarch64", "arm64") else "yt-dlp_linux"


class TestSource:
    def __init__(self, cache_dir: Path, on_change: Callable[[], None]):
        self.cache_dir = cache_dir
        self.tool_dir = cache_dir.parent / "bin"  # 설정 폴더/bin
        self.on_change = on_change
        self.state: dict = {"status": "idle"}  # idle | downloading | ready | error
        self.path: Path | None = None
        self._lock = threading.Lock()

    def view(self) -> dict:
        with self._lock:
            return dict(self.state)

    def _set(self, **state) -> None:
        with self._lock:
            self.state = state
        self.on_change()

    def load(self, url: str) -> None:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            self._set(status="error", error="http(s) 주소를 넣으세요.")
            return
        with self._lock:  # 연달아 눌러도 내려받기는 하나만
            if self.state.get("status") == "downloading":
                return
            self.state = {"status": "downloading", "progress": 0, "url": url}
        self.on_change()
        threading.Thread(target=self._download, args=(url,), daemon=True, name="test-source").start()

    def clear(self) -> None:
        self.path = None
        self._set(status="idle")

    # ── yt-dlp 명령 준비 ──

    def _command(self, url: str) -> list[str]:
        if not getattr(sys, "frozen", False) and importlib.util.find_spec("yt_dlp"):
            return [sys.executable, "-m", "yt_dlp"]
        exe = self.tool_dir / _binary_name()
        if not exe.exists():
            self._fetch_tool(exe, url)
        elif time.time() - exe.stat().st_mtime > UPDATE_AFTER:
            # 자체 업데이트(-U) 대신 체크섬을 확인하며 다시 받는다. 실패하면 있던 것을 그대로 쓰고 일주일 뒤 다시 본다.
            try:
                self._fetch_tool(exe, url)
            except Exception as err:
                print(f"[test-source] yt-dlp 업데이트 실패, 있던 것을 씀: {err}", flush=True)
                os.utime(exe)
        return [str(exe)]

    def _fetch_tool(self, exe: Path, url: str) -> None:
        """yt-dlp 공식 릴리스에서 실행 파일을 받고, 같은 릴리스의 SHA2-256SUMS 로 확인한다."""
        self._set(status="downloading", step="tool", progress=0, url=url)
        name = exe.name
        with urllib.request.urlopen(RELEASE + "SHA2-256SUMS", timeout=30) as res:
            sums = {name: sha for sha, name in (line.split() for line in res.read(MAX_SUMS).decode().splitlines()
                                                if line.strip())}
        expected = sums.get(name)
        if not expected:
            raise RuntimeError(f"yt-dlp 릴리스에 {name} 이 없습니다")
        self.tool_dir.mkdir(parents=True, exist_ok=True)
        part = exe.with_name(name + ".part")
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(RELEASE + name, timeout=30) as res, part.open("wb") as out:
                total = int(res.headers.get("Content-Length") or 0)
                done = 0
                while chunk := res.read(256 * 1024):
                    done += len(chunk)
                    if done > MAX_TOOL:
                        raise RuntimeError("받는 yt-dlp 가 너무 큽니다")
                    out.write(chunk)
                    digest.update(chunk)
                    progress = round(done * 100 / total) if total else 0
                    if progress != self.state.get("progress"):
                        self._set(status="downloading", step="tool", progress=progress, url=url)
            if digest.hexdigest() != expected:
                raise RuntimeError("받은 yt-dlp 의 체크섬이 맞지 않습니다")
            part.chmod(0o755)
            part.replace(exe)
        finally:
            part.unlink(missing_ok=True)

    # ── 소리 받기 ──

    def _run(self, cmd: list[str], fmt: str, url: str) -> dict:
        args = [
            *cmd, "--no-playlist", "--quiet", "--no-warnings", "--progress", "--newline", "--color", "never",
            "--progress-template",
            "download:VKP %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s",
            "--print", "after_move:VKF %(filepath)s",
            "--print", "after_move:VKT %(title)s",
            "--print", "after_move:VKD %(duration)s",
            "-f", fmt, "-o", str(self.cache_dir / "%(id)s.%(ext)s"), url,
        ]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        info: dict = {}
        errors: list[str] = []
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                              creationflags=NO_WINDOW) as proc:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                tag, _, rest = line.partition(" ")
                if tag == "VKP":
                    done, *totals = (_number(v) for v in rest.split())
                    total = next((t for t in totals if t), 0)
                    progress = round(done * 100 / total) if total else 0
                    if progress != self.state.get("progress"):
                        self._set(status="downloading", progress=progress, url=url)
                elif tag == "VKF":
                    info["path"] = rest
                elif tag == "VKT":
                    info["title"] = "" if rest == "NA" else rest
                elif tag == "VKD":
                    info["duration"] = _number(rest)
                elif line:
                    errors.append(line)
        if proc.returncode != 0 or not info.get("path"):
            raise RuntimeError(errors[-1] if errors else f"yt-dlp 종료 코드 {proc.returncode}")
        return info

    def _download(self, url: str) -> None:
        try:
            cmd = self._command(url)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            last_err: Exception | None = None
            for fmt in FORMATS:
                try:
                    info = self._run(cmd, fmt, url)
                    break
                except Exception as err:  # 형식 없음·403 등 → 다음 형식
                    last_err = err
            else:
                raise last_err or RuntimeError("받을 수 있는 소리 형식이 없습니다")
            path = Path(info["path"])
            if not path.exists():
                raise RuntimeError("받은 파일을 찾지 못했습니다")
            self.path = path
            self._set(status="ready", url=url, title=info.get("title", ""), duration=info.get("duration") or 0)
        except Exception as err:
            self._set(status="error", url=url, error=str(err)[:300])
