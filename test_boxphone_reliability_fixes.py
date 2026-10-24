"""Unit tests kiểm chứng toàn diện các cải tiến độ tin cậy của BoxphoneKH (Lỗi A -> F).

Bao gồm:
- Lỗi A: Không đoán tọa độ khi DOM rỗng/thiếu; hỗ trợ bounds âm; loại bỏ bounds zero/âm.
- Lỗi B: Gửi bình luận 1 lần; xác minh bằng chứng UI; xử lý UNKNOWN_OUTCOME không auto-retry.
- Lỗi C: Target lock TikTok xác thực lại kênh/video; dừng an toàn khi không xác định được.
- Lỗi D: Phân biệt container bài viết Facebook; trả về AMBIGUOUS_TARGET khi có nhiều bài.
- Lỗi E: Cập nhật live bounds trước mỗi retry mở khung bình luận; loại bỏ tọa độ tỷ lệ đoán.
- Lỗi F: Khóa thiết bị device_workflow_scope có timeout, kiểm tra cờ hủy và dọn dẹp an toàn.
"""

import threading
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, call, patch

import comment_controller
import ui_automator_dom
from adb_controller import ADBController


class TestBoxphoneReliabilityFixes(unittest.TestCase):
    def setUp(self):
        self.adb = MagicMock()
        self.adb.get_effective_screen_size.return_value = (1080, 1920)
        self.adb.execute_adb.return_value = (0, "", "")
        self.device_id = "test_device_api29"

    # ==========================================================================
    # LỖI A: XỬ LÝ BOUNDS VÀ LOẠI BỎ TỌA ĐỘ ĐOÁN MÒ
    # ==========================================================================

    def test_parse_bounds_supports_negative_and_validates_size(self):
        """Bounds âm phải được phân tích đúng; bounds có kích thước <= 0 bị loại bỏ."""
        # 1. Bounds âm hợp lệ (phần tử panning hoặc off-screen mép trái)
        b_neg = ui_automator_dom.parse_bounds("[-150,-100][250,300]")
        self.assertIsNotNone(b_neg)
        x1, y1, x2, y2, cx, cy = b_neg
        self.assertEqual(x1, -150)
        self.assertEqual(y1, -100)
        self.assertEqual(x2, 250)
        self.assertEqual(y2, 300)
        self.assertEqual(cx, 50)
        self.assertEqual(cy, 100)

        # 2. Bounds kích thước zero hoặc âm -> phải trả về None
        self.assertIsNone(ui_automator_dom.parse_bounds("[100,200][100,300]"))  # width == 0
        self.assertIsNone(ui_automator_dom.parse_bounds("[200,200][100,300]"))  # width < 0
        self.assertIsNone(ui_automator_dom.parse_bounds("[100,300][200,300]"))  # height == 0
        self.assertIsNone(ui_automator_dom.parse_bounds("[100,400][200,300]"))  # height < 0

    def test_is_bounds_visible_on_screen(self):
        """Phần tử nằm hoàn toàn ngoài màn hình không được xem là hiển thị."""
        # 1. Nằm hoàn toàn bên trái/trên màn hình
        b_off_left = (-300, -200, -10, -50, -155, -125)
        self.assertFalse(ui_automator_dom.is_bounds_visible_on_screen(b_off_left, 1080, 1920))

        # 2. Nằm hoàn toàn bên dưới màn hình
        b_off_bottom = (100, 2000, 500, 2200, 300, 2100)
        self.assertFalse(ui_automator_dom.is_bounds_visible_on_screen(b_off_bottom, 1080, 1920))

        # 3. Nằm trong màn hình
        b_on_screen = (100, 200, 500, 600, 300, 400)
        self.assertTrue(ui_automator_dom.is_bounds_visible_on_screen(b_on_screen, 1080, 1920))

    def test_empty_hierarchy_returns_none_no_fake_coordinates(self):
        """Với <hierarchy/> rỗng, find_tiktok_video_controls và find_facebook_target_controls tuyệt đối không đoán tọa độ."""
        empty_root = ET.fromstring("<hierarchy/>")

        # TikTok
        tt_ctrls = ui_automator_dom.find_tiktok_video_controls(empty_root, 1080, 1920)
        self.assertIsNone(tt_ctrls["like"])
        self.assertIsNone(tt_ctrls["comment"])
        self.assertIsNone(tt_ctrls["bookmark"])
        self.assertIsNone(tt_ctrls["share"])

        # Facebook
        fb_ctrls = ui_automator_dom.find_facebook_target_controls(empty_root, 1080, 1920)
        self.assertIsNone(fb_ctrls["like"])
        self.assertIsNone(fb_ctrls["comment"])
        self.assertEqual(fb_ctrls["status"], "NOT_FOUND")

    # ==========================================================================
    # LỖI B: GỬI BÌNH LUẬN 1 LẦN, XÁC MINH VÀ XỬ LÝ UNKNOWN_OUTCOME
    # ==========================================================================

    def test_verify_tiktok_comment_posted_success(self):
        """Xác minh thành công khi bình luận xuất hiện trong DOM stream."""
        xml_with_comment = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
          <node class="android.widget.TextView" text="Da em bị mụn ẩn dùng combo này được không?" bounds="[100,800][900,900]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_with_comment)):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "Da em bị mụn ẩn dùng combo này được không?", 1080, 1920, timeout=1.0
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.SUCCESS)

    def test_verify_tiktok_comment_posted_unknown_outcome(self):
        """Khi ô nhập đã sạch nhưng bình luận chưa thấy render trong DOM stream, trả về UNKNOWN_OUTCOME."""
        xml_without_comment = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
          <node class="android.widget.TextView" text="Bình luận của người khác" bounds="[100,800][900,900]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_without_comment)):
            outcome = comment_controller.verify_tiktok_comment_posted(
                self.adb, self.device_id, "Bình luận vừa đăng chưa kịp hiện", 1080, 1920, timeout=1.0
            )
            self.assertEqual(outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

    def test_unknown_outcome_does_not_retry_and_can_retry_is_false(self):
        """Kết quả UNKNOWN_OUTCOME có bool(result)==False và can_retry==False để không auto-retry mù quáng."""
        res = comment_controller.CommentTaskResult(
            comment_controller.TaskOutcome.UNKNOWN_OUTCOME,
            "Chưa đủ bằng chứng xác nhận",
            can_retry=False,
        )
        self.assertFalse(res)  # bool(res) is False
        self.assertFalse(res.can_retry)
        self.assertEqual(res.outcome, comment_controller.TaskOutcome.UNKNOWN_OUTCOME)

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
        xml_video = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="khai hoan" bounds="[50,1400][500,1460]" />
          <node class="android.widget.TextView" text="Bình luận đơn lẻ" bounds="[100,800][600,850]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_video)):
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
            # Nút gửi (950, 1200) chỉ được tap ĐÚNG 1 LẦN
            send_taps = [pt for pt in taps if pt == (950, 1200)]
            self.assertEqual(len(send_taps), 1)

    # ==========================================================================
    # LỖI C: TARGET LOCK TIKTOK
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
            # Phải dừng an toàn với AMBIGUOUS_TARGET
            self.assertFalse(res)
            self.assertEqual(res.outcome, comment_controller.TaskOutcome.AMBIGUOUS_TARGET)
            self.assertFalse(res.can_retry)
            # Đã cố gắng mở lại intent để phục hồi
            self.assertTrue(mock_intent.call_count >= 2)

    # ==========================================================================
    # LỖI D: PHÂN BIỆT BÀI VIẾT FACEBOOK (AMBIGUOUS_TARGET)
    # ==========================================================================

    def test_facebook_multiple_posts_on_feed_returns_ambiguous_target(self):
        """Khi màn hình Feed Facebook chứa nhiều bài viết độc lập (nhiều hàng Like/Comment cách xa nhau), trả về AMBIGUOUS_TARGET."""
        xml_multi_post = """<hierarchy>
          <!-- Post 1 ở nửa trên (y=600) -->
          <node class="android.widget.Button" content-desc="Thích" bounds="[50,550][150,650]" />
          <node class="android.widget.Button" content-desc="Bình luận" bounds="[350,550][450,650]" />
          <!-- Post 2 ở nửa dưới (y=1500) -->
          <node class="android.widget.Button" content-desc="Thích" bounds="[50,1450][150,1550]" />
          <node class="android.widget.Button" content-desc="Bình luận" bounds="[350,1450][450,1550]" />
        </hierarchy>"""
        root = ET.fromstring(xml_multi_post)
        ctrls = ui_automator_dom.find_facebook_target_controls(root, 1080, 1920)
        self.assertEqual(ctrls["status"], "AMBIGUOUS_TARGET")
        self.assertIsNone(ctrls["like"])
        self.assertIsNone(ctrls["comment"])

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
            # Tuyệt đối không bấm nút Thích hay Bình luận nào
            self.assertEqual(taps, [])

    # ==========================================================================
    # LỖI E: CẬP NHẬT LIVE BOUNDS TRƯỚC MỖI RETRY
    # ==========================================================================

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
          <!-- Tọa độ nút bình luận đã dịch chuyển khi UI layout ổn định -->
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1250][1080,1370]" />
          <node class="android.widget.TextView" text="khaihoan" bounds="[50,1400][500,1460]" />
        </hierarchy>"""

        xml_comment_open = """<hierarchy>
          <node class="android.widget.EditText" text="Thêm bình luận..." bounds="[50,1700][900,1850]" />
          <node class="android.widget.TextView" text="Cmt test" bounds="[100,800][500,850]" />
        </hierarchy>"""

        def mock_dump(_adb, _dev):
            dump_calls.append(len(dump_calls) + 1)
            if len(dump_calls) == 1:
                return ET.fromstring(xml_video_1)
            elif len(dump_calls) == 2:
                return ET.fromstring(xml_video_2)
            else:
                return ET.fromstring(xml_comment_open)

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
                            # Đã dump DOM nhiều lần để lấy live bounds
                            self.assertTrue(len(dump_calls) >= 2)
                            # Tap lần 2 phải dùng tọa độ live bounds (cy = (1250+1370)//2 = 1310), KHÔNG dùng tọa độ đoán cũ
                            self.assertIn((996, 1310), taps)

    # ==========================================================================
    # LỖI F: ĐỒNG BỘ KHÓA THIẾT BỊ, TIMEOUT VÀ HỦY TÁC VỤ
    # ==========================================================================

    def test_device_workflow_scope_timeout(self):
        """Khóa thiết bị có timeout, nâng TimeoutError nếu thiết bị bị luồng khác chiếm giữ quá thời gian."""
        controller = ADBController()

        # Luồng 1 chiếm khóa thiết bị dev_busy trong 1.5 giây
        def hold_lock():
            with controller.device_workflow_scope("dev_busy", timeout=5.0):
                time.sleep(1.2)

        t = threading.Thread(target=hold_lock)
        t.start()
        time.sleep(0.2)

        # Luồng 2 thử chiếm khóa với timeout ngắn 0.3s -> phải văng TimeoutError
        with self.assertRaises(TimeoutError):
            with controller.device_workflow_scope("dev_busy", timeout=0.3):
                pass
        t.join()

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


if __name__ == "__main__":
    unittest.main()
