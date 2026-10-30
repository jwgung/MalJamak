"""자막 화면을 띄울 모니터 고르기 테스트: python -m unittest discover tests"""

import unittest

from maljamak.screens import Screen, pick_projector, window_args


class PickProjectorTest(unittest.TestCase):
    def test_single_monitor_has_no_projector(self):
        self.assertIsNone(pick_projector([Screen(0, 0, 1920, 1080, True)]))
        self.assertIsNone(pick_projector([]))

    def test_picks_first_non_primary(self):
        main, projector = Screen(0, 0, 1920, 1080, True), Screen(1920, 0, 1280, 720, False)
        self.assertEqual(pick_projector([main, projector]), projector)
        self.assertEqual(pick_projector([projector, main]), projector)

    def test_window_lands_inside_monitor_even_left_of_primary(self):
        screen = Screen(-1280, 0, 1280, 720, False)
        args = window_args(screen)
        x, y = map(int, args[0].split("=")[1].split(","))
        w, h = map(int, args[1].split("=")[1].split(","))
        self.assertTrue(-1280 <= x and x + w <= 0 and 0 <= y and y + h <= 720)
        self.assertIn("--start-fullscreen", args)


if __name__ == "__main__":
    unittest.main()
