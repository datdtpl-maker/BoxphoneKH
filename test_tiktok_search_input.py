import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from adb_controller import ADBController


class TikTokSearchInputTests(unittest.TestCase):
    def setUp(self):
        self.controller = ADBController(adb_path="adb")
        self.commands = []
        self.controller.ensure_ime = lambda _device_id: None

        def execute_adb(_device_id, cmd_args, timeout=15):
            self.commands.append(cmd_args)
            return 0, "Broadcast completed: result=0", ""

        self.controller.execute_adb = execute_adb

    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_input_uses_only_one_utf8_xwime_broadcast(self, _sleep):
        self.controller.ensure_ime = lambda _device_id: self.fail(
            "Không được reset IME giữa thao tác xóa và nhập TikTok"
        )
        self.controller.input_tiktok_search_text(
            "device-1", "Kênh TikTok Mẫu"
        )

        broadcasts = [
            command
            for command in self.commands
            if "XW_INPUT_B64" in command
        ]
        adb_text_inputs = [
            command
            for command in self.commands
            if command[:3] == ["shell", "input", "text"]
        ]

        self.assertEqual(1, len(broadcasts))
        self.assertEqual([], adb_text_inputs)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_clear_search_uses_xwime_clear_action(self, _sleep):
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.focus_tiktok_search_input = lambda _device_id: True
        self.controller.get_tiktok_search_input_state = lambda _device_id: {
            "text": "người mới xây kênh",
            "focused": True,
            "coords": (486, 106),
        }
        self.assertTrue(self.controller.clear_tiktok_search_input("device-1"))
        clear_broadcasts = [
            command for command in self.commands if "XW_CLEAR_TEXT" in command
        ]
        self.assertEqual(1, len(clear_broadcasts))

    @patch("adb_controller.time.sleep", return_value=None)
    def test_replace_search_text_clears_then_enters_exact_target(self, _sleep):
        events = []
        self.controller.clear_tiktok_search_input = lambda _device_id: (
            events.append(("clear", None)) or True
        )
        self.controller.input_tiktok_search_text = lambda _device_id, text: (
            events.append(("input", text)) or True
        )
        self.controller.get_tiktok_search_input_state = lambda _device_id: {
            "text": "Kênh TikTok Mẫu",
            "focused": True,
            "coords": (486, 106),
        }
        self.controller.input_text_naturally = lambda _device_id, text: events.append(
            ("input", text)
        )

        self.assertTrue(
            self.controller.replace_tiktok_search_text(
                "device-1", "Kênh TikTok Mẫu"
            )
        )
        self.assertEqual(
            [("clear", None), ("input", "Kênh TikTok Mẫu")],
            events,
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_click_uses_clickable_card_and_verifies_profile(self, _sleep):
        search_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.RelativeLayout" clickable="true"
                    bounds="[0,325][1080,520]" resource-id="card">
                <node class="android.widget.TextView" clickable="false"
                      bounds="[226,355][646,405]"
                      resource-id="com.ss.android.ugc.trill:id/tv_username"
                      text="‎⁨Kênh TikTok Mẫu⁩" />
              </node>
            </hierarchy>
            """
        )
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Kênh TikTok Mẫu" />
              <node class="android.widget.Button" text="Message" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
            </hierarchy>
            """
        )
        roots = iter([search_root, profile_root])
        self.controller._get_tiktok_ui_root = lambda *_args: next(roots)
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-1", "Kênh TikTok Mẫu"
            )
        )
        self.assertEqual([(540, 422)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_profile_video_click_supports_s1_grid_resource_ids(self, _sleep):
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.GridView"
                    resource-id="com.ss.android.ugc.trill:id/hui"
                    bounds="[0,905][1079,1920]">
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[0,905][358,1382]">
                  <node class="android.widget.ImageView" clickable="false"
                        resource-id="com.ss.android.ugc.trill:id/cover"
                        bounds="[0,905][358,1382]" />
                </node>
              </node>
            </hierarchy>
            """
        )
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller._get_tiktok_ui_root = lambda *_args: profile_root
        self.controller.is_on_tiktok_target_profile = lambda *_args, **_kwargs: True
        self.controller.is_tiktok_video_player = lambda _device_id: True
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.click_random_tiktok_profile_video(
                "device-1", "Kênh TikTok Mẫu"
            )
        )
        self.assertEqual([(179, 1143)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_advance_tiktok_feed_retries_when_photo_post_does_not_change(
        self, _sleep
    ):
        signatures = iter(["photo-post", "photo-post", "next-post"])
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.get_tiktok_feed_signature = (
            lambda _device_id: next(signatures)
        )
        swipes = []
        self.controller.swipe = (
            lambda _device_id, x1, y1, x2, y2, duration=300:
            swipes.append((x1, y1, x2, y2, duration))
        )

        self.assertTrue(self.controller.advance_tiktok_feed("device-1"))
        self.assertEqual(2, len(swipes))
        self.assertLess(swipes[1][4], swipes[0][4])

    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_uses_task_keyword_then_replaces_it_with_target(
        self, _sleep, _randint, _uniform
    ):
        entered_keywords = []
        statuses = []
        taps_after_search = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: None
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: entered_keywords.append(text) or True
        )
        self.controller.press_enter = lambda _device_id: None
        self.controller.tap = lambda _device_id, x, y: taps_after_search.append((x, y))
        self.controller.find_and_click_tiktok_channel = lambda *_args: True
        self.controller.click_random_tiktok_profile_video = lambda *_args: True

        success, _message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["nặn mụn"],
            target_channel="Kênh TikTok Mẫu",
            status_callback=lambda _device_id, message: statuses.append(message),
        )

        self.assertTrue(success)
        self.assertEqual(
            ["nặn mụn", "Kênh TikTok Mẫu"],
            entered_keywords,
        )
        self.assertEqual(
            [],
            taps_after_search,
            "Bước 2 và 3 chỉ được Enter, không tap góc phải vì sẽ mở Filters",
        )
        self.assertTrue(
            any("[TikTok B2] Lướt kết quả" in message and "15s" in message for message in statuses)
        )
        self.assertTrue(
            any("[TikTok B3] Ở lại Kênh 3 phút" in message for message in statuses)
        )

    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_fails_when_target_profile_was_not_opened(
        self, _sleep, _randint, _uniform
    ):
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: None
        self.controller.replace_tiktok_search_text = lambda *_args: True
        self.controller.press_enter = lambda _device_id: None
        self.controller.tap = lambda *_args: None
        self.controller.find_and_click_tiktok_channel = lambda *_args: False

        success, message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["nặn mụn"],
            target_channel="Kênh TikTok Mẫu",
        )

        self.assertFalse(success)
        self.assertIn("không mở được kênh", message.lower())


if __name__ == "__main__":
    unittest.main()
