"""현장 자막 세션 테스트: python -m unittest discover tests"""

import tempfile
import time
import unittest
from pathlib import Path

from voicekb.live import LiveSession, sentence_break


class OperatorLineBreakTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = LiveSession(Path(self.tmp.name))
        self.live.start()

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, text):
        chunk, _ = self.live.add_draft(text, "manual", 3)
        return chunk

    def transcript_lines(self):
        return [line.split("] ", 1)[1] for line in self.live.transcript_path().read_text(encoding="utf-8").splitlines()]

    def test_shift_enter_breaks_after_chunk(self):
        a, b, c = self.add("땀도 흘리고 올라갈 때"), self.add("쉽지가 않아요"), self.add("근데 높은 산에")
        self.live.send(a.id)
        self.live.send(b.id)
        self.live.toggle_break(b.id, True)  # Shift+Enter
        self.live.send(c.id)
        self.assertEqual(self.transcript_lines(), ["땀도 흘리고 올라갈 때 쉽지가 않아요", "근데 높은 산에"])
        self.assertTrue(self.live.display_view()[1]["break_after"])

    def test_toggle_break_on_sent_chunk(self):
        a, b = self.add("보이게 되는 겁니다"), self.add("그래서")
        self.live.send(a.id)
        self.live.send(b.id)
        self.assertEqual(self.transcript_lines(), ["보이게 되는 겁니다 그래서"])
        self.live.toggle_break(a.id)
        self.assertEqual(self.transcript_lines(), ["보이게 되는 겁니다", "그래서"])
        self.live.toggle_break(a.id)
        self.assertEqual(self.transcript_lines(), ["보이게 되는 겁니다 그래서"])

    def test_operator_punctuation_breaks_line(self):
        a, b = self.add("볼 수 있기를 바랍니다"), self.add("제가 로마서 8장을")
        self.live.send(a.id, "볼 수 있기를 바랍니다.")
        self.live.send(b.id)
        self.assertEqual(self.transcript_lines(), ["볼 수 있기를 바랍니다.", "제가 로마서 8장을"])

    def test_auto_break_off_by_default(self):
        self.add("쉽지가 않아요")
        chunk, _ = self.live.add_draft("근데 높은 산에", "manual", 3, "pause")
        self.assertFalse(chunk.newline)
        self.assertEqual(self.live.items[0].text, "쉽지가 않아요")


