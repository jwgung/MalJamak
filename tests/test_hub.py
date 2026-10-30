"""Hub(서버) 현장 자막 흐름 테스트: python -m unittest discover tests
엔진·Groq 는 가짜로 바꿔 끼운다."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maljamak.config import Config


class FakeWS:
    closed = False

    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class FakeGroq:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    async def transcribe(self, wav, lang, prompt="", model=""):
        self.calls.append((lang, prompt, model))
        return self.texts.pop(0)

    async def close(self):
        pass


WAV = b"RIFF" + bytes(40)


class HubTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 기록·테스트 소리 폴더를 임시 폴더로 (Windows 에서도 실제 설정 폴더를 건드리지 않게)
        for patch in (mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}),
                      mock.patch("maljamak.server.config_dir", return_value=Path(self.tmp.name))):
            patch.start()
            self.addCleanup(patch.stop)
        from maljamak.server import Hub
        self.config = Config(Path(self.tmp.name) / "config.json")
        self.hub = Hub(self.config, dry_run=True)
        self.hub.loop = asyncio.get_running_loop()
        self.engine = FakeWS()
        self.hub.engine = self.engine

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def drain_stt(self):
        """받아쓰기 일꾼을 큐가 빌 때까지 돌린다."""
        worker = asyncio.create_task(self.hub.run_stt_worker())
        for _ in range(50):
            await asyncio.sleep(0)
            if self.hub._stt_queue.empty():
                break
        await asyncio.sleep(0)
        worker.cancel()

    def live_start_msg(self):
        return next(m for m in self.engine.sent if m.get("cmd") == "live_start")


class WhisperEngineTest(HubTestCase):
    async def test_whisper_needs_groq_key(self):
        self.config.update({"live": {"engine": "whisper"}})
        await self.hub.set_live(True)
        self.assertFalse(self.hub.live_on)
        self.assertIn("Groq", self.hub.last_error)

    async def test_whisper_only_in_normal_mode(self):
        self.config.update({"live": {"engine": "whisper", "mode": "interpret"}})
        self.hub.groq = FakeGroq([])
        await self.hub.set_live(True)
        self.assertFalse(self.hub.live_on)
        self.assertIn("일반 방식", self.hub.last_error)

    async def test_segments_become_chunks_in_order_with_context(self):
        self.config.update({"live": {"engine": "whisper", "review": "manual"}})
        self.hub.groq = FakeGroq(["첫 문장입니다", "", "둘째 문장입니다"])
        await self.hub.set_live(True)
        self.assertTrue(self.live_start_msg()["whisper"])
        for _ in range(3):
            self.hub.on_stt_audio(WAV)
        self.hub.on_stt_audio(b"not a wav")  # 형식이 틀리면 버린다
        await self.drain_stt()
        self.assertEqual([c.text for c in self.hub.live.items], ["첫 문장입니다", "둘째 문장입니다"])
        self.assertEqual(self.hub.groq.calls[1][1].strip(), "첫 문장입니다")  # 직전 자막을 힌트로

    async def test_last_segment_after_stop_is_kept(self):
        self.config.update({"live": {"engine": "whisper", "review": "manual"}})
        self.hub.groq = FakeGroq(["멈추기 직전의 말"])
        await self.hub.set_live(True)
        await self.hub.set_live(False)
        self.hub.on_stt_audio(WAV)  # 엔진이 멈추면서 보낸 마지막 토막
        await self.drain_stt()
        self.assertEqual([c.text for c in self.hub.live.items], ["멈추기 직전의 말"])

    async def test_old_session_segments_dropped_on_restart(self):
        self.config.update({"live": {"engine": "whisper", "review": "manual"}})
        self.hub.groq = FakeGroq(["새 세션"])
        await self.hub.set_live(True)
        self.hub.on_stt_audio(WAV)
        await self.hub.set_live(False)
        await self.hub.set_live(True)  # 다시 시작하면 지난 토막은 버린다
        self.hub.on_stt_audio(WAV)
        await self.drain_stt()
        self.assertEqual([c.text for c in self.hub.live.items], ["새 세션"])

    async def test_worker_survives_unexpected_error(self):
        self.config.update({"live": {"engine": "whisper", "review": "manual"}})

        class Broken(FakeGroq):
            async def transcribe(self, *args):
                if not self.calls:
                    self.calls.append(args)
                    raise TypeError("이상한 응답")
                return "다음 토막"
        self.hub.groq = Broken([])
        await self.hub.set_live(True)
        self.hub.on_stt_audio(WAV)
        self.hub.on_stt_audio(WAV)
        await self.drain_stt()
        self.assertEqual([c.text for c in self.hub.live.items], ["다음 토막"])

    async def test_non_string_operator_text_ignored(self):
        await self.hub.set_live(True)
        await self.hub.on_draft("조각", "pause")
        chunk = self.hub.live.items[0]
        await self.hub.on_operator({"cmd": "send", "id": chunk.id, "text": 5})
        self.assertEqual((chunk.status, chunk.text), ("sent", "조각"))

    async def test_failed_segment_reports_error(self):
        self.config.update({"live": {"engine": "whisper"}})
        self.hub.groq = FakeGroq([None])
        await self.hub.set_live(True)
        self.hub.on_stt_audio(WAV)
        await self.drain_stt()
        self.assertIn("Whisper", self.hub.last_error)


class OperatorCommandTest(HubTestCase):
    async def test_dual_choose_command(self):
        await self.hub.set_live(True)
        await self.hub.on_draft("번역", "final", side="translate", pair_id=1, source="translation")
        await self.hub.on_draft("통역", "final", side="interpret", pair_id=1)
        t, i = self.hub.live.items
        await self.hub.on_operator({"cmd": "choose", "pair_id": 1, "side": "interpret", "id": i.id, "text": "통역 (고침)"})
        self.assertEqual((t.status, i.status, i.text), ("discarded", "sent", "통역 (고침)"))

    async def test_revision_attached_by_engine_id(self):
        await self.hub.set_live(True)
        await self.hub.on_draft("로마서 활성화", "pause", eid=7)
        chunk = self.hub.live.items[0]
        await self.hub.on_operator({"cmd": "send", "id": chunk.id})
        await self.hub.on_revise(7, "로마서 8장")
        self.assertEqual((chunk.text, chunk.revision), ("로마서 활성화", "로마서 8장"))
        await self.hub.on_revise(99, "모르는 조각")  # 짝이 없으면 무시
        await self.hub.on_operator({"cmd": "dismiss_revision", "id": chunk.id})
        self.assertEqual(chunk.revision, "")

    async def test_live_start_sends_chunk_size(self):
        self.config.update({"live": {"chunk": "sentence"}})
        await self.hub.set_live(True)
        msg = self.live_start_msg()
        self.assertEqual((msg["chunk"], msg["whisper"]), ("sentence", False))


if __name__ == "__main__":
    unittest.main()
