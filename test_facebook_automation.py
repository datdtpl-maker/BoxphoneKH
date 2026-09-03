import unittest
import xml.etree.ElementTree as ET
import base64
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from adb_controller import ADBController


class FacebookAutomationTests(unittest.TestCase):
    def test_target_phrase_resolves_to_full_canonical_page_name(self):
        controller = ADBController(adb_path="adb")
        canonical_name = (
            "Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa "
            "Phan Thiết"
        )

        with (
            patch(
                "adb_controller.config.FACEBOOK_TARGET_PAGE_EXACT_DEFAULT",
                "Khải Hoàn Skincare",
            ),
            patch(
                "adb_controller.config.FACEBOOK_CANONICAL_PAGE_NAME",
                canonical_name,
            ),
        ):
            resolved = controller._resolve_facebook_exact_page_name(
                "Khải Hoàn Skincare"
            )

        self.assertEqual(canonical_name, resolved)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_partial_home_dump_is_retried_before_search_fallback(self, _sleep):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: True
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._get_facebook_header_search_coords = lambda _device_id: None
        home_states = iter([False, None])
        controller.is_facebook_home = lambda _device_id: next(home_states)
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
            or (0, "", "")
        )

        self.assertTrue(
            controller.find_and_click_facebook_search("device-partial-dump")
        )
        self.assertEqual([(896, 105)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_foreground_home_unknown_still_uses_safe_search_icon_fallback(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: True
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._get_facebook_header_search_coords = lambda _device_id: None
        controller.is_facebook_home = lambda _device_id: None
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
            or (0, "", "")
        )

        self.assertTrue(
            controller.find_and_click_facebook_search("device-home-unknown")
        )
        self.assertEqual([(896, 105)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_forty_devices_accept_visible_search_during_parallel_xml_busy(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: True
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._get_facebook_header_search_coords = lambda _device_id: None
        controller.is_facebook_home = lambda _device_id: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        controller.tap = (
            lambda device_id, x, y: taps.append((device_id, x, y))
            or (0, "", "")
        )
        devices = [f"device-{index}" for index in range(1, 41)]

        with ThreadPoolExecutor(max_workers=40) as executor:
            results = list(
                executor.map(controller.find_and_click_facebook_search, devices)
            )

        self.assertTrue(all(results))
        self.assertEqual(40, len(taps))
        self.assertTrue(all((x, y) == (896, 105) for _, x, y in taps))

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_vietnamese_wide_search_field_is_detected_but_header_icon_is_not(
        self, _exists, _remove
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.view.View"
                    content-desc="Tìm kiếm"
                    bounds="[890,55][980,145]" />
              <node class="android.view.View"
                    content-desc="Tìm kiếm trên Facebook"
                    clickable="true"
                    bounds="[110,55][850,145]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            state = controller._get_facebook_search_input_state(
                "device-vietnamese-search"
            )

        self.assertIsNotNone(state)
        self.assertEqual((480, 100), state["coords"])

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_recent_search_uses_wide_clickable_ancestor_of_placeholder(
        self, _exists, _remove
    ):
        """Màn Mới đây đặt chữ Tìm kiếm trong một container rộng riêng."""
        root = ET.fromstring(
            """
            <hierarchy>
              <node package="com.facebook.katana"
                    class="android.view.ViewGroup"
                    clickable="true"
                    bounds="[105,55][990,170]">
                <node package="com.facebook.katana"
                      class="android.widget.TextView"
                      text="Tìm kiếm"
                      bounds="[420,80][585,145]" />
              </node>
              <node package="com.facebook.katana"
                    text="Mới đây"
                    bounds="[25,205][300,275]" />
              <node package="com.facebook.katana"
                    text="Xem tất cả"
                    bounds="[820,205][1040,275]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            coords = controller._get_facebook_header_search_coords(
                "device-recent"
            )

        self.assertEqual((547, 112), coords)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_accepts_xml_verified_recent_field_during_focus_gap(
        self, _sleep
    ):
        """Tap đúng ô Mới đây không được báo lỗi vì dumpsys trống một nhịp."""
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        foreground_states = iter([True, True, False, False])
        controller.wait_for_facebook_foreground = (
            lambda *_args, **_kwargs: next(foreground_states, False)
        )
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._get_facebook_header_search_coords = (
            lambda _device_id: (547, 112)
        )
        controller.is_facebook_home = lambda _device_id: False
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        backs = []
        controller.tap = (
            lambda _device_id, x, y: taps.append((x, y)) or (0, "", "")
        )
        controller.keyevent = (
            lambda _device_id, key: backs.append(key) or (0, "", "")
        )

        self.assertTrue(
            controller.find_and_click_facebook_search("device-focus-gap")
        )
        self.assertEqual([(547, 112)], taps)
        self.assertEqual([], backs)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_target_search_uses_recent_field_when_all_foreground_probes_are_busy(
        self, _sleep
    ):
        """B3 đã xác nhận Facebook nên dumpsys nghẽn không được chặn ô Search."""
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: False
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._get_facebook_header_search_coords = lambda _device_id: None
        controller.is_facebook_home = lambda _device_id: False
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        taps = []
        controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
            or (0, "", "")
        )

        self.assertTrue(
            controller.find_and_click_facebook_search(
                "device-b3-busy", allow_recent_fallback=True
            )
        )
        self.assertEqual([(486, 105)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_visible_home_search_tap_is_accepted_when_ui_dump_stays_busy(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: True
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._get_facebook_header_search_coords = lambda _device_id: None
        controller.is_facebook_home = lambda _device_id: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        events = []
        controller.tap = (
            lambda _device_id, x, y: events.append(("tap", x, y))
            or (0, "", "")
        )
        controller.keyevent = (
            lambda _device_id, key: events.append(("back", key))
            or (0, "", "")
        )

        self.assertTrue(
            controller.find_and_click_facebook_search("device-ui-busy")
        )
        self.assertEqual([("tap", 896, 105)], events)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_return_home_before_seed_search_backs_once_and_verifies_home(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        events = []
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: True
        controller.keyevent = (
            lambda _device_id, key: events.append(("back", key))
            or (0, "", "")
        )
        controller.is_facebook_home = (
            lambda _device_id: events.append(("verify_home",)) or True
        )

        self.assertTrue(
            controller.return_facebook_home_before_search("device-home")
        )
        self.assertEqual([("back", 4), ("verify_home",)], events)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_home_header_reveal_never_backs_out_of_ready_feed(self, _sleep):
        controller = ADBController(adb_path="adb")
        events = []
        home_states = iter([True, True])
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: next(home_states)
        controller.keyevent = lambda _device_id, key: events.append(("back", key))
        controller.launch_app = (
            lambda _device_id, package: events.append(("launch", package))
        )
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.swipe = lambda *_args, **_kwargs: (
            events.append(("swipe", _args[2], _args[4])) or (0, "", "")
        )

        self.assertTrue(controller.reveal_facebook_header("device-s5"))

        self.assertEqual(1, len(events))
        self.assertEqual("swipe", events[0][0])
        self.assertLess(events[0][1], events[0][2])

    def test_home_refresh_is_ignored_outside_facebook_home(self):
        controller = ADBController(adb_path="adb")
        events = []
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: False
        controller.keyevent = lambda *_args: events.append(("back",))
        controller.launch_app = lambda *_args: events.append(("launch",))
        controller.swipe = lambda *_args, **_kwargs: events.append(("swipe",))

        self.assertFalse(controller.reveal_facebook_header("device-page"))
        self.assertEqual([], events)

    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    def test_cross_warmup_swipes_immediately_when_ui_dump_is_busy(
        self, _randint
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: True
        events = []
        controller.swipe = (
            lambda *_args, **_kwargs:
            events.append("swipe") or (0, "", "")
        )
        controller.get_facebook_feed_signature = lambda _device_id: None
        controller.reveal_facebook_header = (
            lambda _device_id: events.append("reopen") or True
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
                controller.browse_facebook_surface(
                    "device-blank", 1, "facebook_cross_warmup"
                )
            )

        self.assertEqual(["swipe"], events)

    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    def test_facebook_main_feed_never_backs_when_adb_swipe_was_accepted(
        self, _randint
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: True
        events = []
        controller.swipe = (
            lambda *_args, **_kwargs:
            events.append("swipe") or (0, "", "")
        )
        signatures = iter([("same",), ("same",), ("fresh",), ("moved",)])
        controller.get_facebook_feed_signature = (
            lambda _device_id: next(signatures)
        )
        controller.reveal_facebook_header = (
            lambda _device_id: events.append("reopen") or True
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
                controller.browse_facebook_surface(
                    "device-stalled", 3, "feed"
                )
            )

        self.assertEqual(["swipe"], events)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_ensure_home_retries_transient_unknown_without_back(self, _sleep):
        controller = ADBController(adb_path="adb")
        home_states = iter([None, True])
        events = []
        controller.is_facebook_home = lambda _device_id: next(home_states)
        controller.keyevent = (
            lambda _device_id, key: events.append(("back", key))
        )
        controller.execute_adb = (
            lambda _device_id, args, timeout=15:
            events.append(("adb", tuple(args))) or (0, "", "")
        )
        controller.lock_portrait = lambda *_args, **_kwargs: True

        self.assertTrue(controller.ensure_facebook_home("device-busy-dump"))
        self.assertFalse(any(event[0] == "back" for event in events))
        self.assertFalse(
            any("fb://feed" in event[1] for event in events if event[0] == "adb")
        )

    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    def test_cross_warmup_recovers_facebook_foreground_before_swipe(
        self, _randint
    ):
        controller = ADBController(adb_path="adb")
        swipes = []
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        foreground = iter([False, True, True, True])
        controller.is_facebook_in_foreground = lambda _device_id: next(
            foreground, True
        )
        recoveries = []
        controller.ensure_facebook_ready = lambda device_id: (
            recoveries.append(device_id) or True
        )
        controller.swipe = lambda *_args, **_kwargs: swipes.append(_args)
        signatures = iter([("feed-a",), ("feed-b",), ("feed-b",)])
        controller.get_facebook_feed_signature = (
            lambda _device_id: next(signatures)
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
                controller.browse_facebook_surface(
                    "device-transition", 7, "facebook_cross_warmup"
                )
            )

        self.assertEqual(["device-transition"], recoveries)
        self.assertEqual(1, len(swipes))

    @patch("adb_controller.time.sleep", return_value=None)
    def test_cross_warmup_still_never_swipes_if_facebook_cannot_recover(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        swipes = []
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.is_facebook_in_foreground = lambda _device_id: False
        controller.ensure_facebook_ready = lambda _device_id: False
        controller.swipe = lambda *_args, **_kwargs: swipes.append(_args)

        with self.assertRaisesRegex(RuntimeError, "Facebook.*foreground"):
            controller.browse_facebook_surface(
                "device-on-other-app", 20, "facebook_cross_warmup"
            )

        self.assertEqual([], swipes)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_facebook_keyword_is_never_sent_while_tiktok_is_foreground(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        broadcasts = []
        controller.is_facebook_in_foreground = lambda _device_id: False
        controller.ensure_ime = lambda _device_id: None
        controller._focus_facebook_search_input = lambda _device_id: True
        controller._get_facebook_search_input_state = lambda _device_id: {
            "text": "facebook seed",
            "focused": True,
            "coords": (430, 90),
        }

        def execute(_device_id, args, timeout=15):
            if "XW_CLEAR_TEXT" in args or "XW_INPUT_B64" in args:
                broadcasts.append(args)
            return 0, "", ""

        controller.execute_adb = execute

        with self.assertRaisesRegex(RuntimeError, "Facebook.*foreground"):
            controller.replace_facebook_search_text(
                "device-tiktok", "facebook seed"
            )

        self.assertEqual([], broadcasts)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_ready_check_keeps_open_facebook_and_launches_only_when_needed(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        launches = []
        home_checks = []
        portrait_locks = []
        controller.lock_portrait = (
            lambda device_id, retries=2:
            portrait_locks.append(device_id) or True
        )
        controller.ensure_facebook_home = (
            lambda device_id: home_checks.append(device_id) or True
        )
        foreground_states = iter([True, False, True])
        controller.is_facebook_in_foreground = (
            lambda _device_id: next(foreground_states)
        )
        controller.launch_app = (
            lambda device_id, package: launches.append((device_id, package))
        )

        self.assertTrue(controller.ensure_facebook_ready("device-1"))
        self.assertEqual([], launches)

        self.assertTrue(controller.ensure_facebook_ready("device-2"))
        self.assertEqual(
            [("device-2", "com.facebook.katana")],
            launches,
        )
        self.assertEqual(["device-1", "device-2"], home_checks)
        self.assertGreaterEqual(portrait_locks.count("device-1"), 2)
        self.assertGreaterEqual(portrait_locks.count("device-2"), 3)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_page_click_uses_full_result_containing_every_target_word(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.EditText"
                    text="Thương Hiệu Mẫu"
                    bounds="[60,25][900,145]" />
              <node clickable="true" bounds="[20,200][1060,380]">
                <node class="android.widget.TextView"
                      text="Nhà Thuốc Mẫu - Thương Hiệu Mẫu"
                      bounds="[100,230][800,300]" />
              </node>
              <node clickable="true" bounds="[20,400][1060,660]">
                <node class="android.widget.TextView"
                      text="Nhà thuốc Thương Hiệu Mẫu - Chăm sóc da chuẩn y khoa"
                      bounds="[100,430][950,560]" />
              </node>
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(
                controller.find_and_click_facebook_page(
                    "device-1",
                    "Thương Hiệu Mẫu",
                    exact_page_name=(
                        "Nhà thuốc Thương Hiệu Mẫu - Chăm sóc da "
                        "chuẩn y khoa"
                    ),
                )
            )

        self.assertEqual([(540, 530)], taps)

        taps.clear()
        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(
                controller.find_and_click_facebook_page(
                    "device-1",
                    "Thương Hiệu Mẫu",
                )
            )

        self.assertEqual(
            [(540, 530)],
            taps,
            "Không cấu hình tên chính xác thì ưu tiên tên Page đầy đủ hơn",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_page_click_accepts_target_phrase_when_exact_label_is_truncated(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.EditText"
                    text="Khải Hoàn Skincare"
                    bounds="[60,25][900,145]" />
              <node clickable="true" bounds="[20,260][1060,500]">
                <node class="android.widget.TextView"
                      text="Khải Hoàn Skincare"
                      bounds="[100,300][850,380]" />
              </node>
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            clicked = controller.find_and_click_facebook_page(
                "device-pixel",
                "Khải Hoàn Skincare",
                exact_page_name=(
                    "Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa"
                ),
            )

        self.assertTrue(clicked)
        self.assertEqual([(540, 380)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_target_results_return_to_top_and_select_pages_filter(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node clickable="true" bounds="[830,120][1060,230]">
                <node class="android.widget.TextView"
                      text="Trang"
                      bounds="[880,145][1010,205]" />
              </node>
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        swipes = []
        taps = []
        controller.swipe = (
            lambda _device_id, x1, y1, x2, y2, duration=500:
            swipes.append((x1, y1, x2, y2, duration))
        )
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            prepared = controller.prepare_facebook_target_results(
                "device-pixel"
            )

        self.assertTrue(prepared)
        self.assertGreaterEqual(len(swipes), 2)
        self.assertTrue(
            all(y1 < y2 for _, y1, _, y2, _ in swipes),
            "Đưa kết quả về đầu phải vuốt ngón tay từ trên xuống dưới",
        )
        self.assertEqual([(945, 175)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_search_uses_verified_home_header_without_extra_back(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node content-desc="Story card"
                    bounds="[670,70][1010,700]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        states = iter(
            [
                None,
                None,
                {"text": "", "focused": True, "coords": (430, 90)},
                {"text": "", "focused": True, "coords": (430, 90)},
            ]
        )
        controller._get_facebook_search_input_state = (
            lambda _device_id: next(states)
        )
        events = []
        controller.ensure_facebook_home = lambda _device_id: True
        controller.reveal_facebook_header = (
            lambda _device_id: events.append("reveal") or True
        )
        controller.keyevent = (
            lambda _device_id, key: events.append(("back", key))
        )
        controller.tap = (
            lambda _device_id, _x, _y: events.append("tap")
        )

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(
                controller.find_and_click_facebook_search("device-story")
            )

        self.assertEqual(["tap"], events)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_waits_for_transient_foreground_then_backs_once(self, _sleep):
        """Một nhịp dumpsys trống không được làm Facebook dừng trước khi Back."""
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        foreground = iter([False, True])
        controller.is_facebook_in_foreground = (
            lambda _device_id: next(foreground, True)
        )
        states = iter(
            [
                None,
                None,
                {"text": "", "focused": True, "coords": (430, 90)},
            ]
        )
        controller._get_facebook_search_input_state = (
            lambda _device_id: next(states, None)
        )
        header_coords = iter([None, (900, 100)])
        controller._get_facebook_header_search_coords = (
            lambda _device_id: next(header_coords, None)
        )
        controller.is_facebook_home = lambda _device_id: False
        controller.get_effective_screen_size = (
            lambda _device_id: (1080, 1920)
        )
        keys = []
        taps = []
        controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            controller.find_and_click_facebook_search("device-focus-gap")
        )
        self.assertEqual([4], keys)
        self.assertEqual([(900, 100)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_search_fails_when_adb_rejects_verified_home_icon_tap(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            '<hierarchy><node content-desc="Story card" '
            'bounds="[670,70][1010,700]" /></hierarchy>'
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller.reveal_facebook_header = lambda _device_id: True
        keys = []
        taps = []
        controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
            or (1, "", "tap rejected")
        )

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertFalse(
                controller.find_and_click_facebook_search("device-hidden-header")
            )

        self.assertEqual([], keys)
        self.assertEqual([(896, 105), (896, 105)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_search_does_not_use_blind_fallback_inside_photo_viewer(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.ImageView"
                    content-desc="Ảnh"
                    bounds="[0,63][1080,1920]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda _device_id, retries=2: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.is_facebook_home = lambda _device_id: False
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertFalse(
                controller.find_and_click_facebook_search("device-1")
            )

        self.assertEqual([], taps)

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_home_detection_accepts_facebook_header_controls(
        self, _exists, _remove
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node content-desc="Menu" bounds="[20,65][115,155]" />
              <node content-desc="Tạo, nhấn đúp để tạo bài viết"
                    bounds="[700,65][790,155]" />
              <node content-desc="Tìm kiếm"
                    bounds="[810,65][900,155]" />
              <node content-desc="Nhắn tin, 3 mục mới"
                    bounds="[920,65][1060,155]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(controller.is_facebook_home("device-1"))

    def test_home_detection_is_unknown_when_xml_pull_is_busy(self):
        controller = ADBController(adb_path="adb")

        def execute(_device_id, args, timeout=15):
            if args and args[0] == "pull":
                return -1, "", "ADB server busy"
            return 0, "", ""

        controller.execute_adb = execute

        self.assertIsNone(controller.is_facebook_home("device-pull-busy"))

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_home_detection_accepts_english_facebook_header_controls(
        self, _exists, _remove
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node content-desc="Menu" bounds="[20,65][115,155]" />
              <node content-desc="Create, double-tap to create a new post"
                    bounds="[700,65][790,155]" />
              <node content-desc="Search"
                    bounds="[810,65][900,155]" />
              <node content-desc="Messaging, 4 new"
                    bounds="[920,65][1060,155]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(controller.is_facebook_home("device-english"))

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_home_detection_rejects_story_viewer_with_header_like_controls(
        self, _exists, _remove
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node content-desc="Menu" bounds="[20,65][115,155]" />
              <node content-desc="Create" bounds="[700,65][790,155]" />
              <node content-desc="Search" bounds="[810,65][900,155]" />
              <node content-desc="Messaging" bounds="[920,65][1060,155]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")

        def execute(_device_id, args, timeout=15):
            if args[-3:] == ["dumpsys", "window", "windows"]:
                return (
                    0,
                    "mCurrentFocus=com.facebook.katana/"
                    "com.facebook.stories.viewer.activity.StoryViewerActivity",
                    "",
                )
            return 0, "", ""

        controller.execute_adb = execute
        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertFalse(controller.is_facebook_home("device-story"))

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_search_backs_once_when_first_tap_does_not_open_input(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node content-desc="Search"
                    bounds="[810,65][900,155]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda _device_id, retries=2: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.is_facebook_home = lambda _device_id: True
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        states = iter(
            [
                None,
                None,
                None,
                {"text": "", "focused": True, "coords": (430, 90)},
            ]
        )
        controller._get_facebook_search_input_state = (
            lambda _device_id: next(states)
        )
        controller.reveal_facebook_header = lambda _device_id: True
        keys = []
        controller.keyevent = (
            lambda _device_id, key: keys.append(key) or (0, "", "")
        )
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(
                controller.find_and_click_facebook_search("device-retry")
            )

        self.assertEqual([4], keys)
        self.assertEqual(2, len(taps))

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_target_page_verification_accepts_english_profile_actions(
        self, _exists, _remove
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node text="Nhà thuốc Thương Hiệu Mẫu - Chăm sóc da chuẩn y khoa" />
              <node text="Follow" />
              <node text="Message" />
              <node text="Posts" />
              <node text="About" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(
                controller.is_facebook_target_page_open(
                    "device-page",
                    "Thương Hiệu Mẫu",
                    exact_page_name=(
                        "Nhà thuốc Thương Hiệu Mẫu - Chăm sóc da "
                        "chuẩn y khoa"
                    ),
                )
            )

    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_target_page_verification_accepts_short_profile_header(
        self, _exists, _remove
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node text="Khải Hoàn Skincare" />
              <node text="Theo dõi" />
              <node text="Bài viết" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            opened = controller.is_facebook_target_page_open(
                "device-short-header",
                "Khải Hoàn Skincare",
                exact_page_name=(
                    "Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa"
                ),
            )

        self.assertTrue(opened)

    @patch("adb_controller.random.randint", side_effect=[100, 45, 150])
    @patch(
        "adb_controller.random.choice",
        side_effect=["chăm sóc da", "Thương Hiệu Mẫu"],
    )
    def test_workflow_reopens_facebook_before_each_keyword_stage(
        self, _choice, _randint
    ):
        controller = ADBController(adb_path="adb")
        state = {"foreground": False}
        ready_calls = []
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.warmup_tiktok_before_facebook = lambda *_args, **_kwargs: True
        controller.is_facebook_in_foreground = (
            lambda _device_id: state["foreground"]
        )

        def ensure_ready(device_id):
            ready_calls.append(device_id)
            state["foreground"] = True
            return True

        def browse(_device_id, _total, label, **_kwargs):
            if label in ("feed", "seed_results"):
                state["foreground"] = False

        controller.ensure_facebook_ready = ensure_ready
        controller.browse_facebook_surface = browse
        controller.return_facebook_home_before_search = (
            lambda _device_id: True
        )
        controller.reveal_facebook_header = lambda _device_id: True
        controller.find_and_click_facebook_search = lambda *_args, **_kwargs: True
        controller.replace_facebook_search_text = lambda *_args, **_kwargs: True
        controller.submit_facebook_search = lambda *_args, **_kwargs: True
        controller.facebook_loading_delay = lambda *_args, **_kwargs: None
        controller.find_and_click_facebook_page = lambda *_args, **_kwargs: True
        controller.is_facebook_target_page_open = lambda *_args, **_kwargs: True

        with patch("builtins.print"):
            success, message = controller.facebook_automation_workflow(
                "device-recovery",
                seed_keywords="chăm sóc da",
                target_pages="Thương Hiệu Mẫu",
            )

        self.assertTrue(success, message)
        self.assertEqual(
            ["device-recovery", "device-recovery", "device-recovery"],
            ready_calls,
        )

    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.random.choice", side_effect=lambda values: values[0])
    def test_workflow_retries_target_page_when_first_result_scan_is_late(
        self, _choice, _randint
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.warmup_tiktok_before_facebook = lambda *_args, **_kwargs: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.ensure_facebook_ready = lambda _device_id: True
        controller.browse_facebook_surface = lambda *_args, **_kwargs: True
        controller.reveal_facebook_header = lambda _device_id: True
        controller.find_and_click_facebook_search = lambda *_args, **_kwargs: True
        controller.replace_facebook_search_text = lambda *_args, **_kwargs: True
        controller.submit_facebook_search = lambda *_args, **_kwargs: True
        controller.facebook_loading_delay = lambda *_args, **_kwargs: None
        page_scans = iter([False, True])
        scan_count = []

        def find_page(*_args, **_kwargs):
            scan_count.append(1)
            return next(page_scans)

        controller.find_and_click_facebook_page = find_page
        controller.is_facebook_target_page_open = lambda *_args, **_kwargs: True

        with patch("builtins.print"):
            success, message = controller.facebook_automation_workflow(
                "device-late-result",
                seed_keywords="chăm sóc da",
                target_pages="Khải Hoàn Skincare",
            )

        self.assertTrue(success, message)
        self.assertEqual(2, len(scan_count))

    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.random.choice", side_effect=lambda values: values[0])
    @patch("adb_controller.time.sleep", return_value=None)
    def test_workflow_waits_for_target_profile_verification_after_click(
        self, _sleep, _choice, _randint
    ):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.warmup_tiktok_before_facebook = lambda *_args, **_kwargs: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.ensure_facebook_ready = lambda _device_id: True
        controller.browse_facebook_surface = lambda *_args, **_kwargs: True
        controller.reveal_facebook_header = lambda _device_id: True
        controller.find_and_click_facebook_search = lambda *_args, **_kwargs: True
        controller.replace_facebook_search_text = lambda *_args, **_kwargs: True
        controller.submit_facebook_search = lambda *_args, **_kwargs: True
        controller.facebook_loading_delay = lambda *_args, **_kwargs: None
        controller.find_and_click_facebook_page = lambda *_args, **_kwargs: True
        profile_checks = iter([False, True])
        controller.is_facebook_target_page_open = (
            lambda *_args, **_kwargs: next(profile_checks)
        )

        with patch("builtins.print"):
            success, message = controller.facebook_automation_workflow(
                "device-slow-profile",
                seed_keywords="chăm sóc da",
                target_pages="Khải Hoàn Skincare",
            )

        self.assertTrue(success, message)

    @patch("adb_controller.random.randint", side_effect=[100, 45, 150])
    @patch(
        "adb_controller.random.choice",
        side_effect=["chăm sóc da", "Thương Hiệu Mẫu"],
    )
    def test_workflow_replaces_seed_with_whole_target_phrase(
        self, _choice, _randint
    ):
        controller = ADBController(adb_path="adb")
        events = []
        controller.lock_portrait = lambda _device_id, retries=2: True
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller.warmup_tiktok_before_facebook = (
            lambda _device_id, **_kwargs:
            events.append(("cross_warmup", "tiktok")) or True
        )
        controller.ensure_facebook_ready = lambda _device_id: True
        controller.return_facebook_home_before_search = (
            lambda _device_id: events.append(("back_home",)) or True
        )
        controller.browse_facebook_surface = (
            lambda _device_id, total, label, **_kwargs:
            events.append(("browse", label, total))
        )
        controller.find_and_click_facebook_search = (
            lambda *_args, **_kwargs: events.append(("search",)) or True
        )
        controller.replace_facebook_search_text = (
            lambda _device_id, text, **_kwargs:
            events.append(("replace", text)) or True
        )
        controller.submit_facebook_search = (
            lambda *_args, **_kwargs: events.append(("enter",))
        )
        controller.facebook_loading_delay = (
            lambda _device_id, context, **_kwargs:
            events.append(("load", context))
        )
        controller.prepare_facebook_target_results = (
            lambda _device_id: events.append(("prepare_target_results",))
            or True
        )
        controller.find_and_click_facebook_page = (
            lambda _device_id, target, exact_page_name=None, **_kwargs:
            events.append(("page", target)) or True
        )
        controller.is_facebook_target_page_open = (
            lambda _device_id, target, exact_page_name=None:
            events.append(("verify", target)) or True
        )

        with patch("builtins.print"):
            success, message = controller.facebook_automation_workflow(
                "device-1",
                seed_keywords="mụn, chăm sóc da",
                target_pages="Thương Hiệu Mẫu, Dược mỹ phẩm địa phương",
            )

        self.assertTrue(success, message)
        self.assertEqual(
            [
                ("cross_warmup", "tiktok"),
                ("browse", "feed", 100),
                ("back_home",),
                ("search",),
                ("replace", "chăm sóc da"),
                ("enter",),
                ("load", "seed_results"),
                ("browse", "seed_results", 45),
                ("search",),
                ("replace", "Thương Hiệu Mẫu"),
                ("enter",),
                ("load", "target_results"),
                ("prepare_target_results",),
                ("page", "Thương Hiệu Mẫu"),
                ("load", "target_page"),
                ("verify", "Thương Hiệu Mẫu"),
                ("browse", "target_page", 150),
            ],
            events,
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_search_replacement_clears_old_text_before_each_input(self, _sleep):
        controller = ADBController(adb_path="adb")
        controller.ensure_ime = lambda _device_id: None
        controller.is_facebook_in_foreground = lambda _device_id: True
        controller._focus_facebook_search_input = lambda _device_id: True
        broadcasts = []
        current_text = {"value": ""}

        def execute(_device_id, args, timeout=15):
            if "XW_CLEAR_TEXT" in args:
                broadcasts.append("clear")
                current_text["value"] = ""
            elif "XW_INPUT_B64" in args:
                encoded = args[args.index("msg") + 1]
                value = base64.b64decode(encoded).decode("utf-8")
                broadcasts.append(f"input:{value}")
                current_text["value"] = value
            return 0, "", ""

        controller.execute_adb = execute
        controller._get_facebook_search_input_state = (
            lambda _device_id: {
                "text": current_text["value"],
                "focused": True,
                "coords": (400, 90),
            }
        )

        controller.replace_facebook_search_text("device-1", "chăm sóc da")
        controller.replace_facebook_search_text(
            "device-1", "Thương Hiệu Mẫu"
        )

        self.assertEqual(
            [
                "clear",
                "input:chăm sóc da",
                "clear",
                "input:Thương Hiệu Mẫu",
            ],
            broadcasts,
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_replace_search_text_allows_enter_when_facebook_xml_is_busy(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.wait_for_facebook_foreground = lambda _device_id: True
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._focus_facebook_search_input = lambda _device_id: True
        controller.ensure_ime = lambda _device_id: None
        broadcasts = []

        def execute(_device_id, args, timeout=15):
            if "XW_CLEAR_TEXT" in args:
                broadcasts.append("clear")
            elif "XW_INPUT_B64" in args:
                encoded = args[args.index("msg") + 1]
                broadcasts.append(
                    "input:" + base64.b64decode(encoded).decode("utf-8")
                )
            return 0, "", ""

        controller.execute_adb = execute

        self.assertTrue(
            controller.replace_facebook_search_text(
                "device-suggestion-panel",
                "lấy nhân mụn chuẩn y khoa Phan Thiết",
            )
        )
        self.assertEqual(
            [
                "clear",
                "input:lấy nhân mụn chuẩn y khoa Phan Thiết",
            ],
            broadcasts,
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_replace_search_text_accepts_visible_text_when_input_broadcast_reports_error(
        self, _sleep
    ):
        """Một số máy hiển thị chữ dù am broadcast trả mã lỗi; không báo lỗi giả."""
        controller = ADBController(adb_path="adb")
        controller.wait_for_facebook_foreground = lambda _device_id: True
        controller._focus_facebook_search_input = lambda _device_id: True
        controller.ensure_ime = lambda _device_id: None
        current_text = {"value": ""}
        broadcasts = []
        expected = "lấy nhân mụn chuẩn y khoa Phan Thiết"

        def execute(_device_id, args, timeout=15):
            if "XW_CLEAR_TEXT" in args:
                current_text["value"] = ""
                broadcasts.append("clear")
                return 0, "", ""
            if "XW_INPUT_B64" in args:
                encoded = args[args.index("msg") + 1]
                current_text["value"] = base64.b64decode(encoded).decode("utf-8")
                broadcasts.append("input")
                return 1, "", "receiver reported failure"
            return 0, "", ""

        controller.execute_adb = execute
        controller._get_facebook_search_input_state = lambda _device_id: {
            "text": current_text["value"],
            "focused": True,
            "coords": (400, 90),
        }

        self.assertTrue(controller.replace_facebook_search_text("device-1", expected))
        self.assertEqual(["clear", "input"], broadcasts)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_target_replace_and_enter_survive_transient_foreground_probe_failure(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.wait_for_facebook_foreground = lambda *_args, **_kwargs: False
        controller._get_facebook_search_input_state = lambda _device_id: None
        controller._focus_facebook_search_input = lambda _device_id: True
        controller.ensure_ime = lambda _device_id: None
        broadcasts = []
        enters = []

        def execute(_device_id, args, timeout=15):
            if "XW_CLEAR_TEXT" in args:
                broadcasts.append("clear")
            elif "XW_INPUT_B64" in args:
                encoded = args[args.index("msg") + 1]
                broadcasts.append(
                    "input:" + base64.b64decode(encoded).decode("utf-8")
                )
            return 0, "", ""

        controller.execute_adb = execute
        controller.press_enter = (
            lambda _device_id: enters.append("enter") or (0, "", "")
        )

        self.assertTrue(
            controller.replace_facebook_search_text(
                "device-b3-busy",
                "Khải Hoàn Skincare",
                allow_transient_foreground=True,
            )
        )
        self.assertEqual(
            (0, "", ""),
            controller.submit_facebook_search(
                "device-b3-busy", allow_transient_foreground=True
            ),
        )
        self.assertEqual(
            ["clear", "input:Khải Hoàn Skincare"], broadcasts
        )
        self.assertEqual(["enter"], enters)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_page_click_selects_exact_phan_thiet_page_inside_oversized_recycler(
        self, _exists, _remove, _sleep
    ):
        """Mô phỏng danh sách 3 Page dưới 'Trang' nằm trong RecyclerView toàn màn hình:
        Item 1: Nhà Thuốc Khải Hoàn - Khải Hoàn Skincare
        Item 2: Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa Spa Clinic
        Item 3: Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa Phan Thiết
        Tool phải bấm chính xác Item 3 (y ~ 770), không bị kéo lên tâm RecyclerView (y ~ 1175).
        """
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="androidx.recyclerview.widget.RecyclerView" clickable="true" bounds="[0,150][1080,2200]">
                <node class="android.view.ViewGroup" bounds="[0,200][1080,420]">
                  <node class="android.widget.TextView" text="Nhà Thuốc Khải Hoàn - Khải Hoàn Skincare" bounds="[168,220][900,310]" />
                </node>
                <node class="android.view.ViewGroup" bounds="[0,430][1080,650]">
                  <node class="android.widget.TextView" text="Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa Spa Clinic" bounds="[168,450][900,540]" />
                </node>
                <node class="android.view.ViewGroup" bounds="[0,660][1080,880]">
                  <node class="android.widget.TextView" text="Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa Phan Thiết" bounds="[168,680][900,770]" />
                </node>
              </node>
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_effective_screen_size = lambda _device_id: (1080, 2400)
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            clicked = controller.find_and_click_facebook_page(
                "device-s1",
                "Khải Hoàn Skincare",
                exact_page_name=(
                    "Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa "
                    "Phan Thiết"
                ),
            )

        self.assertTrue(clicked)
        self.assertEqual(1, len(taps))
        tap_x, tap_y = taps[0]
        self.assertEqual(534, tap_x)
        self.assertTrue(
            660 <= tap_y <= 880,
            f"Tap Y ({tap_y}) phải nằm trong bounds của Item 3 [660, 880]"
        )

    @patch("adb_controller.time.sleep")
    def test_facebook_workflow_multi_page_random_selection(self, _mock_sleep):
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: None
        controller.warmup_tiktok_before_facebook = lambda *_args, **_kwargs: None
        controller.launch_facebook = lambda *_args, **_kwargs: None
        controller.ensure_facebook_ready = lambda *_args, **_kwargs: True
        controller.is_facebook_in_foreground = lambda *_args, **_kwargs: True
        controller.browse_facebook_surface = lambda *_args, **_kwargs: None

        statuses = []
        target_input = (
            "Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa Spa Clinic, "
            "Nhà Thuốc Khải Hoàn - Khải Hoàn Skincare"
        )
        controller.facebook_automation_workflow(
            "device-1",
            seed_keywords="mồi da mụn",
            target_pages=target_input,
            status_callback=lambda _dev, text: statuses.append(text),
        )
        self.assertTrue(
            any("Chọn ngẫu nhiên Page mục tiêu" in s for s in statuses),
            f"Statuses must contain multi-target log, got: {statuses}"
        )

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_find_and_click_facebook_page_randomizes_among_matching_cards(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.EditText"
                    text="Nhà thuốc Khải Hoàn"
                    bounds="[60,25][900,145]" />
              <node clickable="true" bounds="[20,200][1060,380]">
                <node class="android.widget.TextView"
                      text="Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa Spa Clinic"
                      bounds="[100,230][800,300]" />
              </node>
              <node clickable="true" bounds="[20,400][1060,580]">
                <node class="android.widget.TextView"
                      text="Nhà Thuốc Khải Hoàn - Khải Hoàn Skincare"
                      bounds="[100,430][950,500]" />
              </node>
              <node clickable="true" bounds="[20,600][1060,780]">
                <node class="android.widget.TextView"
                      text="Nhà thuốc Khải Hoàn Dược Mỹ Phẩm"
                      bounds="[100,630][950,700]" />
              </node>
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.execute_adb = lambda _device_id, _args, timeout=15: (0, "", "")
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch("adb_controller.ET.parse", return_value=SimpleNamespace(getroot=lambda: root)):
            success = controller.find_and_click_facebook_page(
                "device-1",
                "Nhà thuốc Khải Hoàn",
                randomize_matching_pages=True,
            )
        self.assertTrue(success)
        self.assertEqual(1, len(taps))
        possible_ys = {290, 490, 690}
        self.assertIn(taps[0][1], possible_ys)


if __name__ == "__main__":
    unittest.main()

