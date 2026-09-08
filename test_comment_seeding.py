"""Unit tests cho phân hệ Bơm Bình Luận (Comment Seeding) và Đồng Bộ Notion."""

import io
import json
import unittest
from unittest.mock import MagicMock, patch

import comment_controller
import notion_comment_sync


class TestCommentController(unittest.TestCase):
    def setUp(self):
        self.adb = MagicMock()
        self.adb.get_effective_screen_size.return_value = (1080, 1920)
        self.adb.execute_adb.return_value = (0, "", "")
        self.adb.find_element_coords_by_text.return_value = None
        self.device_id = "device_test_1"

    def test_resolve_canonical_url_non_http(self):
        url = "invalid-url"
        self.assertEqual(comment_controller.resolve_canonical_url(url), "invalid-url")

    def test_resolve_canonical_url_empty(self):
        self.assertEqual(comment_controller.resolve_canonical_url(""), "")

    @patch("urllib.request.urlopen")
    def test_resolve_canonical_url_redirect(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.geturl.return_value = "https://www.tiktok.com/@khaihoan/video/123456"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = comment_controller.resolve_canonical_url("https://vt.tiktok.com/ZSabc/")
        self.assertEqual(res, "https://www.tiktok.com/@khaihoan/video/123456")

    def test_open_url_via_intent_tiktok(self):
        self.adb.execute_adb.return_value = (0, "", "")
        res = comment_controller.open_url_via_intent(
            self.adb, self.device_id, "https://www.tiktok.com/@a/video/1", "TikTok"
        )
        self.assertTrue(res)
        calls = self.adb.execute_adb.call_args_list
        self.assertTrue(len(calls) >= 1)
        first_cmd = calls[0][0][1]
        self.assertIn("am", first_cmd)
        self.assertIn("android.intent.action.VIEW", first_cmd)
        self.assertIn("com.ss.android.ugc.trill", first_cmd)
        self.assertIn("--es", first_cmd)
        self.assertIn("android.intent.extra.REFERRER_NAME", first_cmd)

    def test_open_url_via_intent_facebook(self):
        self.adb.execute_adb.return_value = (0, "", "")
        res = comment_controller.open_url_via_intent(
            self.adb, self.device_id, "https://www.facebook.com/reel/123", "Facebook"
        )
        self.assertTrue(res)
        calls = self.adb.execute_adb.call_args_list
        first_cmd = calls[0][0][1]
        self.assertIn("com.facebook.katana", first_cmd)

    @patch("time.sleep", return_value=None)
    def test_post_tiktok_comment_flow(self, _mock_sleep):
        status_msgs = []
        res = comment_controller.post_tiktok_comment(
            self.adb,
            self.device_id,
            "https://www.tiktok.com/@a/video/1",
            "Sản phẩm rất tốt!",
            dwell_time=1,
            status_callback=status_msgs.append,
        )
        self.assertTrue(res)
        self.adb.input_text.assert_called_with(self.device_id, "Sản phẩm rất tốt!")
        self.assertTrue(any("thành công" in msg for msg in status_msgs))

    @patch("time.sleep", return_value=None)
    def test_post_facebook_comment_flow(self, _mock_sleep):
        status_msgs = []
        res = comment_controller.post_facebook_comment(
            self.adb,
            self.device_id,
            "https://www.facebook.com/post/123",
            "Tư vấn cho mình với nha!",
            dwell_time=1,
            status_callback=status_msgs.append,
        )
        self.assertTrue(res)
        self.adb.input_text.assert_called_with(self.device_id, "Tư vấn cho mình với nha!")
        self.adb.keyevent.assert_called_with(self.device_id, 4)

    @patch("time.sleep", return_value=None)
    def test_comment_cancelled_early(self, _mock_sleep):
        res = comment_controller.post_tiktok_comment(
            self.adb,
            self.device_id,
            "https://www.tiktok.com/@a/video/1",
            "Bình luận test",
            dwell_time=1,
            is_cancelled=lambda: True,
        )
        self.assertFalse(res)


class TestNotionCommentSync(unittest.TestCase):
    def test_detect_platform_from_url(self):
        self.assertEqual(
            notion_comment_sync.detect_platform_from_url("https://www.tiktok.com/@khaihoan/video/123"),
            "TikTok",
        )
        self.assertEqual(
            notion_comment_sync.detect_platform_from_url("https://www.facebook.com/reel/456"),
            "Facebook",
        )
        self.assertEqual(
            notion_comment_sync.detect_platform_from_url("https://fb.watch/abc/"),
            "Facebook",
        )
        self.assertEqual(
            notion_comment_sync.detect_platform_from_url("https://example.com/other"),
            "Khác",
        )

    @patch("urllib.request.urlopen")
    def test_fetch_notion_comments_success(self, mock_urlopen):
        fake_data = {
            "results": [
                {
                    "id": "page_id_123",
                    "properties": {
                        "STT": {"number": 1},
                        "Nội dung comment": {
                            "title": [{"plain_text": "Serum này trị mụn thâm tốt không shop?"}]
                        },
                        "Link bài đăng": {
                            "url": "https://www.tiktok.com/@khaihoanskincare.pt/video/123"
                        },
                        "Nền tảng": {
                            "formula": {"string": "TikTok"}
                        },
                        "Trạng thái": {
                            "select": {"name": "Chưa comment"}
                        },
                        "Thời gian hoàn thành": {
                            "rich_text": []
                        },
                    },
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        tasks = notion_comment_sync.fetch_notion_comments("fake_tok", "fake_db")
        self.assertEqual(len(tasks), 1)
        t = tasks[0]
        self.assertEqual(t.stt, 1)
        self.assertEqual(t.content, "Serum này trị mụn thâm tốt không shop?")
        self.assertEqual(t.url, "https://www.tiktok.com/@khaihoanskincare.pt/video/123")
        self.assertEqual(t.platform, "TikTok")
        self.assertEqual(t.status, "Chưa comment")

    @patch("urllib.request.urlopen")
    def test_mark_notion_comment_completed(self, mock_urlopen):
        mock_patch_resp = MagicMock()
        mock_patch_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_patch_resp

        ok = notion_comment_sync.mark_notion_comment_completed(
            page_id="page_id_123",
            device_name="01",
            token="fake_tok",
        )
        self.assertTrue(ok)
        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.method, "PATCH")
        self.assertIn("page_id_123", req.full_url)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["properties"]["Trạng thái"]["select"]["name"], "Hoàn thành")
        self.assertIn("Máy 01 lúc", body["properties"]["Thời gian hoàn thành"]["rich_text"][0]["text"]["content"])


class TestGUICommentSeedingIntegration(unittest.TestCase):
    def test_gui_has_comment_tab_and_attributes(self):
        import gui_app

        # Kiểm tra lớp GUIApp có đầy đủ các phương thức và thuộc tính bình luận
        self.assertTrue(hasattr(gui_app.GUIApp, "_on_click_scan_notion_comments"))
        self.assertTrue(hasattr(gui_app.GUIApp, "start_comment_seeding"))
        self.assertTrue(hasattr(gui_app.GUIApp, "stop_comment_seeding"))
        self.assertTrue(hasattr(gui_app.GUIApp, "_run_comment_seeding_worker"))


if __name__ == "__main__":
    unittest.main()
