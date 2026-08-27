import base64
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from adb_controller import ADBController


class TikTokSearchInputTests(unittest.TestCase):
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    @patch("adb_controller.ET.parse")
    def test_search_more_node_is_never_treated_as_search_input(
        self, parse, _exists, _remove
    ):
        parse.return_value.getroot.return_value = ET.fromstring(
            '<hierarchy>'
            '<node clickable="true" '
            'resource-id="com.zhiliaoapp.musically:id/search_more" '
            'content-desc="More options" bounds="[900,35][1060,175]" />'
            '</hierarchy>'
        )
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)

        self.assertIsNone(
            self.controller.get_tiktok_search_input_state("device-search-more")
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_b3_closes_existing_filter_panel_before_focusing_query(self, _sleep):
        filter_root = ET.fromstring(
            '<hierarchy><node text="Filters" />'
            '<node text="Share feedback" /></hierarchy>'
        )
        self.controller._get_tiktok_ui_root = lambda *_args: filter_root
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        keys = []
        taps = []
        self.controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y)) or (0, "", "")
        )

        self.assertTrue(
            self.controller.focus_tiktok_existing_search_bar("device-filter")
        )
        self.assertEqual([4], keys)
        self.assertEqual([(486, 105)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_b3_existing_results_never_taps_search_more_filter_button(
        self, _sleep
    ):
        """B3 phải focus thanh query bên trái, không chạm search_more."""
        root = ET.fromstring(
            '<hierarchy>'
            '<node class="android.widget.TextView" '
            'text="lấy nhân mụn chuẩn y khoa Phan Thiết" '
            'bounds="[100,45][875,165]" />'
            '<node clickable="true" resource-id="com.zhiliaoapp.musically:id/search_more" '
            'content-desc="More options" bounds="[900,35][1060,175]" />'
            '<node text="Top" bounds="[100,180][220,250]" />'
            '</hierarchy>'
        )
        self.controller._get_tiktok_ui_root = lambda *_args: root
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id: "com.ss.android.ugc.aweme.splash.SplashActivity"
        )
        taps = []
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y)) or (0, "", "")
        )

        self.assertTrue(
            self.controller.focus_tiktok_existing_search_bar("device-results")
        )
        self.assertTrue(taps)
        self.assertTrue(all(x < 850 for x, _y in taps), taps)
        self.assertNotIn((980, 105), taps)

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
        self.assertEqual([(1015, 124), (486, 105)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_activity_focuses_existing_input_without_back(self, _sleep):
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id:
            "com.ss.android.ugc.aweme.search.SearchResultActivity"
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        focuses = []
        self.controller.focus_tiktok_search_input = (
            lambda device_id: focuses.append(device_id) or True
        )
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        keys = []
        taps = []
        self.controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.find_and_click_tiktok_search("device-search")
        )
        self.assertEqual(["device-search"], focuses)
        self.assertEqual([], keys)
        self.assertEqual([], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_generic_activity_busy_xml_still_enters_keyword_without_back(
        self, _sleep
    ):
        """Màn Search thật dùng activity chung vẫn phải CLEAR + INPUT + ENTER."""
        self.controller.dismiss_tiktok_location_popup = lambda _device_id: False
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller._get_tiktok_search_icon_coords = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id: "com.ss.android.ugc.aweme.splash.SplashActivity"
        )
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        taps = []
        keyevents = []
        commands = []
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )
        self.controller.keyevent = (
            lambda _device_id, keycode: keyevents.append(keycode)
            or (0, "", "")
        )

        def execute(_device_id, args, timeout=15):
            commands.append(args)
            return 0, "Broadcast completed: result=0", ""

        self.controller.execute_adb = execute
        keyword = "nặn mụn Phan Thiết"

        self.assertTrue(
            self.controller.find_and_click_tiktok_search("device-generic-search")
        )
        self.assertTrue(
            self.controller.replace_tiktok_search_text(
                "device-generic-search", keyword
            )
        )
        self.assertTrue(
            self.controller.submit_tiktok_search("device-generic-search")
        )
        self.controller.is_tiktok_search_results_for = (
            lambda _device_id, value: value == keyword
        )
        self.assertTrue(
            self.controller.wait_for_tiktok_search_results(
                "device-generic-search", keyword
            )
        )

        self.assertNotIn(4, keyevents)
        self.assertEqual([66], keyevents)
        self.assertIn((486, 105), taps)
        clear_commands = [args for args in commands if "XW_CLEAR_TEXT" in args]
        input_commands = [args for args in commands if "XW_INPUT_B64" in args]
        self.assertEqual(1, len(clear_commands))
        self.assertEqual(1, len(input_commands))
        encoded = input_commands[0][input_commands[0].index("msg") + 1]
        self.assertEqual(keyword, base64.b64decode(encoded).decode("utf-8"))

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_recovery_stops_after_one_back_if_activity_stays_search(
        self, _sleep
    ):
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id:
            "com.ss.android.ugc.aweme.search.SearchResultActivity"
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        self.controller.focus_tiktok_search_input = lambda _device_id: False
        keys = []
        taps = []
        self.controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertFalse(
            self.controller.find_and_click_tiktok_search("device-search-stuck")
        )
        self.assertEqual([4], keys)
        self.assertEqual([], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_focus_search_requires_verified_input_after_fallback(self, _sleep):
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = lambda _device_id: None
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertFalse(
            self.controller.focus_tiktok_search_input("device-no-input")
        )
        self.assertGreaterEqual(len(taps), 1)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_focus_search_accepts_verified_search_activity_when_xml_is_busy(
        self, _sleep
    ):
        state_checks = []
        self.controller.get_tiktok_search_input_state = lambda device_id: (
            state_checks.append(device_id) or None
        )
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id:
            "com.ss.android.ugc.aweme.search.SearchResultActivity"
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.focus_tiktok_search_input("device-busy-xml")
        )
        self.assertEqual(["device-busy-xml"], state_checks)
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

    def test_seed_results_accept_compact_layout_with_one_tab_and_result_card(self):
        compact_root = ET.fromstring(
            '<hierarchy>'
            '<node class="android.widget.EditText" text="nặn mụn" '
            'resource-id="com.ss.android.ugc.trill:id/search_edit_text" />'
            '<node text="Top" />'
            '<node clickable="true" bounds="[20,260][1060,900]">'
            '<node text="Cách chăm sóc da mụn hiệu quả" />'
            '</node>'
            '</hierarchy>'
        )
        self.controller._get_tiktok_ui_root = (
            lambda _device_id, _prefix: compact_root
        )

        self.assertTrue(
            self.controller.is_tiktok_search_results_for(
                "device-compact", "nặn mụn"
            )
        )

    def test_seed_results_accept_query_textview_in_top_search_bar(self):
        """TikTok mới có thể xuất query thành TextView thay vì EditText."""
        textview_root = ET.fromstring(
            '<hierarchy>'
            '<node class="android.widget.TextView" text="nặn mụn Phan Thiết" '
            'clickable="true" bounds="[92,48][910,164]" />'
            '<node text="Top" bounds="[130,170][280,245]" />'
            '<node text="Videos" bounds="[300,170][470,245]" />'
            '<node clickable="true" bounds="[20,260][1060,900]">'
            '<node text="Kết quả chăm sóc da tại Phan Thiết" />'
            '</node>'
            '</hierarchy>'
        )
        self.controller._get_tiktok_ui_root = (
            lambda _device_id, _prefix: textview_root
        )

        self.assertTrue(
            self.controller.is_tiktok_search_results_for(
                "device-textview", "nặn mụn Phan Thiết"
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

        self.assertFalse(self.controller.advance_tiktok_feed("device-wrong-app"))
        self.assertEqual([], swipes)

    @patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MIN", 16)
    @patch("adb_controller.config.SOCIAL_CROSS_WARMUP_MAX", 16)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    def test_tiktok_warmup_stops_if_foreground_changes_before_swipe(
        self, _sleep, _randint
    ):
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.ensure_tiktok_foreground_ready = (
            lambda *_args, **_kwargs: False
        )
        self.controller.lock_portrait = lambda *_args, **_kwargs: True
        advances = []
        self.controller.advance_tiktok_feed = (
            lambda device_id: advances.append(device_id) or True
        )

        with self.assertRaisesRegex(RuntimeError, "TikTok.*phục hồi"):
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

    def test_feed_motion_swipes_immediately_after_home_is_ready(self):
        events = []
        self.controller.ensure_tiktok_foreground_ready = (
            lambda *_args, **_kwargs: events.append("ready") or True
        )
        self.controller.advance_tiktok_feed = (
            lambda _device_id: events.append("swipe") or True
        )
        self.controller.keyevent = (
            lambda *_args: events.append("back")
        )
        self.controller.launch_tiktok = (
            lambda _device_id: events.append("launch")
        )

        self.assertTrue(
            self.controller.ensure_tiktok_feed_motion("device-s4")
        )
        self.assertEqual(["ready", "swipe"], events)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_stalled_tiktok_feed_backs_reopens_and_swipes_again(self, _sleep):
        events = []
        moves = iter([False, True])
        self.controller.ensure_tiktok_foreground_ready = (
            lambda *_args, **_kwargs: events.append("ready") or True
        )
        self.controller.advance_tiktok_feed = (
            lambda _device_id:
            events.append("swipe") or next(moves)
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.keyevent = (
            lambda _device_id, keycode:
            events.append("back") if keycode == 4 else None
        )
        self.controller.launch_tiktok = (
            lambda _device_id: events.append("launch")
        )
        self.controller.lock_portrait = lambda *_args, **_kwargs: True

        self.assertTrue(
            self.controller.ensure_tiktok_feed_motion("device-s4")
        )
        self.assertEqual(
            ["ready", "swipe", "back", "launch", "ready", "swipe"],
            events,
        )

    @patch("builtins.print")
    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    def test_workflow_starts_feed_motion_before_first_dwell(
        self, _randint, _uniform, _print
    ):
        events = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = (
            lambda *_args, **_kwargs: True
        )
        self.controller.launch_tiktok = (
            lambda _device_id: events.append("launch")
        )
        self.controller.ensure_tiktok_feed_motion = (
            lambda *_args, **_kwargs: events.append("motion") or True
        )
        self.controller.ensure_tiktok_foreground_ready = (
            lambda *_args, **_kwargs: True
        )
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = lambda *_args: True
        self.controller.submit_tiktok_search = lambda _device_id: True
        self.controller.wait_for_tiktok_search_results = lambda *_args: True
        self.controller.find_and_click_tiktok_channel = lambda *_args: True
        self.controller.click_random_tiktok_profile_video = lambda *_args: True
        self.controller.swipe = lambda *_args, **_kwargs: None

        with patch(
            "adb_controller.time.sleep",
            side_effect=lambda _seconds: events.append("dwell"),
        ):
            success, message = self.controller.tiktok_automation_workflow(
                "device-s4",
                seed_keywords=["nặn mụn"],
                target_channel="Kênh TikTok Mẫu",
            )

        self.assertTrue(success, message)
        self.assertLess(events.index("motion"), events.index("dwell"))

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

    @patch("adb_controller.time.sleep", return_value=None)
    def test_replace_search_continues_when_search_activity_is_ready_but_xml_busy(
        self, _sleep
    ):
        events = []
        self.controller.clear_tiktok_search_input = lambda _device_id: (
            events.append("clear") or True
        )
        self.controller.input_tiktok_search_text = lambda _device_id, text: (
            events.append(("input", text)) or True
        )
        self.controller.get_tiktok_search_input_state = lambda _device_id: None
        self.controller.get_tiktok_foreground_activity = (
            lambda _device_id:
            "com.ss.android.ugc.aweme.search.SearchResultActivity"
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True

        self.assertTrue(
            self.controller.replace_tiktok_search_text(
                "device-busy-xml", "nặn mụn"
            )
        )
        self.assertEqual(["clear", ("input", "nặn mụn")], events)

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
        self.controller._get_tiktok_ui_root = (
            lambda *_args: next(roots, profile_root)
        )
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
        self.controller._get_tiktok_ui_root = (
            lambda *_args: next(roots, profile_root)
        )
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-1", "Target Channel"
            )
        )
        self.assertEqual([(540, 390)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_click_rejects_other_channel_video_caption(self, _sleep):
        wrong_video_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.RelativeLayout" clickable="true"
                    bounds="[0,325][1080,920]" resource-id="video_card">
                <node class="android.widget.TextView" clickable="false"
                      bounds="[40,700][1020,790]"
                      resource-id="com.ss.android.ugc.trill:id/caption"
                      text="Review Kênh TikTok Mẫu hôm nay" />
                <node class="android.widget.TextView" clickable="false"
                      bounds="[40,800][500,850]"
                      resource-id="com.ss.android.ugc.trill:id/tv_username"
                      text="Kênh Khác" />
              </node>
            </hierarchy>
            """
        )
        self.controller._get_tiktok_ui_root = (
            lambda *_args: wrong_video_root
        )
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertFalse(
            self.controller.find_and_click_tiktok_channel(
                "device-wrong-card", "Kênh TikTok Mẫu"
            )
        )
        self.assertEqual(
            [],
            taps,
            "Caption nhắc tên target không được coi là card danh tính kênh",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_click_accepts_combined_user_accessibility_label(self, _sleep):
        """Một số TikTok gộp tên, handle và Follow vào content-desc."""
        search_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Users"
                    bounds="[20,190][200,250]" />
              <node class="android.widget.FrameLayout" clickable="true"
                    bounds="[0,260][1080,560]" resource-id="id/obfuscated_row">
                <node class="android.widget.ImageView"
                      resource-id="id/obfuscated_avatar"
                      bounds="[30,300][190,460]" />
                <node class="android.widget.TextView"
                      resource-id="id/obfuscated_name"
                      content-desc="Kênh TikTok Mẫu, @kenhmau, Follow"
                      bounds="[220,310][790,390]" />
                <node class="android.widget.Button" text="Follow"
                      bounds="[820,320][1040,430]" />
              </node>
            </hierarchy>
            """
        )
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Kênh TikTok Mẫu" />
              <node class="android.widget.Button" text="Follow" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
            </hierarchy>
            """
        )
        roots = iter([search_root, profile_root])
        self.controller._get_tiktok_ui_root = (
            lambda *_args: next(roots, profile_root)
        )
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-combined-label", "Kênh TikTok Mẫu"
            )
        )
        self.assertEqual([(540, 410)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_click_accepts_profile_already_open_after_previous_tap(
        self, _sleep
    ):
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Kênh TikTok Mẫu" />
              <node class="android.widget.Button" text="Follow" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
            </hierarchy>
            """
        )
        self.controller._get_tiktok_ui_root = lambda *_args: profile_root
        taps = []
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-profile-open", "Kênh TikTok Mẫu"
            )
        )
        self.assertEqual([], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_search_scrolls_past_products_to_target_user(self, _sleep):
        products_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Top" />
              <node class="android.widget.TextView" text="Mua sắm" />
              <node class="android.widget.FrameLayout" clickable="true"
                    bounds="[0,260][1080,1680]" resource-id="shop_products">
                <node text="Kem dưỡng da" />
                <node text="551.325đ" />
              </node>
            </hierarchy>
            """
        )
        user_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Người dùng" />
              <node class="android.widget.FrameLayout" clickable="true"
                    bounds="[0,980][1080,1280]" resource-id="user_result">
                <node class="android.widget.TextView"
                      text="Kênh TikTok Mẫu" bounds="[220,1020][760,1090]" />
                <node class="android.widget.Button" text="Đã follow" />
              </node>
            </hierarchy>
            """
        )
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Kênh TikTok Mẫu" />
              <node class="android.widget.Button" text="Đã follow" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
            </hierarchy>
            """
        )
        state = {"scrolled": False, "tapped": False}

        def get_root(*_args):
            if state["tapped"]:
                return profile_root
            return user_root if state["scrolled"] else products_root

        swipes = []
        taps = []
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        self.controller._get_tiktok_ui_root = get_root
        self.controller.swipe = (
            lambda *_args, **_kwargs:
            swipes.append("scroll-results")
            or state.update(scrolled=True)
        )
        self.controller.tap = (
            lambda _device_id, x, y:
            taps.append((x, y)) or state.update(tapped=True)
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-products-first", "Kênh TikTok Mẫu"
            )
        )
        self.assertGreaterEqual(len(swipes), 1)
        self.assertEqual([(540, 1130)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_click_uses_identity_row_when_clickable_parent_is_whole_results(
        self, _sleep
    ):
        """TikTok có thể gắn clickable cho cả khối Users + Shopping."""
        search_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Users"
                    bounds="[20,190][200,250]" />
              <node class="android.widget.FrameLayout" clickable="true"
                    resource-id="id/search_content_container"
                    bounds="[0,250][1080,1920]">
                <node class="android.widget.ImageView"
                      resource-id="id/avatar_obfuscated"
                      bounds="[30,280][170,420]" />
                <node class="android.widget.TextView" clickable="false"
                      resource-id="id/text_obfuscated"
                      text="Khải Hoàn Skincare PT"
                      bounds="[190,290][650,370]" />
                <node class="android.widget.Button" text="Follow"
                      bounds="[820,290][1040,400]" />
                <node class="android.widget.GridView"
                      resource-id="id/shopping_results"
                      bounds="[0,440][1080,1920]" />
              </node>
            </hierarchy>
            """
        )
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView"
                    text="Khải Hoàn Skincare PT" />
              <node class="android.widget.Button" text="Đã follow" />
              <node class="android.widget.TextView" text="Shop" />
              <node class="android.widget.GridView"
                    bounds="[0,780][1080,1920]">
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[0,780][358,1260]" />
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[361,780][718,1260]" />
              </node>
            </hierarchy>
            """
        )
        state = {"tapped": False}
        taps = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller._get_tiktok_ui_root = (
            lambda *_args: profile_root if state["tapped"] else search_root
        )
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.tap = (
            lambda _device_id, x, y:
            taps.append((x, y)) or state.update(tapped=True)
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-wide-click-parent", "Khai Hoan Skincare PT"
            )
        )
        self.assertEqual(
            [(420, 330)],
            taps,
            "Phải tap trực tiếp tên kênh, không tap giữa khối sản phẩm",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_click_uses_follow_row_when_identity_has_no_bounds(
        self, _sleep
    ):
        """Tên kênh có content-desc nhưng TikTok không cấp bounds riêng."""
        search_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Users"
                    bounds="[20,190][200,250]" />
              <node class="android.widget.FrameLayout" clickable="true"
                    resource-id="id/search_content_container"
                    bounds="[0,250][1080,1920]">
                <node class="android.view.View"
                      content-desc="Khải Hoàn Skincare PT, @khaihoan, Following" />
                <node class="android.widget.Button" text="Following"
                      bounds="[820,290][1040,400]" />
                <node class="android.widget.GridView"
                      resource-id="id/shopping_results"
                      bounds="[0,440][1080,1920]" />
              </node>
            </hierarchy>
            """
        )
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView"
                    text="Khải Hoàn Skincare PT" />
              <node class="android.widget.Button" text="Đã follow" />
              <node class="android.widget.GridView"
                    bounds="[0,780][1080,1920]">
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[0,780][358,1260]" />
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[361,780][718,1260]" />
              </node>
            </hierarchy>
            """
        )
        state = {"tapped": False}
        taps = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller._get_tiktok_ui_root = (
            lambda *_args: profile_root if state["tapped"] else search_root
        )
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.swipe = lambda *_args, **_kwargs: None
        self.controller.tap = (
            lambda _device_id, x, y:
            taps.append((x, y)) or state.update(tapped=True)
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-no-identity-bounds", "Khai Hoan Skincare PT"
            )
        )
        self.assertEqual(
            [(410, 345)],
            taps,
            "Phải suy ra vị trí tên kênh từ nút Following cùng hàng",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_clicks_fixed_top_name_area_when_ui_dump_is_unavailable(
        self, _sleep
    ):
        """Ảnh vẫn thấy card target dù UIAutomator không trả XML."""
        taps = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-ui-dump-busy", "Khai Hoan Skincare"
            )
        )
        self.assertEqual(
            [(410, 499)],
            taps,
            "Khi XML bận phải tap thẳng vùng tên kênh trên kết quả Top",
        )

    @patch("adb_controller.random.choice", side_effect=lambda values: values[0])
    @patch("adb_controller.time.sleep", return_value=None)
    def test_trusted_direct_channel_tap_opens_clip_without_profile_xml(
        self, _sleep, _choice
    ):
        """Sau tap trực tiếp kênh, XML tiếp tục bận vẫn phải bấm clip."""
        taps = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.is_tiktok_video_player = lambda _device_id: True
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-ui-dump-busy", "Khai Hoan Skincare"
            )
        )
        self.assertTrue(
            self.controller.click_random_tiktok_profile_video(
                "device-ui-dump-busy", "Khai Hoan Skincare"
            )
        )
        self.assertEqual(
            [(410, 499), (194, 1305)],
            taps,
            "Phải tap vùng tên kênh rồi tap trực tiếp clip trong lưới",
        )

    @patch("adb_controller.random.choice", side_effect=lambda values: values[0])
    @patch("adb_controller.time.sleep", return_value=None)
    def test_profile_clip_fallback_rejects_foreground_without_video_player(
        self, _sleep, _choice
    ):
        """Menu Latest/Popular không được coi là đã mở video."""
        taps = []
        swipes = []
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller._get_tiktok_ui_root = lambda *_args: None
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.is_tiktok_video_player = lambda _device_id: False
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )
        self.controller.swipe = (
            lambda *_args, **_kwargs: swipes.append("reveal-grid")
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-menu-not-player", "Khai Hoan Skincare"
            )
        )
        self.assertFalse(
            self.controller.click_random_tiktok_profile_video(
                "device-menu-not-player", "Khai Hoan Skincare"
            )
        )
        self.assertEqual((410, 499), taps[0])
        self.assertTrue(
            all(y >= int(1920 * 0.60) for _, y in taps[1:]),
            "Fallback clip không được tap vùng sort/header phía trên",
        )
        self.assertGreaterEqual(len(swipes), 1)

    def test_profile_verifier_rejects_target_mentioned_only_in_bio(self):
        wrong_profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Kênh Khác" />
              <node class="android.widget.TextView"
                    text="Chuyên review Kênh TikTok Mẫu" />
              <node class="android.widget.Button" text="Follow" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
              <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
            </hierarchy>
            """
        )

        self.assertFalse(
            self.controller.is_on_tiktok_target_profile(
                "device-wrong-profile",
                "Kênh TikTok Mẫu",
                root=wrong_profile_root,
            )
        )

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

    def test_profile_verifier_accepts_business_profile_with_shop_tab(self):
        """Tab Shop trên profile doanh nghiệp không phải trang Search results."""
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView"
                    text="Khải Hoàn Skincare PT" />
              <node class="android.widget.Button" text="Đã follow" />
              <node class="android.widget.TextView" text="Shop" />
              <node class="android.widget.GridView"
                    resource-id="com.ss.android.ugc.trill:id/hui"
                    bounds="[0,780][1080,1920]">
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[0,780][358,1260]" />
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[361,780][718,1260]" />
              </node>
            </hierarchy>
            """
        )

        self.assertTrue(
            self.controller.is_on_tiktok_target_profile(
                "device-business-profile",
                "Khai Hoan Skincare",
                root=profile_root,
            )
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_business_profile_with_shop_tab_opens_a_clip(self, _sleep):
        """Khi profile đã hiện lưới clip thì phải bấm clip, không báo sai B3."""
        profile_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView"
                    text="Khải Hoàn Skincare PT" />
              <node class="android.widget.Button" text="Đã follow" />
              <node class="android.widget.TextView" text="Shop" />
              <node class="android.widget.GridView"
                    resource-id="com.ss.android.ugc.trill:id/hui"
                    bounds="[0,780][1080,1920]">
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="com.ss.android.ugc.trill:id/erf"
                      bounds="[0,780][358,1260]" />
              </node>
            </hierarchy>
            """
        )
        self.controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        self.controller._get_tiktok_ui_root = lambda *_args: profile_root
        self.controller.is_tiktok_video_player = lambda _device_id: True
        taps = []
        self.controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )

        self.assertTrue(
            self.controller.find_and_click_tiktok_channel(
                "device-business-profile", "Khai Hoan Skincare"
            )
        )
        self.assertTrue(
            self.controller.click_random_tiktok_profile_video(
                "device-business-profile", "Khai Hoan Skincare"
            )
        )
        self.assertEqual([(179, 1020)], taps)

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
    def test_profile_video_click_scrolls_until_grid_is_visible(self, _sleep):
        tall_header_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.TextView" text="Kênh TikTok Mẫu" />
              <node class="android.widget.Button" text="Follow" />
              <node class="android.widget.TextView"
                    text="Tiểu sử dài đang che phần lưới clip" />
            </hierarchy>
            """
        )
        grid_root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.GridView" bounds="[0,520][1080,1920]">
                <node class="android.widget.FrameLayout" clickable="true"
                      resource-id="id/obfuscated_video_tile"
                      bounds="[0,560][358,1080]">
                  <node class="android.widget.ImageView"
                        resource-id="id/cover" bounds="[0,560][358,1080]" />
                </node>
              </node>
            </hierarchy>
            """
        )
        state = {"scrolled": False}
        swipes = []
        taps = []
        self.controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        self.controller._get_tiktok_ui_root = (
            lambda *_args: grid_root if state["scrolled"] else tall_header_root
        )
        self.controller.swipe = (
            lambda *_args, **_kwargs:
            swipes.append("scroll-profile")
            or state.update(scrolled=True)
        )
        self.controller.tap = lambda _device_id, x, y: taps.append((x, y))
        self.controller.is_tiktok_video_player = lambda _device_id: True

        self.assertTrue(
            self.controller.click_random_tiktok_profile_video(
                "device-tall-profile", "Kênh TikTok Mẫu"
            )
        )
        self.assertGreaterEqual(len(swipes), 1)
        self.assertEqual([(179, 820)], taps)

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
    def test_cross_warmup_starts_feed_motion_immediately(
        self, _randint
    ):
        events = []
        self.controller.launch_tiktok = (
            lambda _device_id: events.append("launch")
        )
        self.controller.is_tiktok_in_foreground = lambda _device_id: True
        self.controller.lock_portrait = lambda _device_id, retries=2: True
        self.controller.ensure_tiktok_feed_motion = (
            lambda _device_id, **_kwargs:
            events.append("motion") or True
        )

        clock = [0.0]
        with (
            patch(
                "adb_controller.time.sleep",
                side_effect=lambda seconds: clock.__setitem__(
                    0, clock[0] + float(seconds)
                ),
            ),
            patch("adb_controller.time.monotonic", side_effect=lambda: clock[0]),
        ):
            self.assertTrue(
                self.controller.warmup_tiktok_before_facebook("device-1")
            )
        self.assertEqual(["launch", "motion"], events[:2])

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
        workflow_events = []
        current_keyword = {"value": ""}
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
        def replace_text(_device_id, text):
            current_keyword["value"] = text
            entered_keywords.append(text)
            workflow_events.append(f"input:{text}")
            return True

        self.controller.replace_tiktok_search_text = replace_text
        self.controller.submit_tiktok_search = (
            lambda _device_id:
            workflow_events.append(
                f"submit:{current_keyword['value']}"
            ) or True
        )
        self.controller.wait_for_tiktok_search_results = lambda *_args: True
        self.controller.tap = lambda _device_id, x, y: taps_after_search.append((x, y))
        self.controller.find_and_click_tiktok_channel = (
            lambda _device_id, channel:
            workflow_events.append(f"channel:{channel}") or True
        )
        self.controller.click_random_tiktok_profile_video = (
            lambda _device_id, channel:
            workflow_events.append(f"clip:{channel}") or True
        )

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
            [
                "input:nặn mụn",
                "submit:nặn mụn",
                "input:Kênh TikTok Mẫu",
                "submit:Kênh TikTok Mẫu",
                "channel:Kênh TikTok Mẫu",
                "clip:Kênh TikTok Mẫu",
            ],
            workflow_events,
            "B2 chỉ lướt kết quả; chỉ B3 mới được mở clip sau khi vào đúng kênh",
        )
        search_input_taps = [
            (x, y) for x, y in taps_after_search
            if y < int(1920 * 0.20)
        ]
        if search_input_taps:
            self.assertTrue(
                all(x < 850 for x, _y in search_input_taps),
                "B3 chỉ được tap thanh query bên trái, không tap nút ba chấm/Filters",
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
    def test_workflow_does_not_retype_seed_when_result_xml_is_unreadable(
        self, _sleep, _randint, _print
    ):
        entered = []
        result_detector_calls = []
        statuses = []
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
        self.controller.submit_tiktok_search = lambda _device_id: True
        self.controller.wait_for_tiktok_search_results = (
            lambda *_args:
            result_detector_calls.append("xml-check") or False
        )
        self.controller.find_and_click_tiktok_channel = lambda *_args: True
        self.controller.click_random_tiktok_profile_video = lambda *_args: True

        success, message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["từ khóa mồi"],
            target_channel="Kênh mục tiêu",
            status_callback=lambda _device_id, status: statuses.append(status),
        )

        self.assertTrue(success, message)
        self.assertEqual(["từ khóa mồi", "Kênh mục tiêu"], entered)
        self.assertEqual(
            [],
            result_detector_calls,
            "B2 không được chờ UI XML sau khi Enter đã thành công",
        )
        self.assertFalse(any("tải chậm" in status for status in statuses))
        self.assertTrue(
            any("không nhập lại" in status for status in statuses)
        )

    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    @patch("builtins.print")
    def test_workflow_enters_seed_exactly_once_before_exact_target(
        self, _print, _sleep, _randint
    ):
        entered = []
        submitted = []
        self.controller.get_screen_size = lambda _device_id: (1080, 1920)
        self.controller.warmup_facebook_before_tiktok = lambda *_args, **_kwargs: True
        self.controller.launch_tiktok = lambda _device_id: None
        self.controller.ensure_tiktok_foreground_ready = lambda *_args, **_kwargs: True
        self.controller.wait_for_tiktok_foreground = lambda _device_id: True
        self.controller.advance_tiktok_feed = lambda _device_id: True
        self.controller.find_and_click_tiktok_search = lambda _device_id: True
        self.controller.replace_tiktok_search_text = (
            lambda _device_id, text: entered.append(text) or True
        )
        self.controller.submit_tiktok_search = (
            lambda _device_id: submitted.append(entered[-1]) or True
        )
        self.controller.find_and_click_tiktok_channel = lambda *_args: True
        self.controller.click_random_tiktok_profile_video = lambda *_args: True
        self.controller.swipe = lambda *_args, **_kwargs: None

        success, message = self.controller.tiktok_automation_workflow(
            "device-delayed-results",
            seed_keywords=["từ khóa mồi"],
            target_channel="Kênh mục tiêu",
        )

        self.assertTrue(success, message)
        self.assertEqual(
            ["từ khóa mồi", "Kênh mục tiêu"],
            entered,
        )
        self.assertEqual(
            ["từ khóa mồi", "Kênh mục tiêu"],
            submitted,
            "Mỗi lớp từ khóa chỉ được nhập và Enter đúng một lần",
        )

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
        opened_clips = []
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
        self.controller.click_random_tiktok_profile_video = (
            lambda *_args: opened_clips.append("clip") or True
        )

        success, message = self.controller.tiktok_automation_workflow(
            "device-1",
            seed_keywords=["nặn mụn"],
            target_channel="Kênh TikTok Mẫu",
        )

        self.assertFalse(success)
        self.assertIn("không mở được kênh", message.lower())
        self.assertEqual(
            [],
            opened_clips,
            "Không được mở clip khi chưa xác minh đã vào đúng kênh target",
        )


if __name__ == "__main__":
    unittest.main()
