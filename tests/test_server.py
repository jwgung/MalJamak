"""엔진으로 보내는 소리 프레임 테스트: python -m unittest discover tests"""

import struct
import unittest

from voicekb.server import pack_audio


class AudioFrameTest(unittest.TestCase):
    """engine.html 의 pushAudio 가 이 머리로 샘플레이트·채널 수를 읽는다 (Windows 는 장치 형식 그대로 보낸다)."""

    def test_header_carries_rate_and_channels(self):
        pcm = bytes(range(8))
        frame = pack_audio(pcm, 48000, 2)
        self.assertEqual(struct.unpack("<IHH", frame[:8]), (48000, 2, 0))
        self.assertEqual(frame[8:], pcm)


if __name__ == "__main__":
    unittest.main()
