import unittest
from unittest.mock import MagicMock, patch
import time
import xml.etree.ElementTree as ET

import config
from adb_controller import ADBController
from gui_app import GUIApp, split_google_maps_keywords
import main


class GoogleMapsAutomationTests(unittest.TestCase):
    def setUp(self):
        self.adb = ADBController("dummy_adb")

    def test_normalize_maps_text(self):
        self.assertEqual(
            ADBController._normalize_maps_text("Nhà thuốc Khải Hoàn Skincare"),
            "nha thuoc khai hoan skincare",
        )
        self.assertEqual(
            ADBController._normalize_maps_text("Phan Thiết, Lâm Đồng!"),
            "phan thiet lam dong",
        )

    def test_split_google_maps_keywords_comma_and_newline(self):
        text = "chăm sóc da, trị mụn, spa lấy mụn\nnặn mụn chuẩn y khoa, mỹ phẩm"
        result = split_google_maps_keywords(text)
        expected = [
            "chăm sóc da",
            "trị mụn",
            "spa lấy mụn",
            "nặn mụn chuẩn y khoa",
            "mỹ phẩm",
        ]
        self.assertEqual(result, expected)

    def test_assign_maps_tasks_distributes_randomly_to_all_devices(self):
        keywords = ["từ khóa 1", "từ khóa 2", "từ khóa 3"]
        locations = ["Phan Thiết", "Lâm Đồng"]
        devices = ["device_1", "device_2", "device_3", "device_4"]

        tasks = GUIApp._assign_maps_tasks(keywords, locations, devices)
        self.assertEqual(len(tasks), 4)

        for dev_id, kw, loc in tasks:
            self.assertIn(dev_id, devices)
            self.assertIn(kw, keywords)
            self.assertIn(loc, locations)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "lock_portrait", return_value=True)
    @patch.object(ADBController, "launch_chrome", return_value=True)
    @patch.object(ADBController, "dismiss_chrome_popups", return_value=True)
    @patch.object(ADBController, "ensure_chrome_ready", return_value=True)
    @patch.object(ADBController, "find_and_search_chrome", return_value=True)
    @patch.object(ADBController, "find_and_click_google_maps_target", return_value=True)
    @patch.object(ADBController, "browse_google_maps_profile", return_value=True)
    @patch.object(ADBController, "interact_google_maps_profile_actions", return_value=True)
    def test_workflow_runs_successfully(
        self,
        mock_actions,
        mock_browse,
        mock_find_target,
        mock_search_chrome,
        mock_ready,
        mock_popups,
        mock_launch,
        mock_lock,
        mock_sleep,
    ):
        status_updates = []
        success, res = self.adb.google_maps_automation_workflow(
            "dev_01",
            keywords=["trị mụn"],
            target_name="Nhà thuốc Khải Hoàn Skincare",
            locations=["Phan Thiết"],
            status_callback=lambda _d, msg: status_updates.append(msg),
        )
        self.assertTrue(success)
        self.assertEqual(res, "Thành công")
        self.assertTrue(mock_ready.called)
        self.assertTrue(mock_search_chrome.called)
        self.assertTrue(mock_find_target.called)
        self.assertTrue(mock_browse.called)
        self.assertTrue(mock_actions.called)
        self.assertTrue(any("Hoàn thành" in s for s in status_updates))

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "lock_portrait", return_value=True)
    @patch.object(ADBController, "launch_chrome", return_value=True)
    @patch.object(ADBController, "dismiss_chrome_popups", return_value=True)
    @patch.object(ADBController, "ensure_chrome_ready", return_value=True)
    @patch.object(ADBController, "find_and_search_chrome", return_value=True)
    @patch.object(ADBController, "find_and_click_google_maps_target", return_value=True)
    @patch.object(ADBController, "browse_google_maps_profile", return_value=True)
    @patch.object(ADBController, "interact_google_maps_profile_actions", return_value=True)
    def test_workflow_searches_only_keyword_without_location(
        self,
        mock_actions,
        mock_browse,
        mock_find_target,
        mock_search_chrome,
        mock_ready,
        mock_popups,
        mock_launch,
        mock_lock,
        mock_sleep,
    ):
        self.adb.google_maps_automation_workflow(
            "dev_01",
            keywords=["nặn mụn Phan Thiết"],
            target_name="Nhà thuốc Khải Hoàn Skincare",
            locations=["Phan Thiết, Lâm Đồng"],
        )
        mock_search_chrome.assert_called_once()
        self.assertEqual(mock_search_chrome.call_args[0][1], "nặn mụn Phan Thiết")
        self.assertTrue(mock_find_target.called)
        self.assertEqual(mock_find_target.call_args[1].get("locations"), ["Phan Thiết, Lâm Đồng"])

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "clear_input_field", return_value=True)
    @patch.object(ADBController, "input_text", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    @patch.object(ADBController, "open_chrome_homepage", return_value=True)
    def test_find_and_search_chrome_homepage(self, mock_home, mock_key, mock_input, mock_clear, mock_tap, mock_size, mock_sleep):
        # Giả lập XML Trang chủ Chrome
        xml_home = '<hierarchy><node text="Tìm kiếm hoặc nhập URL" bounds="[60,340][660,420]"/></hierarchy>'
        root_home = ET.fromstring(xml_home)
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root_home):
            res = self.adb.find_and_search_chrome("dev_01", "kem chống nắng")
            self.assertTrue(res)
            mock_home.assert_called_once_with("dev_01", status_callback=None)
            self.assertTrue(mock_tap.called)
            self.assertTrue(mock_clear.called)
            self.assertEqual(
                [call.args[1] for call in mock_input.call_args_list],
                ["kem", "chống", "nắng"],
            )
            mock_key.assert_called_with("dev_01", 66)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "clear_input_field", return_value=True)
    @patch.object(ADBController, "input_text", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    def test_find_and_search_chrome_uses_only_tracking_keyword(self, mock_key, mock_input, mock_clear, mock_tap, mock_size, mock_sleep):
        xml_home = '<hierarchy><node text="Tìm kiếm trên Google hoặc nhập URL" bounds="[60,340][660,420]"/></hierarchy>'
        root_home = ET.fromstring(xml_home)
        with patch.object(ADBController, "open_chrome_homepage", return_value=True), \
             patch.object(ADBController, "_get_maps_ui_root", return_value=root_home):
            res = self.adb.find_and_search_chrome("dev_01", "nặn mụn Phan Thiết")
            self.assertTrue(res)
            typed_words = [call.args[1] for call in mock_input.call_args_list]
            self.assertEqual(typed_words, ["nặn", "mụn", "Phan", "Thiết"])
            self.assertNotIn("Nhà thuốc Khải Hoàn Skincare", typed_words)
            self.assertNotIn("Lâm Đồng", typed_words)
            mock_key.assert_called_once_with("dev_01", 66)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "clear_input_field", return_value=True)
    @patch.object(ADBController, "input_text", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    def test_open_chrome_homepage_clicks_chrome_home_icon(self, mock_key, mock_input, mock_clear, mock_tap, mock_size, mock_sleep):
        xml_not_home = '<hierarchy><node text="swedish massage" bounds="[100,220][620,300]"/></hierarchy>'
        xml_home_button = '<hierarchy><node resource-id="com.android.chrome:id/home_button" content-desc="Trang chủ" bounds="[24,50][84,110]"/></hierarchy>'
        with patch.object(ADBController, "is_chrome_homepage", side_effect=[False, True]), \
             patch.object(ADBController, "_get_maps_ui_root", return_value=ET.fromstring(xml_home_button)), \
             patch.object(ADBController, "dismiss_chrome_popups", return_value=False):
            self.assertTrue(self.adb.open_chrome_homepage("dev_01"))
            mock_tap.assert_called_once_with("dev_01", 54, 80)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    def test_find_and_click_target_clicks_immediately_when_present_on_first_screen(self, mock_tap, mock_size, mock_sleep):
        # Giả lập đúng màn hình người dùng gửi: có "Nhà thuốc Khải Hoàn Skincare - S..."
        xml_first = (
            '<hierarchy>'
            '<node text="Doanh nghiệp" bounds="[40,320][300,370]"/>'
            '<node text="Nhà thuốc Khải Hoàn Skincare - S..." bounds="[40,540][600,590]"/>'
            '<node text="HAYALINK SPA - Chuyên Về Mụn P..." bounds="[40,720][600,770]"/>'
            '<node text="Doanh nghiệp khác" bounds="[40,950][350,1000]"/>'
            '</hierarchy>'
        )
        root = ET.fromstring(xml_first)
        status_msgs = []
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root), \
             patch.object(ADBController, "is_in_google_maps_profile", side_effect=[False, True]):
            found = self.adb.find_and_click_google_maps_target(
                "dev_01",
                target_names=["Nhà thuốc Khải Hoàn Skincare", "Khải Hoàn Skincare"],
                status_callback=lambda _d, m: status_msgs.append(m),
            )
            self.assertTrue(found)
            self.assertTrue(mock_tap.called)
            self.assertTrue(any("Tìm thấy" in msg or "Đã tìm thấy" in msg for msg in status_msgs))
            # KHÔNG bấm vào nút "Doanh nghiệp khác"
            self.assertFalse(any("Doanh nghiệp khác" in msg for msg in status_msgs))

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    def test_find_and_click_target_clicks_other_places_when_absent_on_first_screen(self, mock_tap, mock_size, mock_sleep):
        # Lần 1: Không có Khải Hoàn, chỉ có Doanh nghiệp khác
        xml_1 = (
            '<hierarchy>'
            '<node text="Bắp Spa - Phan Thiết" bounds="[40,540][600,590]"/>'
            '<node text="Doanh nghiệp khác" bounds="[40,800][350,860]"/>'
            '</hierarchy>'
        )
        # Lần 2 (sau khi bấm Doanh nghiệp khác): Có Nhà thuốc Khải Hoàn Skincare
        xml_2 = (
            '<hierarchy>'
            '<node text="Nhà thuốc Khải Hoàn Skincare" bounds="[40,400][600,460]"/>'
            '</hierarchy>'
        )
        root1 = ET.fromstring(xml_1)
        root2 = ET.fromstring(xml_2)
        status_msgs = []
        with patch.object(ADBController, "_get_maps_ui_root", side_effect=[root1, root1, root2]), \
             patch.object(ADBController, "is_in_google_maps_profile", side_effect=[False] * 6 + [True]):
            found = self.adb.find_and_click_google_maps_target(
                "dev_01",
                target_names=["Nhà thuốc Khải Hoàn Skincare"],
                status_callback=lambda _d, m: status_msgs.append(m),
            )
            self.assertTrue(found)
            self.assertTrue(any("Doanh nghiệp khác" in msg for msg in status_msgs))

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "swipe", return_value=True)
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    def test_interact_google_maps_profile_actions_scrolls_to_top_and_clicks_action(
        self, mock_key, mock_tap, mock_swipe, mock_size, mock_sleep
    ):
        # Giả lập XML có nút "Đường đi" và "Chia sẻ"
        xml_actions = (
            '<hierarchy>'
            '<node text="Đường đi" bounds="[170,680][290,750]"/>'
            '<node text="Chia sẻ" bounds="[310,680][430,750]"/>'
            '</hierarchy>'
        )
        root = ET.fromstring(xml_actions)
        status_msgs = []
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root):
            res = self.adb.interact_google_maps_profile_actions(
                "dev_01",
                status_callback=lambda _d, m: status_msgs.append(m),
            )
            self.assertTrue(res)
            # Phải cuộn lên đỉnh trước
            self.assertTrue(mock_swipe.called)
            self.assertTrue(any("Cuộn về đầu trang" in msg for msg in status_msgs))
            # Phải bấm vào nút
            self.assertTrue(mock_tap.called)
            self.assertTrue(any("Bấm tương tác nút" in msg for msg in status_msgs))

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "lock_portrait", return_value=True)
    @patch.object(ADBController, "launch_chrome", return_value=True)
    @patch.object(ADBController, "ensure_chrome_ready", return_value=False)
    def test_workflow_fails_if_app_not_ready(self, mock_ready, mock_launch, mock_lock, mock_sleep):
        success, err = self.adb.google_maps_automation_workflow(
            "dev_01",
            keywords=["trị mụn"],
            target_name="Nhà thuốc Khải Hoàn Skincare",
        )
        self.assertFalse(success)
        self.assertIn("Không thể mở ứng dụng Google Chrome", err)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "lock_portrait", return_value=True)
    @patch.object(ADBController, "launch_chrome", return_value=True)
    @patch.object(ADBController, "ensure_chrome_ready", return_value=True)
    def test_workflow_aborts_immediately_if_cancelled(self, mock_ready, mock_launch, mock_lock, mock_sleep):
        cancelled = True
        success, err = self.adb.google_maps_automation_workflow(
            "dev_01",
            keywords=["trị mụn"],
            target_name="Nhà thuốc Khải Hoàn Skincare",
            is_cancelled=lambda: cancelled,
        )
        self.assertFalse(success)
        self.assertTrue("dừng" in err.lower())

    def test_parse_natural_command_maps(self):
        # Test default syntax
        cmd = main.parse_natural_command("/maps")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["action"], "google_maps_automation")
        self.assertFalse(cmd["is_sequential"])

        # Test full syntax with parameters
        cmd2 = main.parse_natural_command(
            "/maps chăm sóc da, trị mụn | Khải Hoàn Skincare | Lâm Đồng"
        )
        self.assertEqual(cmd2["action"], "google_maps_automation")
        self.assertEqual(cmd2["keywords"], "chăm sóc da, trị mụn")
        self.assertEqual(cmd2["target_name"], "Khải Hoàn Skincare")
        self.assertEqual(cmd2["locations"], "Lâm Đồng")

        # Test sequential syntax
        cmd3 = main.parse_natural_command("bơm google map tuần tự máy 2")
        self.assertTrue(cmd3["is_sequential"])
        self.assertEqual(cmd3["device_idx"], 2)


if __name__ == "__main__":
    unittest.main()
