import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

from adb_controller import ADBController
import main


class ShopeeSearchClickTests(unittest.TestCase):
    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_homepage_add_to_cart_text_does_not_redirect_to_cart(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/inputSearchBar"
                    bounds="[20,58][838,190]" />
              <node text="Thêm vào giỏ"
                    bounds="[500,400][1000,900]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
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
                controller.ensure_shopee_search_box_click("device-1")
            )

        self.assertEqual(
            [(429, 124)],
            taps,
            "Trang chủ phải bấm đúng ô search, không bấm vùng giỏ hàng",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_homepage_generic_top_edittext_is_safe_search_target(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/a1b2c3"
                    class="android.widget.EditText"
                    editable="true"
                    clickable="true"
                    bounds="[24,58][828,190]" />
              <node resource-id="com.shopee.vn:id/cart_btn"
                    class="android.widget.ImageView"
                    bounds="[900,58][1040,190]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
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
                controller.ensure_shopee_search_box_click("device-1")
            )

        self.assertEqual([(426, 124)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_product_detail_uses_header_search_icon_instead_of_blind_home_tap(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/product_detail_header"
                    bounds="[0,0][1080,210]">
                <node resource-id="com.shopee.vn:id/search_icon"
                      class="android.widget.ImageView"
                      bounds="[820,58][900,138]" />
                <node resource-id="com.shopee.vn:id/cart_btn"
                      class="android.widget.ImageView"
                      bounds="[940,58][1040,158]" />
              </node>
              <node text="Mua cùng Voucher"
                    bounds="[400,1700][1080,1900]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
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
                controller.ensure_shopee_search_box_click("device-1")
            )

        self.assertEqual(
            [(860, 98)],
            taps,
            "Ở trang chi tiết phải bấm kính lúp header, không bấm Home/giỏ hàng",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_product_detail_without_search_icon_backs_out_then_uses_home_search(
        self, _exists, _remove, _sleep
    ):
        detail_root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/product_detail_header"
                    bounds="[0,0][1080,210]" />
              <node text="Mua cùng Voucher"
                    bounds="[400,1700][1080,1900]" />
            </hierarchy>
            """
        )
        home_root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/inputSearchBar"
                    bounds="[20,58][838,190]" />
              <node resource-id="com.shopee.vn:id/cart_btn"
                    bounds="[838,58][959,190]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        taps = []
        keyevents = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))
        controller.keyevent = (
            lambda _device_id, keycode: keyevents.append(keycode)
        )

        with patch(
            "adb_controller.ET.parse",
            side_effect=[
                SimpleNamespace(getroot=lambda: detail_root),
                SimpleNamespace(getroot=lambda: home_root),
            ],
        ):
            self.assertTrue(
                controller.ensure_shopee_search_box_click("device-1")
            )

        self.assertEqual([4], keyevents)
        self.assertEqual([(429, 124)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_search_click_recovers_homepage_after_safe_scans_fail(
        self, _exists, _remove, _sleep
    ):
        blank_root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/loading"
                    bounds="[0,0][1080,1920]" />
            </hierarchy>
            """
        )
        home_root = ET.fromstring(
            """
            <hierarchy>
              <node resource-id="com.shopee.vn:id/inputSearchBar"
                    bounds="[20,58][838,190]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        taps = []
        recoveries = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))
        controller.keyevent = lambda *_args: None
        controller.ensure_shopee_homepage = (
            lambda *_args, **_kwargs: recoveries.append(True) or True
        )
        controller.bypass_shopee_popup = lambda _device_id: None

        with patch(
            "adb_controller.ET.parse",
            side_effect=[
                SimpleNamespace(getroot=lambda: blank_root),
                SimpleNamespace(getroot=lambda: blank_root),
                SimpleNamespace(getroot=lambda: blank_root),
                SimpleNamespace(getroot=lambda: home_root),
            ],
        ):
            self.assertTrue(
                controller.ensure_shopee_search_box_click("device-1")
            )

        self.assertEqual([True], recoveries)
        self.assertEqual([(429, 124)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_home_activity_uses_guarded_search_fallback_when_ui_dump_is_busy(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)

        def execute_adb(_device_id, args, timeout=15):
            if args[:4] == ["shell", "uiautomator", "dump", "/sdcard/dump_search_click_device-1.xml"]:
                return -1, "", "ERROR: could not get idle state"
            if args[:4] == ["shell", "dumpsys", "window", "windows"]:
                return (
                    0,
                    "mCurrentFocus=Window{abc u0 "
                    "com.shopee.vn/com.shopee.app.ui.home.HomeActivity_}",
                    "",
                )
            return 0, "", ""

        controller.execute_adb = execute_adb
        recoveries = []
        back_events = []
        controller.ensure_shopee_homepage = (
            lambda *_args, **_kwargs: recoveries.append(True) or True
        )
        controller.bypass_shopee_popup = lambda _device_id: None
        controller.keyevent = (
            lambda _device_id, keycode: back_events.append(keycode)
        )
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        self.assertTrue(
            controller.ensure_shopee_search_box_click("device-1")
        )
        self.assertEqual([(432, 153)], taps)
        self.assertEqual([], back_events)
        self.assertEqual([], recoveries)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_replace_shopee_keyword_clears_then_inputs_only_once(self, _sleep):
        controller = ADBController(adb_path="adb")
        commands = []
        controller.execute_adb = (
            lambda _device_id, args, timeout=15:
            (commands.append(args) or (0, "", ""))
        )

        self.assertTrue(
            controller.replace_shopee_search_text(
                "device-1", "trị mụn bôi da"
            )
        )

        self.assertEqual(
            1,
            sum("XW_CLEAR_TEXT" in command for command in commands),
        )
        self.assertEqual(
            1,
            sum("XW_INPUT_B64" in command for command in commands),
        )

    @patch("adb_controller.random.choice", side_effect=lambda values: values[-1])
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_random_shop_product_uses_visible_clickable_grid_card(
        self, _exists, _remove, _choice
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.view.ViewGroup" clickable="true"
                    content-desc="shop_page_product_tab"
                    bounds="[260,60][480,210]" />
              <node class="android.view.ViewGroup" clickable="true"
                    bounds="[40,500][520,1120]" />
              <node class="android.view.ViewGroup" clickable="true"
                    bounds="[560,500][1040,1120]" />
              <node class="android.view.ViewGroup" clickable="true"
                    content-desc="shop_page_button_back_to_top"
                    bounds="[940,1760][1040,1860]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            coords = controller.find_random_product_in_shop("device-1")

        self.assertEqual((800, 810), coords)

    @patch("adb_controller.random.choice", side_effect=lambda values: values[-1])
    def test_random_shop_product_uses_grid_fallback_when_ui_is_busy(
        self, _choice
    ):
        controller = ADBController(adb_path="adb")
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.execute_adb = (
            lambda _device_id, args, timeout=15:
            (
                (0, "", "ERROR: could not get idle state")
                if "uiautomator" in args
                else (0, "", "")
            )
        )

        coords = controller.find_random_product_in_shop("device-1")

        self.assertEqual((810, 1459), coords)

    @patch("adb_controller.random.uniform", return_value=1.0)
    @patch("adb_controller.random.randint", side_effect=lambda low, _high: low)
    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.config.SHOPEE_SHOP_NAMES", ["Shop Mẫu"])
    def test_shop_fallback_browses_random_product_without_product_search(
        self, _sleep, _randint, _uniform
    ):
        controller = ADBController(adb_path="adb")
        controller.ensure_shopee_homepage = lambda *_args, **_kwargs: True
        controller.bypass_shopee_popup = lambda _device_id: None
        controller.ensure_shopee_search_box_click = (
            lambda *_args, **_kwargs: True
        )
        taps = []
        statuses = []
        entered_texts = []
        enter_events = []
        controller.tap = (
            lambda _device_id, x, y: taps.append((x, y))
        )
        controller.clear_input_field = lambda _device_id: None
        controller.input_text = (
            lambda _device_id, text: entered_texts.append(text)
        )
        controller.press_enter = (
            lambda _device_id: enter_events.append(True)
        )
        controller.find_and_click_view_shop = lambda *_args, **_kwargs: (500, 500)
        controller.get_screen_size = lambda _device_id: (1080, 1920)
        controller.find_random_product_in_shop = (
            lambda _device_id: (700, 900)
        )
        controller.swipe = lambda *_args, **_kwargs: None
        controller.swipe_curved = lambda *_args, **_kwargs: None
        controller.find_shop_search_box = lambda *_args: self.fail(
            "Không được bấm ô tìm kiếm sau khi đã vào shop dự phòng"
        )
        controller.replace_shopee_search_text = lambda *_args: self.fail(
            "Không được nhập keyword sản phẩm trong shop dự phòng"
        )
        controller.find_first_product_in_shop = lambda *_args: self.fail(
            "Không được tìm sản phẩm theo keyword trong shop dự phòng"
        )

        success, _message = controller.shopee_fallback_by_shop_name(
            "device-1",
            "Sản phẩm mẫu hiệu quả",
            status_callback=lambda _device_id, message: statuses.append(message),
        )

        self.assertTrue(success)
        self.assertEqual(["Shop Mẫu"], entered_texts)
        self.assertEqual(1, len(enter_events))
        self.assertIn((700, 900), taps)
        self.assertTrue(
            any("ngẫu nhiên" in message.lower() for message in statuses)
        )

    @patch("main.time.sleep", return_value=None)
    @patch("main.random.randint", return_value=60)
    @patch("main.random.choice", return_value="từ khóa chung")
    def test_sequential_uses_one_random_keyword_for_all_devices(
        self, choice_mock, _randint, _sleep
    ):
        used_keywords = []
        fake_adb = SimpleNamespace(
            shopee_find_and_click_lamdong=(
                lambda _dev, keyword, **_kwargs:
                (used_keywords.append(keyword) or (True, ""))
            )
        )
        fake_tracker = SimpleNamespace(
            start_dashboard=lambda *_args, **_kwargs: None,
            set_active_device=lambda *_args, **_kwargs: None,
            status_callback=lambda *_args, **_kwargs: None,
            update_rest_countdown=lambda *_args, **_kwargs: None,
            finish_dashboard=lambda *_args, **_kwargs: None,
        )
        message = SimpleNamespace(chat=SimpleNamespace(id=123))

        with (
            patch("main.adb", fake_adb),
            patch("main.TelegramRealtimeTracker", return_value=fake_tracker),
            patch("main.get_device_name", side_effect=["S1", "S2", "S2"]),
            patch("main.send_device_finished_card"),
            patch("main.safe_send_message"),
        ):
            main.run_sequential_shopee_search(
                message,
                ["từ khóa 1", "từ khóa 2", "từ khóa 3"],
                ["device-1", "device-2"],
                use_ai=False,
            )

        self.assertEqual(["từ khóa chung", "từ khóa chung"], used_keywords)
        choice_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
