"""설정 파일 이어받기 테스트: python -m unittest discover tests"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maljamak import config
from maljamak.config import Config


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


class LegacyDirMigrationTest(unittest.TestCase):
    """이름을 Voice Keyboard → 말자막으로 바꿨다. 예전 설정 폴더는 처음 뜰 때 새 폴더로 옮긴다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old, self.new = root / "VoiceKeyboard", root / "MalJamak"
        self.patch = mock.patch.object(config, "_config_dir",
                                       lambda name, _linux: self.old if name == "VoiceKeyboard" else self.new)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_moves_whole_folder(self):
        (self.old / "transcripts").mkdir(parents=True)
        (self.old / "config.json").write_text('{"autostart": true}', encoding="utf-8")
        config.migrate_legacy_dir()
        self.assertFalse(self.old.exists())
        self.assertTrue((self.new / "transcripts").is_dir())
        self.assertTrue(Config(self.new / "config.json").get()["autostart"])

    def test_existing_new_folder_untouched(self):
        self.old.mkdir()
        (self.old / "config.json").write_text("{}", encoding="utf-8")
        self.new.mkdir()
        config.migrate_legacy_dir()
        self.assertTrue(self.old.exists())
        self.assertFalse((self.new / "config.json").exists())

    def test_copies_settings_when_folder_cannot_move(self):
        self.old.mkdir()
        (self.old / "config.json").write_text('{"port": 9000}', encoding="utf-8")
        with mock.patch.object(Path, "rename", side_effect=PermissionError("locked")):
            config.migrate_legacy_dir()
        self.assertEqual(Config(self.new / "config.json").get()["port"], 9000)


if __name__ == "__main__":
    unittest.main()
