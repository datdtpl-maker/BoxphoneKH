import unittest
from unittest.mock import patch

from main import TelegramRealtimeTracker


class TikTokTelegramTrackerTests(unittest.TestCase):
    def test_tiktok_status_is_rendered_and_edited_in_real_time(self):
        tracker = TelegramRealtimeTracker(bot_obj=object(), chat_id=123)
        tracker.set_active_device(
            "S2",
            "device-1",
            "TikTok: Kênh TikTok Mẫu",
            1,
            1,
            platform="TikTok",
        )
        tracker.live_msg_id = 456
        tracker.last_edit_time = 0

        with patch("main.safe_edit_message") as edit_mock:
            tracker.status_callback("device-1", "[TikTok B3] Đã mở clip")

        rendered = tracker.render_progress_text()
        self.assertIn("TikTok", rendered)
        self.assertIn("[TikTok B3] Đã mở clip", rendered)
        edit_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