class FillGapsTest(unittest.TestCase):
    """빠진 통역 채우기: 조작자 직접 입력과 강사 원어의 기계 번역 제안."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = LiveSession(Path(self.tmp.name))
        self.live.start()

    def tearDown(self):
        self.tmp.cleanup()

    def texts(self):
        return [c.text for c in self.live.items]

    def test_manual_insert_after_chunk_and_sent(self):
        a, _ = self.live.add_draft("하나", "auto", 3)
        b, _ = self.live.add_draft("셋", "auto", 3)
        m = self.live.add_manual("둘", after_id=a.id)
        self.assertEqual(self.texts(), ["하나", "둘", "셋"])
        self.assertEqual((m.status, m.kind), ("sent", "manual"))

    def test_manual_insert_at_end(self):
        self.live.add_draft("하나", "manual", 3)
        self.live.add_manual("끝")
        self.assertEqual(self.texts(), ["하나", "끝"])

    def test_suggestion_inserted_after_chunk_and_never_auto_sent(self):
        a, _ = self.live.add_draft("앞 조각", "auto", 0)
        self.live.add_draft("뒤 조각", "auto", 0)
        s = self.live.add_suggestion("빠진 통역 제안", "missing interpretation", after_id=a.id)
        self.assertEqual(self.texts(), ["앞 조각", "빠진 통역 제안", "뒤 조각"])
        self.assertIsNone(s.deadline)
        self.assertNotIn(s, self.live.due())
        self.live.send_all_pending()
        self.assertEqual(s.status, "pending")  # 모두 내보내기에서도 빠진다
        self.live.set_review("auto", 0)
        self.assertIsNone(s.deadline)  # 검토 방식을 바꿔도 자동으로 나가지 않는다

    def test_empty_suggestion_needs_operator_text(self):
        s = self.live.add_suggestion("", "untranslated source")
        self.assertFalse(self.live.send(s.id))
        self.assertTrue(self.live.send(s.id, "조작자가 쓴 통역"))
        self.assertEqual(s.text, "조작자가 쓴 통역")


class OperatorPaceTest(unittest.TestCase):
    """조작자가 속도를 따라가게 돕는 기능: 전체 일시정지, 여기까지 내보내기."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = LiveSession(Path(self.tmp.name))
        self.live.start()

    def tearDown(self):
        self.tmp.cleanup()

    def test_pause_stops_auto_send_and_resume_restarts_countdown(self):
        a, _ = self.live.add_draft("하나", "auto", 0)  # 기한이 바로 지난 조각
        self.live.set_paused(True, 3)
        self.assertEqual(self.live.due(), [])
        self.live.set_paused(False, 3)
        self.assertEqual(self.live.due(), [])  # 다시 흐르면 카운트다운을 새로 시작 (바로 나가지 않음)
        self.assertGreater(a.deadline, time.time() + 2)

    def test_send_upto_sends_this_and_earlier_pending(self):
        a, _ = self.live.add_draft("하나", "manual", 3)
        b, _ = self.live.add_draft("둘", "manual", 3)
        c, _ = self.live.add_draft("셋", "manual", 3)
        d, _ = self.live.add_draft("넷", "manual", 3)
        self.assertEqual(self.live.send_upto(c.id, "셋 (고침)"), 3)
        self.assertEqual([x.status for x in (a, b, c, d)], ["sent", "sent", "sent", "pending"])
        self.assertEqual(c.text, "셋 (고침)")

    def test_send_upto_skips_suggestions_unless_chosen(self):
        a, _ = self.live.add_draft("하나", "manual", 3)
        s = self.live.add_suggestion("번역 제안", "source", after_id=a.id)
        b, _ = self.live.add_draft("둘", "manual", 3)
        self.live.send_upto(b.id)
        self.assertEqual((a.status, s.status, b.status), ("sent", "pending", "sent"))
        self.assertEqual(self.live.send_upto(s.id), 1)  # 제안을 직접 고르면 나간다
        self.assertEqual(s.status, "sent")


class AutoSentenceBreakTest(unittest.TestCase):
    """자동 줄바꿈(실험): 다음 조각이 왔을 때 앞뒤 문맥으로 문장 경계를 추측한다."""

    def test_sentence_end_followed_by_new_sentence(self):
        self.assertEqual(sentence_break("땀도 흘리고 올라갈 때 쉽지가 않아요", "boundary", 0.5, "근데 높은 산에"), ".")
        self.assertEqual(sentence_break("보이게 되는 겁니다", "pause", 1.0, "그래서"), ".")
        self.assertEqual(sentence_break("이해가 되십니까", "final", 0.3, "여러분"), "?")

    def test_continuations_do_not_break(self):
        self.assertIsNone(sentence_break("바람이 더 시원한 바람이 불고", "boundary", 0.3, "좀 더 올라가면"))
        self.assertIsNone(sentence_break("근데 높은 산에 올라가기 시작하면요", "boundary", 0.3, "전에 안 보이는 것이"))
        self.assertIsNone(sentence_break("새로운 관점들이", "max", 0.2, "산에 올라갈 때"))
        self.assertIsNone(sentence_break("앞으로 말씀을", "pause", 0.8, "하는 동안에"))

    def test_operator_punctuation_always_breaks(self):
        self.assertEqual(sentence_break("이미 끝났다.", "max", 0.1, "을 통하여"), "")


if __name__ == "__main__":
    unittest.main()
