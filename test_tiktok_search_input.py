import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from adb_controller import ADBController


class TikTokSearchInputTests(unittest.TestCase):
    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_phone_popup_is_closed_before_home_feed(self, _sleep):
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        popup_root = ET.fromstring(
            '<hierarchy><node text="Thêm số điện thoại" />'
            '<node clickable="true" content-desc="Close" '
            'bounds="[930,900][1040,1010]" /></hierarchy>'
        )
        self.controller._get_tiktok_ui_root = (
            lambda _device_id, _prefix: popup_root
        )
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.dismiss_tiktok_blocking_popup("device-popup")
        )
        self.assertEqual([(985, 955)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_unknown_modal_uses_back_not_blind_tap(self, _sleep):
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        popup_root = ET.fromstring(
            '<hierarchy><node text="Add phone number" />'
            '<node text="Continue" bounds="[100,1400][980,1530]" />'
            '</hierarchy>'
        )
        self.controller._get_tiktok_ui_root = (
            lambda _device_id, _prefix: popup_root
        )
        keys = []
        self.controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        self.controller.tap = lambda *_args: self.fail("must not blind tap")

        self.assertTrue(
            self.controller.dismiss_tiktok_blocking_popup("device-popup")
        )
        self.assertEqual([4], keys)

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    @patch("adb_controller.ET.parse")
    def test_search_never_uses_blind_top_right_fallback(
        self, parse, _exists, _remove
    ):
        parse.return_value.getroot.return_value = ET.fromstring(
            '<hierarchy><node content-desc="More options" '
            'bounds="[900,20][1060,160]" /></hierarchy>'
        )
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        taps = []
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )

        self.assertFalse(
            self.controller.find_and_click_tiktok_search("device-1")
        )
        self.assertEqual([], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_recovers_when_video_ui_dump_has_no_search_node(
        self, _sleep
    ):
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id: "com.ss.android.ugc.aweme.splash.SplashActivity"
        )
        self.controller.focus_tiktok_search_input = lambda _device_id: True
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_search("device-profile")
        )
        self.assertEqual([(1015, 124)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_does_not_use_header_fallback_on_search_activity(self, _sleep):
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id: "com.ss.android.ugc.aweme.search.SearchResultActivity"
        )
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertFalse(
            self.controller.find_and_click_tiktok_search("device-search")
        )
        self.assertEqual([], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_focus_search_requires_verified_input_after_fallback(self, _sleep):
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertFalse(
            self.controller.focus_tiktok_search_input("device-no-input")
        )
        self.assertGreaterEqual(len(taps), 1)

    def test_seed_results_require_keyword_and_results_tabs(self):
        good_root = ET.fromstring(
            '<hierarchy>'
            '<node class="android.widget.EditText" text="nặn mụn" />'
            '<node text="Top" /><node text="Người dùng" />'
            '<node text="Video" />'
            '</hierarchy>'
        )
        stale_root = ET.fromstring(
            '<hierarchy><node text="Dành cho bạn" /></hierarchy>'
        )
        self.controller._get_tiktok_ui_root = (
            lambda _device_id, _prefix: good_root
        )
        self.assertTrue(
            self.controller.is_tiktok_search_results_for(
                "device-1", "nặn mụn"
            )
        )
        self.controller._get_tiktok_ui_root = (
            lambda _device_id, _prefix: stale_root
        )
        self.assertFalse(
            self.controller.is_tiktok_search_results_for(
                "device-1", "nặn mụn"
            )
        )

    def test_tiktok_keyword_is_never_sent_while_facebook_is_foreground(self):
        self.controller.is_tiktok_in_foreground = lambda _device_id: False
        broadcasts = []
        self.controller.execute_adb = (
            lambda _device_id, args, timeout=15:
            broadcasts.append(args) or (0, "", "")
        )

        with self.assertRaisesRegex(RuntimeError, "TikTok.*foreground"):
            self.controller.replace_tiktok_search_text(
                "device-facebook", "từ khóa TikTok"
            )

        self.assertEqual([], broadcasts)

    def setUp(self):
        self.controller = ADBController(adb_path="adb")
        self.commands = []
        self.controller.ensure_ime = lambda _device_id: None
        self.controller.is_tiktok_in_foreground = lambda _device_id: True

        def execute_adb(_device_id, cmd_args, timeout=15):
            self.commands.append(cmd_args)
            return 0, "Broadcast completed: result=0", ""

        self.controller.execute_adb = execute_adb

    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_transition_relaunches_until_foreground_is_stable(self, _sleep):
        foreground = iter([False, False, False, True, True, True])
        self.controller.is_tiktok_in_foreground = lambda _device_id: next(
            foreground, True
        )
        launches = []
        self.controller.launch_tiktok = lambda device_id: launches.append(device_id)
        self.controller.ensure_tiktok_home_feed = lambda _device_id: True
        self.controller.lock_portrait = lambda *_args, **_kwargs: True

        self.assertTrue(
            self.controller.ensure_tiktok_foreground_ready("device-transition")
        )
        self.assertEqual(["device-transition"], launches)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_transition_tolerates_temporary_focus_gap_without_relaunch(
        self, _sleep
    ):
        foreground = iter([False, True, True, True])
        self.controller.is_tiktok_in_foreground = lambda _device_id: next(
            foreground, True
        )
        launches = []
        self.controller.launch_tiktok = lambda device_id: launches.append(device_id)
        self.controller.ensure_tiktok_home_feed = lambda _device_id: True
        self.controller.lock_portrait = lambda *_args, **_kwargs: True

        self.assertTrue(
            self.controller.ensure_tiktok_foreground_ready("device-focus-gap")
        )
        self.assertEqual([], launches)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_transition_fails_safely_without_swiping_wrong_app(self, _sleep):
        self.controller.is_tiktok_in_foreground = lambda _device_id: False
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        swipes = []
        self.controller.swipe = lambda *_args, **_kwargs: swipes.append(_args)

        self.assertFalse(
            self.controller.ensure_tiktok_foreground_ready("device-stuck")
        )
        self.assertEqual([], swipes)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_feed_never_swipes_when_tiktok_is_not_foreground(self, _sleep):
        swipes = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller.get_tiktok_feed_signature = lambda _device_id: None
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        self.controller.is_tiktok_in_foreground = lambda _device_id: False
        self.controller.swipe = (
            lambda *_args, **_kwargs: swipes.append(_args) or (0, "", "")
        )

        self.assertFalse(self.controller.advance_tiktok_feed("device-on-shopee"))
        self.assertEqual([], swipes)

    @patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MIN", 16)
    @patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MAX", 16)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_warmup_stops_if_foreground_changes_before_swipe(
        self, _sleep, _randint
    ):
        self.controller.launch_tiktok = lambda _device_id: None
        foreground = iter([True, False])
        self.controller.is_tiktok_in_foreground = (
            lambda _device_id: next(foreground)
        )
        self.controller.ensure_tiktok_home_feed = lambda *_args, **_kwargs: True
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        advances = []
        self.controller.advance_tiktok_feed = (
            lambda device_id: advances.append(device_id) or True
        )

        with self.assertRaisesRegex(RuntimeError, "TikTok.*foreground"):
            self.controller.warmup_tiktok_before_facebook("device-1")

        self.assertEqual([], advances)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_feed_swipe_uses_override_coordinates_when_ui_dump_is_busy(
        self, _sleep
    ):
        swipes = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller.get_tiktok_feed_signature = lambda _device_id: None
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.swipe = (
            lambda _device_id, x1, y1, x2, y2, duration=300:
            swipes.append((x1, y1, x2, y2, duration)) or (0, "", "")
        )

        self.assertTrue(self.controller.advance_tiktok_feed("device-1"))
        self.assertEqual([(540, 1536, 540, 384, 450)], swipes)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_home_recovery_never_backs_out_when_ui_dump_is_busy(self, _sleep):
        taps = []
        backs = []
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )
        self.controller.keyevent = (
            lambda _device_id, keycode: backs.append(keycode)
        )

        self.assertTrue(self.controller.ensure_tiktok_home_feed("device-1"))
        self.assertGreaterEqual(len(taps), 1)
        self.assertEqual((108, 1843), taps[0])
        self.assertEqual([], backs)

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
    def test_replace_search_accepts_visually_identical_unicode_text(self, _sleep):
        self.controller.clear_tiktok_search_input = lambda _device_id: True
        self.controller.input_tiktok_search_text = lambda *_args: True
        self.controller.get_tiktok_search_input_state = lambda _device_id: {
            "text": "\u200eKênh TikTok\u00a0Mẫu\u2069",
            "focused": True,
            "coords": (486, 106),
        }

        self.assertTrue(
            self.controller.replace_tiktok_search_text(
                "device-1", "Kênh TikTok Mẫu"
            )
        )

    def test_tiktok_search_submit_sends_only_one_enter_key(self):
        keyevents = []
        self.controller.keyevent = (
            lambda _device_id, keycode: keyevents.append(keycode)
        )

        self.controller.submit_tiktok_search("device-1")

        self.assertEqual([66], keyevents)

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
    def test_channel_click_ignores_search_input_with_same_target_text(self, _sleep):
        search_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.EditText" clickable="true"
                    bounds="[120,45][850,145]"
                    resource-id="com.ss.android.ugc.trill:id/search_edit_text"
                    text="Target Channel" />
              <node class="android.widget.RelativeLayout" clickable="true"
                    bounds="[180,260][900,520]" resource-id="profile_card">
                <node class="android.widget.TextView" clickable="false"
                      bounds="[280,300][720,360]"
                      resource-id="com.ss.android.ugc.trill:id/title"
                      text="Target Channel" />
              </node>
            </hierarchy>
            """
        )
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Target Channel" />
              <node class="android.widget.Button" text="Follow" />
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
                "device-1", "Target Channel"
            )
        )
        self.assertEqual([(540, 390)], taps)

    def test_profile_verifier_supports_vietnamese_actions_and_erf_video_items(self):
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.Button"
                    text="Kênh TikTok Mẫu"
                    clickable="true"
                    bounds="[294,436][785,494]" />
              <node class="android.widget.TextView"
                    text="Đã follow"
                    resource-id="com.ss.android.ugc.trill:id/s71" />
              <node class="android.widget.TextView"
                    text=" Nhắn tin"
                    resource-id="com.ss.android.ugc.trill:id/faz" />
              <node class="android.widget.GridView"
                    resource-id="com.ss.android.ugc.trill:id/hui"
                    bounds="[0,1108][1079,1920]">
                <node class="android.widget.FrameLayout"
                      clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[0,1108][358,1585]" />
                <node class="android.widget.FrameLayout"
                      clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[361,1108][718,1585]" />
              </node>
            </hierarchy>
            """
        )

        self.assertTrue(
            self.controller.is_on_tiktok_target_profile(
                "device-1", "Kênh TikTok Mẫu", root=profile_root
            )
        )

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
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        swipes = []
        self.controller.swipe = (
            lambda _device_id, x1, y1, x2, y2, duration=300:
            swipes.append((x1, y1, x2, y2, duration))
        )

        self.assertTrue(self.controller.advance_tiktok_feed("device-1"))
        self.assertEqual(2, len(swipes))
        self.assertLess(swipes[1][4], swipes[0][4])

    @patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MIN", 16)
    @patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MAX", 16)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_cross_warmup_recovers_when_tiktok_feed_does_not_move(
        self, _sleep, _randint
    ):
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.lock_portrait = lambda _device_id, retries=2: True
        recoveries = []
        self.controller.ensure_tiktok_home_feed = (
            lambda device_id, force_refresh=False:
            recoveries.append((device_id, force_refresh)) or True
        )
        moves = iter([False, True])
        self.controller.advance_tiktok_feed = (
            lambda _device_id: next(moves)
        )

        self.assertTrue(
            self.controller.warmup_tiktok_before_facebook("device-1")
        )
        self.assertEqual(
            [("device-1", False), ("device-1", True)],
            recoveries,
        )

    def test_home_feed_accepts_tiktok_duplicate_text_and_description(self):
        root = ET.fromstring(
            """
            <hierarchy>
              <node content-desc="Thích video. 26 lượt thích" />
              <node content-desc="Đọc hoặc viết bình luận. 7 bình luận" />
              <node clickable="true" text="Trang chủ"
                    content-desc="Trang chủ" bounds="[0,1700][210,1920]" />
            </hierarchy>
            """
        )

        self.assertTrue(
            self.controller.is_tiktok_home_feed("device-1", root=root)
        )
        self.assertEqual(
            (105, 1810),
            self.controller._find_tiktok_home_navigation(root),
        )

    @patch("builtins.print")
    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_uses_task_keyword_then_replaces_it_with_target(
        self, _sleep, _randint, _uniform, _print
    ):
        entered_keywords = []
        statuses = []
        taps_after_search = []
        startup_order = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = (
            lambda _device_id, **_kwargs:
            startup_order.append("facebook_warmup") or True
        )
        self.controller.launch_tiktok = (
            lambda _device_id: startup_order.append("tiktok_workflow")
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.ensure_tiktok_home_feed = lambda *_args, **_kwargs: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: entered_keywords.append(text) or True
        )
        self.controller.submit_tiktok_search = lambda _device_id: True
        self.controller.wait_for_tiktok_search_results = lambda *_args: True
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
            ["facebook_warmup", "tiktok_workflow"],
            startup_order,
        )
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
    @patch("builtins.print")
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_keeps_b2_results_open_until_target_search(
        self, _sleep, _randint, _print, _uniform
    ):
        events = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = lambda *_args, **_kwargs: True
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.ensure_tiktok_home_feed = lambda *_args, **_kwargs: True
        self.controller.ensure_tiktok_foreground_ready = (
            lambda *_args, **_kwargs: events.append("normalize_home") or True
        )
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.find_and_click_tiktok_search = (
            lambda _device_id: events.append("open_search") or True
        )
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: events.append(f"input:{text}") or True
        )
        self.controller.submit_tiktok_search = (
            lambda _device_id: events.append("submit") or True
        )
        self.controller.wait_for_tiktok_search_results = lambda *_args: True
        self.controller.find_and_click_tiktok_channel = lambda *_args: True
        self.controller.click_random_tiktok_profile_video = lambda *_args: True

        success, _message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["từ khóa mồi"],
            target_channel="Kênh mục tiêu",
        )

        self.assertTrue(success)
        seed_input = events.index("input:từ khóa mồi")
        target_input = events.index("input:Kênh mục tiêu")
        self.assertNotIn(
            "normalize_home",
            events[seed_input + 1:target_input],
            "Sau B2 không được đưa TikTok về Home trước khi tìm kênh B3",
        )

    @patch("builtins.print")
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_never_enters_target_when_seed_search_was_not_submitted(
        self, _sleep, _randint, _print
    ):
        entered = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = lambda *_args, **_kwargs: True
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.ensure_tiktok_foreground_ready = lambda *_args, **_kwargs: True
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: entered.append(text) or True
        )
        self.controller.submit_tiktok_search = lambda _device_id: False

        success, message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["từ khóa mồi"],
            target_channel="Kênh mục tiêu",
        )

        self.assertFalse(success)
        self.assertEqual(["từ khóa mồi"], entered)
        self.assertIn("B2", message)

    @patch("builtins.print")
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_never_enters_target_when_seed_results_are_not_verified(
        self, _sleep, _randint, _print
    ):
        entered = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = lambda *_args, **_kwargs: True
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.ensure_tiktok_foreground_ready = lambda *_args, **_kwargs: True
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: entered.append(text) or True
        )
        self.controller.submit_tiktok_search = lambda _device_id: True
        self.controller.wait_for_tiktok_search_results = lambda *_args: False

        success, message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["từ khóa mồi"],
            target_channel="Kênh mục tiêu",
        )

        self.assertFalse(success)
        self.assertEqual(["từ khóa mồi"], entered)
        self.assertIn("đúng kết quả", message)

    @patch("adb_controller.random.choice", side_effect=lambda values: values[-1])
    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_randomly_selects_one_comma_separated_target_channel(
        self, _sleep, _randint, _uniform, _choice
    ):
        entered_keywords = []
        opened_channels = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = (
            lambda _device_id, **_kwargs: True
        )
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.ensure_tiktok_home_feed = lambda *_args, **_kwargs: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: entered_keywords.append(text) or True
        )
        self.controller.submit_tiktok_search = lambda _device_id: True
        self.controller.wait_for_tiktok_search_results = lambda *_args: True
        self.controller.find_and_click_tiktok_channel = (
            lambda _device_id, channel:
            opened_channels.append(channel) or True
        )
        self.controller.click_random_tiktok_profile_video = (
            lambda _device_id, channel:
            opened_channels.append(channel) or True
        )

        success, _message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["nặn mụn"],
            target_channel="Kênh TikTok A, Kênh TikTok B",
        )

        self.assertTrue(success)
        self.assertEqual(["nặn mụn", "Kênh TikTok B"], entered_keywords)
        self.assertEqual(["Kênh TikTok B", "Kênh TikTok B"], opened_channels)

    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_fails_when_target_profile_was_not_opened(
        self, _sleep, _randint, _uniform
    ):
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = (
            lambda _device_id, **_kwargs: True
        )
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.ensure_tiktok_home_feed = lambda *_args, **_kwargs: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = lambda *_args: True
        self.controller.submit_tiktok_search = lambda _device_id: True
        self.controller.wait_for_tiktok_search_results = lambda *_args: True
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
