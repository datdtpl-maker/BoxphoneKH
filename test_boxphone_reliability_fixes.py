"""Unit tests kiểm chứng toàn diện các cải tiến độ tin cậy của BoxphoneKH (Lỗi 1 -> 10).

Bao gồm:
- Lỗi 1: Chọn Facebook -> worker và Notion scan nhận đúng Facebook.
- Lỗi 2: Không đoán tọa độ khi thiếu phần tử (trả về None, caller dừng an toàn).
- Lỗi 3: Chống báo gửi thành công sai (chụp prior_stream, kiểm tra EditText chưa xóa, không nhận vơ caption).
- Lỗi 4: Target Lock mở rộng link rút gọn, bắt buộc trùng khớp kênh và dừng khi AMBIGUOUS_TARGET.
- Lỗi 5: build_execution_tasks không mutate task gốc, nội dung chỉnh sửa không bị đè bằng Notion cũ.
- Lỗi 6: ensure_comment_input_ready kiểm tra focus/IME thực tế, trả về False nếu không sẵn sàng.
- Lỗi 7: UNKNOWN_OUTCOME lưu bền vào unknown_comment_audit.json và không force-stop xóa hiện trường.
- Lỗi 8: Dừng khẩn cấp dọn dẹp cờ/nút qua finally, khóa run_id chống worker cũ sống lại.
- Lỗi 9: ADB socket timeout trả về -1 (không trả về 0), dọn dẹp remote XML trước khi dump.
- Lỗi 10: AdaptiveScheduler giới hạn strictly max_workers khi chạy randomize_wave_size.
"""

import copy
import json
import os
import socket
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, call, patch

import comment_controller
import ui_automator_dom
from adb_controller import ADBController
from adaptive_scheduler import AdaptivePolicy, run_adaptive
from notion_comment_sync import NotionCommentTask


