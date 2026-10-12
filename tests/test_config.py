"""설정 파일 이어받기 테스트: python -m unittest discover tests"""

import json
import tempfile
import unittest
from pathlib import Path

from voicekb.config import Config


class CaptionTranslateMigrationTest(unittest.TestCase):
    """v0.3 이전에는 PC 소리 자막이 늘 번역이었다. 외국어로 저장된 설정은 번역을 켠 채 이어받는다."""

    def load(self, raw: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            return Config(path).get()["captions"]

    def test_old_foreign_language_keeps_translation(self):
        self.assertTrue(self.load({"captions": {"lang": "en-US"}})["translate"])

    def test_old_korean_or_new_install_no_translation(self):
        self.assertFalse(self.load({"captions": {"lang": "ko-KR"}})["translate"])
        caps = self.load({})
        self.assertFalse(caps["translate"])
        self.assertEqual(caps["lang"], "ko-KR")

    def test_explicit_choice_respected(self):
        self.assertFalse(self.load({"captions": {"lang": "en-US", "translate": False}})["translate"])


if __name__ == "__main__":
    unittest.main()
