import unittest
import xml.etree.ElementTree as ET
import base64
from types import SimpleNamespace
from unittest.mock import patch

from adb_controller import ADBController


class FacebookAutomationTests(unittest.TestCase):
    @patch("adb_controller.time.sleep", return_value=None)
    def test_facebook_browse_never_swipes_when_another_app_is_foreground(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        swipes = []
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.is_facebook_in_foreground = lambda _device_id: False
        controller.swipe = lambda *_args, **_kwargs: swipes.append(_args)

        with self.assertRaisesRegex(RuntimeError, "Facebook.*foreground"):
            controller.browse_facebook_surface(
                "device-on-shopee",
                20,
                "facebook_cross_warmup",
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
    def test_search_never_taps_fallback_before_header_is_revealed(
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
        controller.restart_facebook_home = (
            lambda _device_id: events.append("restart") or True
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

        self.assertEqual(["reveal", "restart", "tap"], events)

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
    def test_search_recovers_to_home_when_first_tap_does_not_open_input(
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
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        states = iter(
            [None, {"text": "", "focused": True, "coords": (430, 90)}]
        )
        controller._get_facebook_search_input_state = (
            lambda _device_id: next(states)
        )
        recoveries = []
        controller.ensure_facebook_home = (
            lambda device_id: recoveries.append(device_id) or True
        )
        controller.reveal_facebook_header = lambda _device_id: True
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            self.assertTrue(
                controller.find_and_click_facebook_search("device-retry")
            )

        self.assertEqual(["device-retry"], recoveries)
        self.assertEqual(1, len(taps))

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
        controller.reveal_facebook_header = lambda _device_id: True
        controller.find_and_click_facebook_search = lambda _device_id: True
        controller.replace_facebook_search_text = lambda *_args: True
        controller.submit_facebook_search = lambda _device_id: True
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
        controller.browse_facebook_surface = (
            lambda _device_id, total, label, **_kwargs:
            events.append(("browse", label, total))
        )
        controller.reveal_facebook_header = (
            lambda _device_id: events.append(("reveal",))
        )
        controller.find_and_click_facebook_search = (
            lambda _device_id: events.append(("search",)) or True
        )
        controller.replace_facebook_search_text = (
            lambda _device_id, text: events.append(("replace", text)) or True
        )
        controller.submit_facebook_search = (
            lambda _device_id: events.append(("enter",))
        )
        controller.facebook_loading_delay = (
            lambda _device_id, context, **_kwargs:
            events.append(("load", context))
        )
        controller.find_and_click_facebook_page = (
            lambda _device_id, target, exact_page_name=None:
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
                ("reveal",),
                ("search",),
                ("replace", "chăm sóc da"),
                ("enter",),
                ("load", "seed_results"),
                ("browse", "seed_results", 45),
                ("search",),
                ("replace", "Thương Hiệu Mẫu"),
                ("enter",),
                ("load", "target_results"),
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


if __name__ == "__main__":
    unittest.main()