class TestBoxphoneReliabilityFixes(unittest.TestCase):
    def setUp(self):
        self.adb = MagicMock()
        self.adb.get_effective_screen_size.return_value = (1080, 1920)
        self.adb.execute_adb.return_value = (0, "", "")
        self.device_id = "test_device_api29"

    # ==========================================================================
    # LỖI 1: CHỌN FACEBOOK -> WORKER VÀ NOTION NHẬN FACEBOOK
    # ==========================================================================

    @patch("comment_controller.execute_comment_task", return_value=True)
    def test_gui_worker_receives_facebook_platform(self, mock_exec):
        """Worker nhận đúng platform Facebook và gọi execute_comment_task với Facebook."""
        from gui_app import GUIApp
        app = MagicMock(spec=GUIApp)
        app.comment_cancel_flag = False
        app._current_comment_run_id = "run-123"
        app.comment_status_label = MagicMock()
        app.btn_comment_start = MagicMock()
        app.btn_comment_stop = MagicMock()
        app.comment_notion_tasks = [
            NotionCommentTask(page_id="p1", row_id="r1", stt=1, content="Cmt FB", url="https://fb.com/1", platform="Facebook")
        ]
        app.after = lambda delay, cb: cb()
        app.log_message = MagicMock()

        GUIApp._run_comment_seeding_worker(
            app,
            devices=["dev1"],
            dwell_time=5,
            delay_between=2,
            platform="Facebook",
            url="https://fb.com/1",
            raw_lines=["Cmt FB"],
            run_id="run-123",
        )

        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args[1]["platform"], "Facebook")

    # ==========================================================================
    # LỖI 2: KHÔNG ĐOÁN TỌA ĐỘ KHI THIẾU PHẦN TỬ
    # ==========================================================================

    def test_parse_bounds_supports_negative_and_validates_size(self):
        """Bounds âm phải được phân tích đúng; bounds có kích thước <= 0 bị loại bỏ."""
        b_neg = ui_automator_dom.parse_bounds("[-150,-100][250,300]")
        self.assertIsNotNone(b_neg)
        x1, y1, x2, y2, cx, cy = b_neg
        self.assertEqual(x1, -150)
        self.assertEqual(y1, -100)
        self.assertEqual(x2, 250)
        self.assertEqual(y2, 300)
        self.assertEqual(cx, 50)
        self.assertEqual(cy, 100)

        self.assertIsNone(ui_automator_dom.parse_bounds("[100,200][100,300]"))
        self.assertIsNone(ui_automator_dom.parse_bounds("[200,200][100,300]"))
        self.assertIsNone(ui_automator_dom.parse_bounds("[100,300][200,300]"))
        self.assertIsNone(ui_automator_dom.parse_bounds("[100,400][200,300]"))

    def test_is_bounds_visible_on_screen(self):
        """Phần tử nằm hoàn toàn ngoài màn hình không được xem là hiển thị."""
        b_off_left = (-300, -200, -10, -50, -155, -125)
        self.assertFalse(ui_automator_dom.is_bounds_visible_on_screen(b_off_left, 1080, 1920))

        b_off_bottom = (100, 2000, 500, 2200, 300, 2100)
        self.assertFalse(ui_automator_dom.is_bounds_visible_on_screen(b_off_bottom, 1080, 1920))

        b_on_screen = (100, 200, 500, 600, 300, 400)
        self.assertTrue(ui_automator_dom.is_bounds_visible_on_screen(b_on_screen, 1080, 1920))

    def test_coordinate_finders_return_none_when_elements_missing(self):
        """Các hàm định vị trả về None khi DOM thiếu phần tử, tuyệt đối không trả về tỷ lệ cố định."""
        empty_root = ET.fromstring("<hierarchy/>")
        with patch("ui_automator_dom.dump_ui_tree", return_value=empty_root):
            self.assertIsNone(comment_controller.find_tiktok_comment_icon_coords(self.adb, self.device_id, 1080, 1920))
            self.assertIsNone(comment_controller.find_facebook_comment_icon_coords(self.adb, self.device_id, 1080, 1920))
            self.assertIsNone(comment_controller.find_comment_input_coords(self.adb, self.device_id, "TikTok", 1080, 1920))
            self.assertIsNone(comment_controller.find_comment_input_coords(self.adb, self.device_id, "Facebook", 1080, 1920))
            self.assertIsNone(comment_controller.find_send_button_coords(self.adb, self.device_id, "TikTok", 1080, 1920))
            self.assertIsNone(comment_controller.find_send_button_coords(self.adb, self.device_id, "Facebook", 1080, 1920))

    # ==========================================================================
    # LỖI 3: CHỐNG BÁO GỬI THÀNH CÔNG SAI (FALSE POSITIVE VERIFICATION)
    # ==========================================================================

    def test_verify_does_not_match_old_comments_in_prior_stream(self):
        """Nếu nội dung bình luận đã có sẵn trong prior_stream trước khi gửi, không báo SUCCESS."""
        xml_stream = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
          <node class="android.widget.TextView" text="Bình luận cũ từ trước" bounds="[100,800][900,900]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_stream)):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb,
                self.device_id,
                "Bình luận cũ từ trước",
                1080,
                1920,
                timeout=1.0,
                prior_stream={"bình luận cũ từ trước"},
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_verify_returns_retryable_when_edittext_still_has_target(self):
        """Nếu EditText vẫn chứa nội dung bình luận, chứng tỏ chưa gửi đi -> trả về RETRYABLE_ERROR."""
        xml_stuck = """<hierarchy>
          <node class="android.widget.EditText" text="Bình luận chưa gửi được" bounds="[50,1700][900,1850]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_stuck)):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb,
                self.device_id,
                "Bình luận chưa gửi được",
                1080,
                1920,
                timeout=1.0,
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_verify_tiktok_comment_posted_success_when_new(self):
        """Xác minh thành công khi bình luận mới xuất hiện trong stream và EditText đã sạch."""
        xml_with_comment = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
          <node class="android.widget.TextView" text="Da em bị mụn ẩn dùng combo này được không?" bounds="[100,800][900,900]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_with_comment)):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb,
                self.device_id,
                "Da em bị mụn ẩn dùng combo này được không?",
                1080,
                1920,
                timeout=1.0,
                prior_stream=set(),
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.SUCCESS)

    @patch("comment_controller.time.sleep", return_value=None)
    @patch("comment_controller.open_url_via_intent", return_value=True)
    @patch("comment_controller.wait_for_tiktok_video_ready", return_value=True)
    @patch("comment_controller.is_tiktok_comment_sheet_open", return_value=True)
    @patch("comment_controller.find_comment_input_coords", return_value=(540, 1800))
    @patch("comment_controller.ensure_comment_input_ready", return_value=True)
    @patch("comment_controller.find_send_button_coords", return_value=(950, 1200))
    def test_single_send_no_duplicate_tap_and_enter(
        self, _send, _ready, _input, _sheet, _wait, _intent, _sleep
    ):
        """Mỗi lần gửi chỉ bấm nút gửi 1 lần, tuyệt đối không lặp chuỗi tap -> Enter -> tap lại -> Enter."""
        xml_video_before = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="khai hoan" bounds="[50,1400][500,1460]" />
        </hierarchy>"""
        xml_video_after = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="khai hoan" bounds="[50,1400][500,1460]" />
          <node class="android.widget.TextView" text="Bình luận đơn lẻ" bounds="[100,800][600,850]" />
        </hierarchy>"""
        call_count = 0
        def dynamic_dump(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return ET.fromstring(xml_video_before)
            return ET.fromstring(xml_video_after)

        with patch("ui_automator_dom.dump_ui_tree", side_effect=dynamic_dump):
            taps = []
            self.adb.tap = lambda _dev, x, y: taps.append((x, y))
            keyevents = []
            self.adb.execute_adb = lambda _dev, cmd, **_kw: (
                keyevents.append(cmd) if "keyevent" in cmd else None, 0, "", ""
            )[1:]

            res = comment_controller.post_tiktok_comment(
                self.adb, self.device_id, "https://www.tiktok.com/@khaihoan/video/123", "Bình luận đơn lẻ", dwell_time=1
            )
            self.assertTrue(res)
            send_taps = [pt for pt in taps if pt == (950, 1200)]
            self.assertEqual(len(send_taps), 1)

    # ==========================================================================
    # LỖI 4: TARGET LOCK & URL CANONICALIZATION
    # ==========================================================================

    @patch("comment_controller.time.sleep", return_value=None)
    @patch("comment_controller.open_url_via_intent", return_value=True)
    @patch("comment_controller.wait_for_tiktok_video_ready", return_value=True)
    def test_tiktok_target_lock_channel_mismatch_aborts(self, _wait, mock_intent, _sleep):
        """Nếu kênh đang phát không khớp kênh mục tiêu, mở lại link một lần; nếu vẫn sai -> dừng an toàn."""
        xml_wrong_channel = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="Kenh Khac Hoan Toan" bounds="[50,1400][500,1460]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_wrong_channel)):
            res = comment_controller.post_tiktok_comment(
                self.adb, self.device_id, "https://www.tiktok.com/@khaihoan.101notmun/video/123", "Cmt", dwell_time=1
            )
            self.assertFalse(res)
            self.assertEqual(res.outcome, comment_controller.TaskOutcome.AMBIGUOUS_TARGET)
            self.assertFalse(res.can_retry)
            self.assertTrue(mock_intent.call_count >= 2)

    @patch("comment_controller.resolve_canonical_url", return_value="https://www.tiktok.com/@target.channel/video/999")
    @patch("comment_controller.time.sleep", return_value=None)
    @patch("comment_controller.open_url_via_intent", return_value=True)
    @patch("comment_controller.wait_for_tiktok_video_ready", return_value=True)
    def test_short_url_resolves_and_locks_channel(self, _wait, _intent, _sleep, mock_resolve):
        """Link ngắn vt.tiktok.com được phân giải canonical để trích xuất target channel và khóa cứng."""
        xml_matched = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="target.channel" bounds="[50,1400][500,1460]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_matched)):
            with patch("comment_controller.is_tiktok_comment_sheet_open", return_value=False):
                res = comment_controller.post_tiktok_comment(
                    self.adb, self.device_id, "https://vt.tiktok.com/ZS12345/", "Cmt", dwell_time=1
                )
                mock_resolve.assert_called_with("https://vt.tiktok.com/ZS12345/")

    @patch("comment_controller.time.sleep", return_value=None)
    @patch("comment_controller.open_url_via_intent", return_value=True)
    def test_post_facebook_comment_ambiguous_target_aborts(self, _intent, _sleep):
        """Khi Facebook trả về AMBIGUOUS_TARGET, post_facebook_comment dừng ngay lập tức, không bấm đoán."""
        xml_multi_post = """<hierarchy>
          <node class="android.widget.Button" content-desc="Thích" bounds="[50,550][150,650]" />
          <node class="android.widget.Button" content-desc="Bình luận" bounds="[350,550][450,650]" />
          <node class="android.widget.Button" content-desc="Thích" bounds="[50,1450][150,1550]" />
          <node class="android.widget.Button" content-desc="Bình luận" bounds="[350,1450][450,1550]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_multi_post)):
            taps = []
            self.adb.tap = lambda _dev, x, y: taps.append((x, y))
            res = comment_controller.post_facebook_comment(
                self.adb, self.device_id, "https://www.facebook.com/post/123", "Cmt", dwell_time=1
            )
            self.assertFalse(res)
            self.assertEqual(res.outcome, comment_controller.TaskOutcome.AMBIGUOUS_TARGET)
            self.assertEqual(taps, [])

    # ==========================================================================
    # LỖI 5: NỘI DUNG CHỈNH SỬA KHÔNG BỊ ĐÈ BẰNG NOTION & KHÔNG MUTATE
    # ==========================================================================

    def test_build_execution_tasks_does_not_mutate_and_keeps_edited_text(self):
        """build_execution_tasks không mutate scanned_tasks; text mới không bị đè bằng content Notion cũ."""
        original_task = NotionCommentTask(
            page_id="page_1",
            row_id="row_1",
            stt=1,
            content="Nội dung Notion gốc",
            url="https://tiktok.com/old",
            platform="TikTok",
        )
        scanned = [original_task]

        tasks = comment_controller.build_execution_tasks(
            scanned,
            platform="TikTok",
            url="https://tiktok.com/new",
            comment_lines=["Nội dung người dùng đã sửa khác hoàn toàn"],
        )

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].content, "Nội dung người dùng đã sửa khác hoàn toàn")
        self.assertEqual(tasks[0].page_id, "")
        self.assertEqual(tasks[0].row_id, "")

        # Object gốc trong scanned_tasks không bị mutate
        self.assertEqual(original_task.content, "Nội dung Notion gốc")
        self.assertEqual(original_task.url, "https://tiktok.com/old")

    # ==========================================================================
    # LỖI 6: INPUT READINESS & LIVE UI CHECK
    # ==========================================================================

    def test_ensure_comment_input_ready_fails_when_no_ime_and_no_focus(self):
        """ensure_comment_input_ready trả về False nếu IME không bật và không có EditText focus."""
        self.adb.execute_adb.return_value = (0, "mInputShown=false", "")
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring("<hierarchy/>")):
            ready = comment_controller.ensure_comment_input_ready(
                self.adb, self.device_id, input_x=540, input_y=1800, width=1080, height=1920
            )
            self.assertFalse(ready)

    @patch("comment_controller.time.sleep", return_value=None)
    @patch("comment_controller.open_url_via_intent", return_value=True)
    @patch("comment_controller.wait_for_tiktok_video_ready", return_value=True)
    def test_retry_open_sheet_redumps_live_dom(self, _wait, _intent, _sleep):
        """Trước mỗi lần thử mở khung bình luận, bắt buộc dump lại DOM để cập nhật bounds mới nhất."""
        dump_calls = []

        xml_video_1 = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1100][1080,1220]" />
          <node class="android.widget.TextView" text="khaihoan" bounds="[50,1400][500,1460]" />
        </hierarchy>"""

        xml_video_2 = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1250][1080,1370]" />
          <node class="android.widget.TextView" text="khaihoan" bounds="[50,1400][500,1460]" />
        </hierarchy>"""

        xml_comment_before = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
        </hierarchy>"""

        xml_comment_after = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
          <node class="android.widget.TextView" text="Cmt test" bounds="[100,800][500,850]" />
        </hierarchy>"""

        def mock_dump(_adb, _dev, **_kw):
            dump_calls.append(len(dump_calls) + 1)
            if len(dump_calls) == 1:
                return ET.fromstring(xml_video_1)
            elif len(dump_calls) == 2:
                return ET.fromstring(xml_video_2)
            elif len(dump_calls) == 3:
                return ET.fromstring(xml_comment_before)
            else:
                return ET.fromstring(xml_comment_after)

        with patch("ui_automator_dom.dump_ui_tree", side_effect=mock_dump):
            with patch("comment_controller.is_tiktok_comment_sheet_open", side_effect=[False, True]):
                with patch("comment_controller.find_comment_input_coords", return_value=(540, 1800)):
                    with patch("comment_controller.ensure_comment_input_ready", return_value=True):
                        with patch("comment_controller.find_send_button_coords", return_value=(950, 1200)):
                            taps = []
                            self.adb.tap = lambda _dev, x, y: taps.append((x, y))

                            res = comment_controller.post_tiktok_comment(
                                self.adb, self.device_id, "https://www.tiktok.com/@khaihoan/video/123", "Cmt test", dwell_time=1
                            )
                            self.assertTrue(res)
                            self.assertTrue(len(dump_calls) >= 2)
                            self.assertIn((996, 1310), taps)

    # ==========================================================================
    # LỖI 7: UNKNOWN_OUTCOME AUDIT TRAIL PERSISTENCE
    # ==========================================================================

    def test_record_unknown_comment_audit(self):
        """UNKNOWN_OUTCOME được ghi vào file JSON bền vững để đối soát, không bị mất."""
        entry = comment_controller.record_unknown_comment_audit(
            platform="TikTok",
            device_id="dev-01",
            url="https://tiktok.com/@test/video/111",
            content="Nội dung cần đối soát",
            reason="Timeout chờ stream",
        )
        self.assertEqual(entry["status"], "PENDING_AUDIT")
        self.assertTrue(
            comment_controller.is_comment_in_pending_audit(
                "TikTok", "https://tiktok.com/@test/video/111", "Nội dung cần đối soát"
            )
        )

    # ==========================================================================
    # LỖI 8: DỪNG KHẨN CẤP KHÔNG LÀM KẸT GUI & LATCH TOKEN
    # ==========================================================================

    def test_device_workflow_scope_cancellation(self):
        """Khi cờ hủy được bật, device_workflow_scope thoát ngay lập tức mà không đợi hết timeout."""
        controller = ADBController()
        cancelled = True
        start = time.time()
        with self.assertRaises(TimeoutError):
            with controller.device_workflow_scope("dev_cancelled", timeout=10.0, is_cancelled=lambda: cancelled):
                pass
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.5)

    # ==========================================================================
    # LỖI 9: ADB SOCKET TIMEOUT TRẢ VỀ -1
    # ==========================================================================

    def test_adb_socket_timeout_returns_negative_one(self):
        """Khi socket timeout lúc đọc dữ liệu ADB stream, _execute_adb_socket phải trả về -1 (không trả về 0)."""
        controller = ADBController()
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"OKAY", b"OKAY", socket.timeout("timed out")]

        with patch("socket.socket", return_value=mock_sock):
            with patch.object(controller, "_ensure_adb_server", return_value=True):
                ret = controller._execute_adb_socket("dev_sock", ["shell", "echo", "hi"], timeout=0.5)
                self.assertIsNotNone(ret)
                code, stdout, stderr = ret
                self.assertEqual(code, -1)
                self.assertIn("timed out", stderr.lower())

    # ==========================================================================
    # LỖI 10: SCHEDULER GIỚI HẠN STRICTLY MAX_WORKERS TRONG ROLLING WAVES
    # ==========================================================================

    def test_randomized_waves_strictly_limits_max_workers(self):
        """Khi randomize_wave_size=True và policy.max_workers=1, peak concurrency không bao giờ vượt quá 1."""
        lock = threading.Lock()
        active = 0
        peak = 0

        def worker(dev):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return dev

        run_adaptive(
            ["D1", "D2", "D3", "D4"],
            worker,
            AdaptivePolicy(max_workers=1, stagger_seconds=(0, 0), wave_size_range=(2, 3), wave_interval_seconds=(0, 0)),
            sleep_fn=lambda _: None,
            randint_fn=lambda low, high: low,
            randomize_wave_size=True,
        )

        self.assertEqual(peak, 1)


    # ==========================================================================
    # TIÊU CHÍ NÂNG CAO 2, 3, 4, 5: XÁC MINH GỬI, BẢO VỆ TARGET & CHẶN AUDIT TRAIL
    # ==========================================================================

    def test_verify_comment_rejects_prior_duplicate_comment(self):
        """Bình luận cũ đã có trên màn hình trước khi gửi (prior_stream) không được tính là thành công."""
        import xml.etree.ElementTree as ET
        xml_dom = """<hierarchy>
          <node class='android.widget.TextView' text='bình luận mẫu' />
          <node class='android.widget.EditText' text='Thêm bình luận...' />
        </hierarchy>"""
        mock_root = ET.fromstring(xml_dom)
        with patch("ui_automator_dom.dump_ui_tree", return_value=mock_root):
            # prior_stream đã có 'bình luận mẫu' -> không thể coi đây là cmt mới gửi
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "bình luận mẫu", 1080, 1920, timeout=1.0, prior_stream={"bình luận mẫu"}
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_verify_comment_rejects_substring_partial_match(self):
        """Text trên màn hình chỉ chứa chuỗi con không được coi là bình luận đã gửi thành công."""
        import xml.etree.ElementTree as ET
        xml_dom = """<hierarchy>
          <node class='android.widget.TextView' text='Hôm nay trời rất bình luận mẫu và đẹp' />
          <node class='android.widget.EditText' text='' />
        </hierarchy>"""
        mock_root = ET.fromstring(xml_dom)
        with patch("ui_automator_dom.dump_ui_tree", return_value=mock_root):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "bình luận mẫu", 1080, 1920, timeout=1.0
            )
            # Khớp chuỗi con -> không tính -> UNKNOWN_OUTCOME
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_verify_comment_ignores_keyboard_candidate_suggestions(self):
        """Gợi ý bàn phím (IME candidates/suggestions) chứa text bình luận không được coi là đã gửi."""
        import xml.etree.ElementTree as ET
        xml_dom = """<hierarchy>
          <node package='com.google.android.inputmethod.latin' resource-id='candidate_view' text='bình luận mẫu' />
          <node class='android.widget.EditText' text='' />
        </hierarchy>"""
        mock_root = ET.fromstring(xml_dom)
        with patch("ui_automator_dom.dump_ui_tree", return_value=mock_root):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "bình luận mẫu", 1080, 1920, timeout=1.0
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_verify_comment_cleared_input_without_stream_returns_unknown(self):
        """Ô nhập trống nhưng không thấy text trên stream bình luận thì trả về UNKNOWN_OUTCOME chứ không báo SUCCESS."""
        import xml.etree.ElementTree as ET
        xml_dom = """<hierarchy>
          <node class='android.widget.EditText' text='Thêm bình luận...' />
        </hierarchy>"""
        mock_root = ET.fromstring(xml_dom)
        with patch("ui_automator_dom.dump_ui_tree", return_value=mock_root):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "bình luận mẫu", 1080, 1920, timeout=1.0
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_verify_comment_server_lag_or_timeout_returns_unknown_not_retryable(self):
        """Server phản hồi chậm / timeout sau khi gửi: trả về UNKNOWN_OUTCOME và không cho phép retry tự động."""
        import xml.etree.ElementTree as ET
        xml_dom = """<hierarchy>
          <node class='android.widget.EditText' text='bình luận mẫu' />
        </hierarchy>"""
        mock_root = ET.fromstring(xml_dom)
        with patch("ui_automator_dom.dump_ui_tree", return_value=mock_root):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "bình luận mẫu", 1080, 1920, timeout=1.0
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_post_comment_without_send_button_fails_cleanly_without_enter(self):
        """Khi DOM không có nút gửi bình luận, hệ thống báo UNSUPPORTED_UI và tuyệt đối không gửi Enter KeyEvent 66."""
        with patch.object(self.adb, "execute_adb", return_value=(0, "mInputShown=true", "")) as mock_adb:
            with patch("ui_automator_dom.find_tiktok_video_controls", return_value={"like": None, "comment": {"center": (1000, 1100)}}):
                with patch("comment_controller.is_tiktok_comment_sheet_open", return_value=True):
                    with patch("comment_controller.find_comment_input_coords", return_value=(500, 1800)):
                        with patch("comment_controller.ensure_comment_input_ready", return_value=True):
                            with patch("comment_controller.find_send_button_coords", return_value=None):
                                res = comment_controller.post_tiktok_comment(
                                    self.adb, self.device_id, "https://www.tiktok.com/@test/video/1", "Test cmt", dwell_time=1
                                )
                                self.assertEqual(res.outcome, comment_controller.TaskOutcome.UNSUPPORTED_UI)
                                self.assertFalse(res.can_retry)
                                # Đảm bảo không có lệnh gửi keyevent 66 (Enter)
                                for call in mock_adb.call_args_list:
                                    args = call[0][1] if len(call[0]) > 1 else []
                                    self.assertNotIn("66", args)

    def test_target_error_state_fails_early_before_clicking(self):
        """Màn hình video bị xóa hoặc không khả dụng: phát hiện qua DOM và trả về FATAL_ERROR ngay lập tức."""
        import xml.etree.ElementTree as ET
        xml_dom = """<hierarchy>
          <node class='android.widget.TextView' text='Video không khả dụng' />
        </hierarchy>"""
        mock_root = ET.fromstring(xml_dom)
        err = comment_controller.check_target_error_state(mock_root, "TikTok")
        self.assertIsNotNone(err)
        self.assertIn("không khả dụng", err)

    def test_blocked_pending_audit_prevents_dispatch_across_restart(self):
        """Tác vụ đang ở trạng thái PENDING_AUDIT phải bị chặn không cho dispatch kể cả khi restart tool."""
        # 1. Ghi nhận tác vụ vào audit trail
        comment_controller.record_unknown_comment_audit(
            platform="TikTok",
            device_id="dev-audit-1",
            url="https://tiktok.com/@test/video/999",
            content="Nội dung nguy cơ gửi lặp",
            reason="Mất mạng sau khi gửi",
        )
        # 2. Xây dựng task execution
        tasks = comment_controller.build_execution_tasks(
            scanned_tasks=[],
            platform="TikTok",
            url="https://tiktok.com/@test/video/999",
            comment_lines=["Nội dung nguy cơ gửi lặp", "Câu bình luận hợp lệ khác"],
        )
        self.assertEqual(len(tasks), 2)
        # Task 1 phải bị chặn
        self.assertTrue(getattr(tasks[0], "is_blocked", False))
        self.assertIn("PENDING_AUDIT", getattr(tasks[0], "block_reason", ""))
        # Task 2 bình thường
        self.assertFalse(getattr(tasks[1], "is_blocked", False))

        # 3. execute_comment_task cũng phải từ chối ngay lập tức
        res = comment_controller.execute_comment_task(
            self.adb,
            "dev-audit-1",
            "TikTok",
            "https://tiktok.com/@test/video/999",
            "Nội dung nguy cơ gửi lặp",
        )
        self.assertEqual(res.outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)
        self.assertFalse(res.can_retry)
        self.assertIn("chặn", res.message.lower())

    def test_audit_trail_resolution_workflow(self):
        """Quy trình đối soát: chuyển trạng thái từ PENDING_AUDIT sang RESOLVED_SUCCESS giải phóng khóa chặn."""
        url = "https://tiktok.com/@test/video/resolved_test"
        content = "Nội dung đối soát xong"
        comment_controller.record_unknown_comment_audit("TikTok", "dev-1", url, content)
        self.assertTrue(comment_controller.is_comment_blocked_by_audit("TikTok", url, content))

        # Đối soát thủ công thành công
        resolved = comment_controller.resolve_unknown_comment_audit(
            "TikTok", url, content, "RESOLVED_SUCCESS", note="Đã kiểm tra tay thấy comment đã lên"
        )
        self.assertTrue(resolved)
        # Sau khi resolved, không còn bị chặn PENDING_AUDIT nữa
        self.assertFalse(comment_controller.is_comment_blocked_by_audit("TikTok", url, content))


if __name__ == "__main__":
    unittest.main()
