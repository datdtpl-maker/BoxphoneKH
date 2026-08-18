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
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "clear_input_field", return_value=True)
    @patch.object(ADBController, "input_text", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    def test_find_and_search_chrome_homepage(self, mock_key, mock_input, mock_clear, mock_tap, mock_size, mock_sleep):
        # Giả lập XML Trang chủ Chrome
        xml_home = '<hierarchy><node text="Tìm kiếm hoặc nhập URL" bounds="[60,340][660,420]"/></hierarchy>'
        root_home = ET.fromstring(xml_home)
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root_home):
            res = self.adb.find_and_search_chrome("dev_01", "kem chống nắng")
            self.assertTrue(res)
            self.assertTrue(mock_tap.called)
            self.assertTrue(mock_clear.called)
            self.assertTrue(mock_input.called)
            mock_key.assert_called_with("dev_01", 66)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "clear_input_field", return_value=True)
    @patch.object(ADBController, "input_text", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    def test_find_and_search_chrome_search_results_page_clears_old_keyword(self, mock_key, mock_input, mock_clear, mock_tap, mock_size, mock_sleep):
        # Giả lập XML Trang kết quả tìm kiếm (có tab Tất cả và nút Xóa)
        xml_res = '<hierarchy><node text="Tất cả" bounds="[50,380][150,420]"/><node content-desc="Xóa cụm từ tìm kiếm" bounds="[480,280][540,340]"/></hierarchy>'
        root_res = ET.fromstring(xml_res)
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root_res):
            status_msgs = []
            res = self.adb.find_and_search_chrome("dev_01", "trị mụn Khải Hoàn", status_callback=lambda _d, m: status_msgs.append(m))
            self.assertTrue(res)
            self.assertTrue(any("Xóa sạch từ khóa cũ" in msg or "xóa sạch" in msg.lower() for msg in status_msgs))
            self.assertTrue(mock_tap.called)
            self.assertTrue(mock_clear.called)
            self.assertTrue(mock_input.called)
            mock_key.assert_called_with("dev_01", 66)

    @patch("time.sleep", return_value=None)
    @patch.object(ADBController, "get_effective_screen_size", return_value=(720, 1280))
    @patch.object(ADBController, "tap", return_value=True)
    @patch.object(ADBController, "clear_input_field", return_value=True)
    @patch.object(ADBController, "input_text", return_value=True)
    @patch.object(ADBController, "keyevent", return_value=True)
    def test_find_and_search_chrome_place_detail_page_clicks_top_url_bar(self, mock_key, mock_input, mock_clear, mock_tap, mock_size, mock_sleep):
        # Giả lập XML Trang chi tiết Profile (như ảnh Bắp Spa - Phan Thiết có Tổng quan, Bài đánh giá, Gọi điện...)
        xml_place = (
            '<hierarchy>'
            '<node resource-id="com.android.chrome:id/url_bar" text="google.com/search?q=..." bounds="[100,60][620,130]"/>'
            '<node text="Bắp Spa - Phan Thiết" bounds="[40,200][500,250]"/>'
            '<node text="Tổng quan" bounds="[40,280][200,340]"/>'
            '<node text="Bài đánh giá" bounds="[220,280][400,340]"/>'
            '<node text="Ảnh" bounds="[420,280][540,340]"/>'
            '<node text="Gọi điện" bounds="[40,550][180,620]"/>'
            '</hierarchy>'
        )
        root_place = ET.fromstring(xml_place)
        status_msgs = []
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root_place):
            res = self.adb.find_and_search_chrome("dev_01", "kem mụn Khải Hoàn", status_callback=lambda _d, m: status_msgs.append(m))
            self.assertTrue(res)
            # Kiểm tra tap vào thanh URL bar trên cùng ((100+620)//2 = 360, (60+130)//2 = 95)
            mock_tap.assert_called_once_with("dev_01", 360, 95)
            self.assertTrue(any("thanh URL trên cùng" in msg for msg in status_msgs))
            self.assertTrue(mock_clear.called)
            self.assertTrue(mock_input.called)
            mock_key.assert_called_with("dev_01", 66)

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
        with patch.object(ADBController, "_get_maps_ui_root", return_value=root):
            found = self.adb.find_and_click_google_maps_target(
                "dev_01",
                target_names=["Nhà thuốc Khải Hoàn Skincare", "Khải Hoàn Skincare"],
                status_callback=lambda _d, m: status_msgs.append(m),
            )
            self.assertTrue(found)
            # Kiểm tra tap vào tọa độ của "Nhà thuốc Khải Hoàn Skincare - S..." (x=(40+600)//2=320, y=(540+590)//2=565)
            mock_tap.assert_called_once_with("dev_01", 320, 565)
            self.assertTrue(any("Đã tìm thấy đúng profile" in msg for msg in status_msgs))
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
        with patch.object(ADBController, "_get_maps_ui_root", side_effect=[root1, root2]):
            found = self.adb.find_and_click_google_maps_target(
                "dev_01",
                target_names=["Nhà thuốc Khải Hoàn Skincare"],
                status_callback=lambda _d, m: status_msgs.append(m),
            )
            self.assertTrue(found)
            self.assertTrue(any("Doanh nghiệp khác" in msg for msg in status_msgs))
            self.assertTrue(any("Đã tìm thấy đúng profile" in msg for msg in status_msgs))

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
