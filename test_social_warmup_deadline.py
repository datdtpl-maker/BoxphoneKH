import unittest
from unittest.mock import patch

from adb_controller import ADBController


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += float(seconds)

    def spend(self, seconds, result=True):
        self.now += float(seconds)
        return result


class SocialWarmupDeadlineTests(unittest.TestCase):
    def test_tiktok_cross_warmup_obeys_wall_clock_deadline(self):
        adb = ADBController("dummy-adb")
        clock = _FakeClock()
        adb.launch_tiktok = lambda _device: None
        adb.is_tiktok_in_foreground = lambda _device: True
        adb.ensure_tiktok_home_feed = lambda *_args, **_kwargs: True
        adb.lock_portrait = (
            lambda *_args, **_kwargs: clock.spend(2.0)
        )
        adb.advance_tiktok_feed = lambda _device: clock.spend(6.0)

        with (
            patch("adb_controller.time.sleep", side_effect=clock.sleep),
            patch("adb_controller.time.monotonic", side_effect=lambda: clock.now),
            patch("adb_controller.random.randint", side_effect=lambda low, _high: low),
            patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MIN", 180),
            patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MAX", 180),
        ):
            adb.warmup_tiktok_before_facebook("device-1")

        self.assertLessEqual(
            clock.now,
            185,
            "Warmup phải kết thúc theo thời gian thực, không cộng thêm thời gian thao tác ADB vào sau bộ đếm.",
        )

    def test_facebook_cross_warmup_obeys_wall_clock_deadline(self):
        adb = ADBController("dummy-adb")
        clock = _FakeClock()
        signature = iter(range(1000))
        adb.get_effective_screen_size = lambda _device: (1080, 1920)
        adb.is_facebook_in_foreground = lambda _device: True
        adb.lock_portrait = (
            lambda *_args, **_kwargs: clock.spend(2.0)
        )
        adb.get_facebook_feed_signature = (
            lambda _device: clock.spend(2.0, next(signature))
        )
        adb.swipe = lambda *_args, **_kwargs: clock.spend(2.0)

        with (
            patch("adb_controller.time.sleep", side_effect=clock.sleep),
            patch("adb_controller.time.monotonic", side_effect=lambda: clock.now),
            patch("adb_controller.random.randint", side_effect=lambda low, _high: low),
        ):
            adb.browse_facebook_surface(
                "device-1",
                180,
                "facebook_cross_warmup",
            )

        self.assertLessEqual(
            clock.now,
            185,
            "Warmup Facebook phải kết thúc theo deadline thời gian thực.",
        )


if __name__ == "__main__":
    unittest.main()
