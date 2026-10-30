"""테스트 소리 내려받기 테스트(yt-dlp 명령 출력 읽기, 실행 파일 받기): python -m unittest discover tests"""

import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voicekb import testsource
from voicekb.testsource import TestSource


def fake_ytdlp(lines: list[str], code: int = 0) -> list[str]:
    """yt-dlp 대신 정해진 줄을 찍고 끝나는 명령 (뒤에 붙는 yt-dlp 인자는 무시된다)."""
    script = f"import sys\nfor l in {lines!r}: print(l, flush=True)\nsys.exit({code})"
    return [sys.executable, "-c", script]


class Response(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


def fake_release(binary: bytes, sha: str):
    name = testsource._binary_name()
    files = {"SHA2-256SUMS": f"{sha}  {name}\n{'0' * 64}  other\n".encode(), name: binary}
    return lambda url, timeout: Response(files[url.rsplit("/", 1)[1]])


class TestSourceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.states: list[dict] = []
        self.src = TestSource(Path(self.tmp.name) / "test-audio", lambda: self.states.append(self.src.view()))

    def tearDown(self):
        self.tmp.cleanup()


class YtDlpOutputTest(TestSourceCase):
    def test_reads_progress_file_title_duration(self):
        info = self.src._run(fake_ytdlp([
            "VKP 50 NA 200.0", "VKP 200 200 NA",
            "VKF /x/abc.webm", "VKT 설교 제목", "VKD 3725.5",
        ]), "bestaudio", "https://example.com/v")
        self.assertEqual(info, {"path": "/x/abc.webm", "title": "설교 제목", "duration": 3725.5})
        self.assertEqual([s["progress"] for s in self.states], [25, 100])

    def test_missing_fields_are_empty(self):
        info = self.src._run(fake_ytdlp(["VKF /x/a.m4a", "VKT NA", "VKD NA"]), "bestaudio", "u")
        self.assertEqual((info["title"], info["duration"]), ("", 0))

    def test_failure_reports_last_error_line(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP Error 403"):
            self.src._run(fake_ytdlp(["ERROR: HTTP Error 403: Forbidden"], code=1), "bestaudio", "u")


class FetchToolTest(TestSourceCase):
    """설치본은 yt-dlp 실행 파일을 처음 쓸 때 받는다. 체크섬이 맞을 때만 둔다."""

    def exe(self) -> Path:
        return self.src.tool_dir / testsource._binary_name()

    def test_checksum_match_installs_executable(self):
        body = b"yt-dlp binary"
        with mock.patch.object(testsource.urllib.request, "urlopen", fake_release(body, hashlib.sha256(body).hexdigest())):
            self.src._fetch_tool(self.exe(), "u")
        self.assertEqual(self.exe().read_bytes(), body)
        self.assertEqual(list(self.src.tool_dir.iterdir()), [self.exe()])  # .part 가 남지 않음
        self.assertEqual(self.states[0]["step"], "tool")

    def test_checksum_mismatch_leaves_nothing(self):
        with mock.patch.object(testsource.urllib.request, "urlopen", fake_release(b"tampered", "f" * 64)):
            with self.assertRaisesRegex(RuntimeError, "체크섬"):
                self.src._fetch_tool(self.exe(), "u")
        self.assertEqual(list(self.src.tool_dir.iterdir()), [])

    def test_stale_executable_kept_when_refetch_fails(self):
        self.src.tool_dir.mkdir(parents=True)
        self.exe().write_bytes(b"old")
        old = 0  # 1970 → 오래된 파일
        os.utime(self.exe(), (old, old))
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(testsource.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(self.src._command("u"), [str(self.exe())])
        self.assertEqual(self.exe().read_bytes(), b"old")
        self.assertGreater(self.exe().stat().st_mtime, old)  # 일주일 뒤에 다시 확인


if __name__ == "__main__":
    unittest.main()
