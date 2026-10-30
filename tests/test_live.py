"""현장 자막 세션 테스트: python -m unittest discover tests"""

import tempfile
import time
import unittest
from pathlib import Path

from maljamak.live import LiveSession, sentence_break


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


class RevisionTest(unittest.TestCase):
    """Chrome 이 이미 내보낸 말을 나중에 고쳐 확정했을 때."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = LiveSession(Path(self.tmp.name))
        self.live.start()

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_untouched_chunk_takes_revision(self):
        a, _ = self.live.add_draft("로마서 활성화 말씀을", "manual", 3)
        self.live.revise(a.id, "로마서 8장 말씀을")
        self.assertEqual((a.text, a.revision), ("로마서 8장 말씀을", ""))

    def test_sent_chunk_keeps_text_and_shows_revision(self):
        a, _ = self.live.add_draft("로마서 활성화 말씀을", "manual", 3)
        self.live.send(a.id)
        self.live.revise(a.id, "로마서 8장 말씀을")
        self.assertEqual((a.text, a.revision), ("로마서 활성화 말씀을", "로마서 8장 말씀을"))
        self.live.send(a.id, a.revision)  # 조작자가 반영
        self.assertEqual((a.text, a.revision), ("로마서 8장 말씀을", ""))
        self.assertEqual(self.live.display_view()[0]["text"], "로마서 8장 말씀을")

    def test_operator_edit_is_not_overwritten(self):
        a, _ = self.live.add_draft("로마서 활성화", "manual", 3)
        self.live.update_text(a.id, "로마서 8장 (조작자)", 3)
        self.live.revise(a.id, "로마서 8장")
        self.assertEqual((a.text, a.revision), ("로마서 8장 (조작자)", "로마서 8장"))
        self.live.dismiss_revision(a.id)
        self.assertEqual(a.revision, "")


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


class DualSttTest(unittest.TestCase):
    """이중 STT 모드: 영어 STT+번역(side=translate)과 한글 STT(side=interpret) 조각."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = LiveSession(Path(self.tmp.name))
        self.live.start()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dual_draft_with_side_and_pair(self):
        a, _ = self.live.add_draft("영어 번역 조각", "manual", 3, side="translate", pair_id=1)
        b, _ = self.live.add_draft("한글 통역 조각", "manual", 3, side="interpret", pair_id=1)
        self.assertEqual(a.side, "translate")
        self.assertEqual(b.side, "interpret")
        self.assertEqual(a.pair_id, 1)
        self.assertEqual(b.pair_id, 1)

    def test_dual_draft_without_side_is_normal(self):
        a, _ = self.live.add_draft("일반 조각", "manual", 3)
        self.assertEqual(a.side, "")
        self.assertIsNone(a.pair_id)

    def test_dual_source_preserved(self):
        a, _ = self.live.add_draft("번역된 텍스트", "manual", 3, side="translate", pair_id=1)
        a.source = "영어 원어"
        self.assertEqual(a.source, "영어 원어")

    def test_dual_queue_view_includes_side_and_pair(self):
        self.live.add_draft("번역", "manual", 3, side="translate", pair_id=1)
        self.live.add_draft("통역", "manual", 3, side="interpret", pair_id=1)
        view = self.live.queue_view()
        self.assertEqual(view[0]["side"], "translate")
        self.assertEqual(view[0]["pair_id"], 1)
        self.assertEqual(view[1]["side"], "interpret")
        self.assertEqual(view[1]["pair_id"], 1)

    def test_dual_send_and_discard(self):
        a, _ = self.live.add_draft("번역", "manual", 3, side="translate", pair_id=1)
        b, _ = self.live.add_draft("통역", "manual", 3, side="interpret", pair_id=1)
        # 조작자가 통역 쪽을 고름
        self.live.send(b.id)
        self.live.discard(a.id)
        self.assertEqual(a.status, "discarded")
        self.assertEqual(b.status, "sent")
        # 자막 화면에는 고른 쪽(통역)만
        self.assertEqual([c["text"] for c in self.live.display_view()], ["통역"])

    def test_unchosen_pair_never_auto_sent(self):
        a, _ = self.live.add_draft("번역", "auto", 0, side="translate", pair_id=1)
        b, _ = self.live.add_draft("통역", "auto", 0, side="interpret", pair_id=1)
        self.assertIsNone(a.deadline)
        self.assertEqual(self.live.due(), [])  # 자동 내보내기여도 고르기 전에는 나가지 않는다
        self.live.set_review("auto", 0)
        self.assertIsNone(b.deadline)

    def test_choose_sends_side_and_drops_later_other_side(self):
        t1, _ = self.live.add_draft("번역 하나", "auto", 3, side="translate", pair_id=1)
        i1, _ = self.live.add_draft("통역 하나", "auto", 3, side="interpret", pair_id=1)
        self.assertEqual(self.live.choose(1, "interpret"), 1)
        self.assertEqual((t1.status, i1.status), ("discarded", "sent"))
        # 같은 차례에 늦게 온 조각: 고른 쪽은 검토 방식대로, 다른 쪽은 버린다
        i2, _ = self.live.add_draft("통역 둘", "auto", 3, side="interpret", pair_id=1)
        t2, _ = self.live.add_draft("번역 둘", "auto", 3, side="translate", pair_id=1)
        self.assertEqual(i2.status, "pending")
        self.assertIsNotNone(i2.deadline)
        self.assertEqual(t2.status, "discarded")
        # 다음 차례는 다시 골라야 한다
        t3, _ = self.live.add_draft("번역 셋", "auto", 3, side="translate", pair_id=2)
        self.assertIsNone(t3.deadline)

    def test_send_on_dual_row_chooses_that_side(self):
        t, _ = self.live.add_draft("번역", "manual", 3, side="translate", pair_id=1)
        i, _ = self.live.add_draft("통역", "manual", 3, side="interpret", pair_id=1)
        self.assertTrue(self.live.send(i.id, "통역 (고침)"))
        self.assertEqual((t.status, i.status, i.text), ("discarded", "sent", "통역 (고침)"))

    def test_send_all_defaults_to_translate(self):
        t1, _ = self.live.add_draft("번역 하나", "manual", 3, side="translate", pair_id=1)
        i1, _ = self.live.add_draft("통역 하나", "manual", 3, side="interpret", pair_id=1)
        i2, _ = self.live.add_draft("통역만 있는 차례", "manual", 3, side="interpret", pair_id=2)
        self.assertEqual(self.live.send_all_pending(), 2)
        self.assertEqual([c["text"] for c in self.live.display_view()], ["번역 하나", "통역만 있는 차례"])
        self.assertEqual(i1.status, "discarded")

    def test_send_upto_in_dual(self):
        t1, _ = self.live.add_draft("번역 하나", "manual", 3, side="translate", pair_id=1)
        i1, _ = self.live.add_draft("통역 하나", "manual", 3, side="interpret", pair_id=1)
        t2, _ = self.live.add_draft("번역 둘", "manual", 3, side="translate", pair_id=2)
        i2, _ = self.live.add_draft("통역 둘", "manual", 3, side="interpret", pair_id=2)
        self.assertEqual(self.live.send_upto(i2.id), 2)  # 차례 1 은 번역(기본), 차례 2 는 고른 통역
        self.assertEqual([c["text"] for c in self.live.display_view()], ["번역 하나", "통역 둘"])
        self.assertEqual(t2.status, "discarded")


if __name__ == "__main__":
    unittest.main()
