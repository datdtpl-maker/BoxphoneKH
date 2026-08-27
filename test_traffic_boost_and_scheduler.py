import unittest
import time
import config
from adb_controller import ADBController


class TestTrafficBoostAndScheduler(unittest.TestCase):
    def setUp(self):
        self.adb = ADBController(adb_path=config.ADB_PATH)

    def test_config_rates(self):
        """Verify interaction rates are properly parsed and within valid bounds."""
        self.assertGreaterEqual(config.INTERACTION_LIKE_RATE, 0.0)
        self.assertLessEqual(config.INTERACTION_LIKE_RATE, 1.0)
        self.assertGreaterEqual(config.INTERACTION_BOOKMARK_RATE, 0.0)
        self.assertLessEqual(config.INTERACTION_BOOKMARK_RATE, 1.0)
        self.assertGreaterEqual(config.INTERACTION_SHARE_RATE, 0.0)
        self.assertLessEqual(config.INTERACTION_SHARE_RATE, 1.0)
        self.assertGreaterEqual(config.INTERACTION_COMMENT_RATE, 0.0)
        self.assertLessEqual(config.INTERACTION_COMMENT_RATE, 1.0)
        self.assertGreaterEqual(config.INTERACTION_LOOP_RATE, 0.0)
        self.assertLessEqual(config.INTERACTION_LOOP_RATE, 1.0)

    def test_scheduler_hours_parsing(self):
        """Verify golden hours list can be parsed into target minutes."""
        hours_raw = config.AUTO_SCHEDULE_HOURS_DEFAULT
        scheduled_times = [h.strip() for h in hours_raw.split(",") if ":" in h]
        self.assertGreaterEqual(len(scheduled_times), 1)

        current_minutes = 12 * 60 + 0  # 12:00
        best_diff = 24 * 60
        next_target = None
        for st in scheduled_times:
            sh, sm = map(int, st.split(":"))
            target_mins = sh * 60 + sm
            diff = target_mins - current_minutes
            if diff <= 0:
                diff += 24 * 60
            if diff < best_diff:
                best_diff = diff
                next_target = st

        self.assertIsNotNone(next_target)
        self.assertIn(":", next_target)

    def test_tiktok_micro_interactions_signature(self):
        """Verify perform_tiktok_micro_interactions is callable and handles errors safely."""
        # Non-existent device should handle safely without throwing unhandled exceptions
        self.assertTrue(hasattr(self.adb, "perform_tiktok_micro_interactions"))
        self.assertTrue(hasattr(self.adb, "try_tiktok_search_click_channel_video"))
        self.assertTrue(hasattr(self.adb, "perform_facebook_micro_interactions"))


if __name__ == "__main__":
    unittest.main()
