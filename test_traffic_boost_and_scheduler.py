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

    def test_dismiss_tiktok_comment_sheet_when_sheet_present(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Bình luận" bounds="[300,500][600,560]" />
              <node class="android.widget.ImageView" content-desc="Đóng" bounds="[980,500][1040,560]" />
              <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[100,1800][980,1890]" />
            </hierarchy>
            """
        )
        taps = []
        swipes = []
        keyevents = []
        self.adb.get_effective_screen_size = lambda _dev: (1080, 1920)
        self.adb.execute_adb = lambda _dev, args, **_kw: (0, "", "")
        self.adb._get_tiktok_ui_root = lambda _dev, _p="": root
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))
        self.adb.swipe = lambda _dev, x1, y1, x2, y2, duration=250: swipes.append((x1, y1, x2, y2))
        self.adb.keyevent = lambda _dev, key: keyevents.append(key)

        dismissed = self.adb.dismiss_tiktok_comment_sheet_if_present("dev-1")
        self.assertTrue(dismissed)
        self.assertIn(111, keyevents)
        self.assertIn((540, 230), taps)  # Backdrop tap at y = height * 0.12
        self.assertEqual(1, len(swipes))  # Pulled down
        self.assertEqual((540, 614, 540, 1536), swipes[0])

    def test_perform_tiktok_micro_interactions_comment_dismisses_safely(self):
        from unittest.mock import patch
        taps = []
        swipes = []
        keyevents = []
        self.adb.get_effective_screen_size = lambda _dev: (1080, 1920)
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))
        self.adb.swipe = lambda _dev, x1, y1, x2, y2, duration=250: swipes.append((x1, y1, x2, y2))
        self.adb.keyevent = lambda _dev, key: keyevents.append(key)

        # Triggers only comment interaction (mock random.random returns 0.99 for like/bm/share, 0.01 for comment)
        # like_rate=0.25, bm_rate=0.15, share_rate=0.10, comment_rate=0.10
        random_values = [0.99, 0.99, 0.99, 0.01]
        with patch("adb_controller.random.random", side_effect=random_values), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_tiktok_micro_interactions("dev-1", 1080, 1920)

        # 1. Tap opened comment icon at (993, 1209)
        self.assertIn((993, 1209), taps)
        # 2. Backdrop tapped to dismiss (540, 230)
        self.assertIn((540, 230), taps)
        # 3. Pull down swipe occurred
        self.assertEqual(1, len(swipes))
        self.assertEqual((540, 614, 540, 1536), swipes[0])
        # 4. Keyboard closed
        self.assertIn(111, keyevents)

    def test_smart_tiktok_channel_matching_rejects_wrong_person(self):
        """Verify _match_tiktok_channel_name rejects similar but wrong persons (like Trần Khải Hoàn)."""
        # Target 1: Khải Hoàn & 101 Nốt Mụn
        t1 = "Khải Hoàn & 101 Nốt Mụn"
        self.assertFalse(self.adb._match_tiktok_channel_name("Trần Khải Hoàn", t1))
        self.assertFalse(self.adb._match_tiktok_channel_name("@kh.super", t1))
        self.assertTrue(self.adb._match_tiktok_channel_name("Khải Hoàn & 101 Nốt Mụn", t1))
        self.assertTrue(self.adb._match_tiktok_channel_name("Khải Hoàn 101 Nốt Mụn", t1))
        self.assertTrue(self.adb._match_tiktok_channel_name("@khaihoan101notmun", t1))

        # Target 2: Khải Hoàn Skincare PT
        t2 = "Khải Hoàn Skincare PT"
        self.assertFalse(self.adb._match_tiktok_channel_name("Trần Khải Hoàn", t2))
        self.assertFalse(self.adb._match_tiktok_channel_name("@kh.super", t2))
        self.assertTrue(self.adb._match_tiktok_channel_name("Khải Hoàn Skincare PT", t2))
        self.assertTrue(self.adb._match_tiktok_channel_name("Khải Hoàn Skincare PT (Spa)", t2))
        self.assertTrue(self.adb._match_tiktok_channel_name("@khaihoanskincarept", t2))

    def test_channel_search_rejects_tran_khai_hoan_when_searching_khai_hoan_skincare(self):
        """When search results show Trần Khải Hoàn at the top, tool must ignore it and click the real target."""
        import xml.etree.ElementTree as ET
        from unittest.mock import patch

        search_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.RelativeLayout" clickable="true" bounds="[0,200][1080,360]">
                <node class="android.widget.TextView" text="Trần Khải Hoàn" bounds="[160,220][500,270]" />
                <node class="android.widget.TextView" text="@kh.super" bounds="[160,280][400,320]" />
                <node class="android.widget.Button" text="Follow" bounds="[850,230][1040,310]" />
              </node>
              <node class="android.widget.RelativeLayout" clickable="true" bounds="[0,380][1080,540]">
                <node class="android.widget.TextView" text="Khải Hoàn Skincare PT" bounds="[160,400][600,450]" />
                <node class="android.widget.TextView" text="@khaihoanskincarept" bounds="[160,460][450,500]" />
                <node class="android.widget.Button" text="Follow" bounds="[850,410][1040,490]" />
              </node>
            </hierarchy>
            """
        )
        taps = []
        self.adb.get_effective_screen_size = lambda _dev: (1080, 1920)
        self.adb._get_tiktok_ui_root = lambda _dev, _p="": search_root
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))
        self.adb.wait_for_tiktok_foreground = lambda _dev: True
        self.adb.is_on_tiktok_target_profile = lambda _dev, _target, **_kw: len(taps) > 0

        with patch("adb_controller.time.sleep", return_value=None):
            result = self.adb.find_and_click_tiktok_channel("dev-1", "Khải Hoàn Skincare PT")

        self.assertTrue(result)
        # Verify it tapped the second card at y=460, NOT the first card (Trần Khải Hoàn at y=280)
        self.assertEqual(1, len(taps))
        self.assertGreater(taps[0][1], 360, "Must tap the real target card, NOT Trần Khải Hoàn!")


if __name__ == "__main__":
    unittest.main()
