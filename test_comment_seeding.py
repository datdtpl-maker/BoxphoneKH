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
        # blocks empty fallback to flat row
        mock_resp1 = MagicMock()
        mock_resp1.read.return_value = json.dumps(fake_data).encode("utf-8")
        mock_resp2 = MagicMock()
        mock_resp2.read.return_value = json.dumps({"results": []}).encode("utf-8")
        mock_urlopen.return_value.__enter__.side_effect = [mock_resp1, mock_resp2]

        tasks = notion_comment_sync.fetch_notion_comments("fake_tok", "fake_db")
        self.assertEqual(len(tasks), 1)
        t = tasks[0]
        self.assertEqual(t.stt, 1)
        self.assertEqual(t.content, "Serum này trị mụn thâm tốt không shop?")
        self.assertEqual(t.url, "https://www.tiktok.com/@khaihoanskincare.pt/video/123")
        self.assertEqual(t.platform, "TikTok")
        self.assertEqual(t.status, "Chưa comment")

    @patch("urllib.request.urlopen")
    def test_fetch_nested_table_skips_completed_comments(self, mock_urlopen):
        # 1. DB query
        db_data = {
            "results": [
                {
                    "id": "camp_page_1",
                    "properties": {
                        "Bài viết / video": {"title": [{"plain_text": "Chiến dịch Skincare"}]},
                        "Link bài đăng": {"url": "https://www.facebook.com/post/1"},
                        "Nền tảng": {"formula": {"string": "Facebook"}},
                        "Trạng thái": {"select": {"name": "Đang chạy"}},
                        "Số cmt dự kiến": {"number": 2},
                        "Đã đăng": {"number": 1},
                    },
                }
            ]
        }
        # 2. Blocks children (contains table)
        blocks_data = {
            "results": [
                {"type": "heading_2", "id": "h2_id"},
                {"type": "table", "id": "table_block_1"},
            ]
        }
        # 3. Table rows: Header + Row 1 (Hoàn thành) + Row 2 (Chưa comment)
        rows_data = {
            "results": [
                {
                    "id": "header_row",
                    "table_row": {
                        "cells": [
                            [{"plain_text": "STT"}],
                            [{"plain_text": "Nội dung bình luận"}],
                            [{"plain_text": "Trạng thái"}],
                            [{"plain_text": "Ai đăng"}],
                            [{"plain_text": "Thời gian hoàn thành"}],
                        ]
                    },
                },
                {
                    "id": "row_done",
                    "table_row": {
                        "cells": [
                            [{"plain_text": "1"}],
                            [{"plain_text": "Cmt đã xong trước đó"}],
                            [{"plain_text": "Hoàn thành"}],
                            [{"plain_text": "Máy 01"}],
                            [{"plain_text": "10:00 08/09/2026"}],
                        ]
                    },
                },
                {
                    "id": "row_pending",
                    "table_row": {
                        "cells": [
                            [{"plain_text": "2"}],
                            [{"plain_text": "Cmt đang chờ chạy"}],
                            [{"plain_text": "Chưa comment"}],
                            [{"plain_text": "—"}],
                            [{"plain_text": "—"}],
                        ]
                    },
                },
            ]
        }
        resp1 = MagicMock()
        resp1.read.return_value = json.dumps(db_data).encode("utf-8")
        resp2 = MagicMock()
        resp2.read.return_value = json.dumps(blocks_data).encode("utf-8")
        resp3 = MagicMock()
        resp3.read.return_value = json.dumps(rows_data).encode("utf-8")

        mock_urlopen.return_value.__enter__.side_effect = [resp1, resp2, resp3]

        tasks = notion_comment_sync.fetch_notion_comments("fake_tok", "fake_db", only_uncompleted=True)
        # Chỉ có Row 2 chưa comment được trả về, Row 1 đã hoàn thành bị bỏ qua!
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].stt, 2)
        self.assertEqual(tasks[0].content, "Cmt đang chờ chạy")
        self.assertEqual(tasks[0].status, "Chưa comment")
        self.assertEqual(tasks[0].row_id, "row_pending")
        self.assertEqual(tasks[0].platform, "Facebook")

    @patch("urllib.request.urlopen")
    def test_mark_nested_comment_completed(self, mock_urlopen):
        # PATCH row
        patch_row_resp = MagicMock()
        patch_row_resp.status = 200

        # GET page (for increment)
        page_resp = MagicMock()
        page_resp.read.return_value = json.dumps({
            "properties": {
                "Số cmt dự kiến": {"number": 1},
                "Đã đăng": {"number": 0},
            }
        }).encode("utf-8")

        # PATCH page
        patch_page_resp = MagicMock()
        patch_page_resp.status = 200

        mock_urlopen.return_value.__enter__.side_effect = [patch_row_resp, page_resp, patch_page_resp]

        task = notion_comment_sync.NotionCommentTask(
            page_id="camp_page_1",
            row_id="row_pending",
            table_id="table_1",
            stt=1,
            content="Cmt 1",
            url="https://facebook.com/1",
            platform="Facebook",
            status="Chưa comment",
            raw_cells=[
                [{"text": {"content": "1"}}],
                [{"text": {"content": "Cmt 1"}}],
                [{"text": {"content": "Chưa comment"}}],
                [{"text": {"content": "—"}}],
                [{"text": {"content": "—"}}],
            ],
            col_map={"stt": 0, "content": 1, "status": 2, "author": 3, "time": 4}
        )

        ok = notion_comment_sync.mark_notion_comment_completed(task, device_name="05", token="fake_tok")
        self.assertTrue(ok)
        self.assertEqual(mock_urlopen.call_count, 3)


