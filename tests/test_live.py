"""현장 자막 세션 테스트: python -m unittest discover tests"""

import tempfile
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
