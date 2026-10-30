"""Whisper 응답 거르기 테스트: python -m unittest discover tests"""

import unittest

from maljamak.groq import whisper_text


def seg(text, no_speech=0.05, logprob=-0.2):
    return {"text": text, "no_speech_prob": no_speech, "avg_logprob": logprob}


class WhisperTextTest(unittest.TestCase):
    def test_joins_segments(self):
        self.assertEqual(whisper_text({"segments": [seg(" 오늘 말씀은"), seg(" 로마서 8장입니다.")]}),
                         "오늘 말씀은 로마서 8장입니다.")

    def test_drops_non_speech_and_low_confidence_segments(self):
        data = {"segments": [seg(" 말씀입니다"), seg(" 시청", no_speech=0.9), seg(" 웅얼", logprob=-1.5)]}
        self.assertEqual(whisper_text(data), "말씀입니다")

    def test_drops_known_hallucinations_only_when_whole(self):
        self.assertEqual(whisper_text({"text": "시청해 주셔서 감사합니다."}), "")
        self.assertEqual(whisper_text({"text": "MBC 뉴스 이덕영입니다."}), "")
        self.assertEqual(whisper_text({"text": "감사합니다"}), "감사합니다")  # 실제로도 하는 말
        self.assertEqual(whisper_text({"text": "오늘 MBC 뉴스를 봤습니다"}), "오늘 MBC 뉴스를 봤습니다")

    def test_plain_text_response(self):
        self.assertEqual(whisper_text({"text": "  공백   정리  "}), "공백 정리")


if __name__ == "__main__":
    unittest.main()