class TestGUICommentSeedingIntegration(unittest.TestCase):
    def test_gui_has_comment_tab_and_attributes(self):
        import gui_app

        # Kiểm tra lớp GUIApp có đầy đủ các phương thức và thuộc tính bình luận
        self.assertTrue(hasattr(gui_app.GUIApp, "_on_click_scan_notion_comments"))
        self.assertTrue(hasattr(gui_app.GUIApp, "start_comment_seeding"))
        self.assertTrue(hasattr(gui_app.GUIApp, "stop_comment_seeding"))
        self.assertTrue(hasattr(gui_app.GUIApp, "_run_comment_seeding_worker"))
        self.assertTrue(hasattr(gui_app.GUIApp, "_on_comment_platform_changed"))
        self.assertTrue(hasattr(gui_app.GUIApp, "_on_comment_url_modified"))
        self.assertTrue(hasattr(gui_app.GUIApp, "_sync_comment_ui_for_platform"))

    def test_platform_filtering_and_task_building(self):
        t1 = notion_comment_sync.NotionCommentTask(
            page_id="p1", row_id="r1", stt=1, content="Cmt FB 1",
            url="https://facebook.com/1", platform="Facebook"
        )
        t2 = notion_comment_sync.NotionCommentTask(
            page_id="p1", row_id="r2", stt=2, content="Cmt FB 2",
            url="https://facebook.com/1", platform="Facebook"
        )
        t3 = notion_comment_sync.NotionCommentTask(
            page_id="p2", row_id="r3", stt=1, content="Cmt TT 1",
            url="https://tiktok.com/1", platform="TikTok"
        )
        all_tasks = [t1, t2, t3]

        # Test filter
        fb_tasks = comment_controller.filter_tasks_for_platform(all_tasks, "Facebook")
        self.assertEqual(len(fb_tasks), 2)
        self.assertTrue(all(t.platform == "Facebook" for t in fb_tasks))

        tt_tasks = comment_controller.filter_tasks_for_platform(all_tasks, "TikTok")
        self.assertEqual(len(tt_tasks), 1)
        self.assertEqual(tt_tasks[0].content, "Cmt TT 1")

        # Test build execution tasks
        exec_fb = comment_controller.build_execution_tasks(
            all_tasks, "Facebook", "https://facebook.com/1", ["Cmt FB 1", "Cmt FB 2"]
        )
        self.assertEqual(len(exec_fb), 2)
        self.assertEqual(exec_fb[0].row_id, "r1")
        self.assertEqual(exec_fb[1].row_id, "r2")

        # Never mix platforms
        self.assertTrue(all(t.platform == "Facebook" for t in exec_fb))


if __name__ == "__main__":
    unittest.main()
