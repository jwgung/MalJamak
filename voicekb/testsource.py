"""테스트용 소리: 유튜브 등 영상의 소리를 내려받아 현장 자막 입력으로 쓴다 (마이크 대신).

받은 파일은 설정 폴더의 test-audio/ 에 영상 ID 로 캐시한다. ffmpeg 없이 받을 수 있는 소리 형식만 고른다.
"""

import threading
from collections.abc import Callable
from pathlib import Path


class TestSource:
    def __init__(self, cache_dir: Path, on_change: Callable[[], None]):
        self.cache_dir = cache_dir
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
        if self.view().get("status") == "downloading":
            return
        threading.Thread(target=self._download, args=(url,), daemon=True, name="test-source").start()

    def clear(self) -> None:
        self.path = None
        self._set(status="idle")

    def _download(self, url: str) -> None:
        self._set(status="downloading", progress=0, url=url)
        try:
            import yt_dlp

            def hook(d: dict) -> None:
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    progress = round(d.get("downloaded_bytes", 0) * 100 / total) if total else 0
                    if progress != self.state.get("progress"):
                        self._set(status="downloading", progress=progress, url=url)

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            opts = {
                # Chrome 이 재생·구간 이동을 확실히 지원하는 webm(opus) 우선. 변환(ffmpeg)이 필요 없는 형식만.
                "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
                "outtmpl": str(self.cache_dir / "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "progress_hooks": [hook],
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = Path(ydl.prepare_filename(info))
            if not path.exists():
                raise RuntimeError("받은 파일을 찾지 못했습니다")
            self.path = path
            self._set(status="ready", url=url, title=info.get("title", ""), duration=info.get("duration") or 0)
        except Exception as err:
            self._set(status="error", url=url, error=str(err)[:300])
