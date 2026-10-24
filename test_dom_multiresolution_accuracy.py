import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from adb_controller import ADBController


class DomMultiResolutionAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.controller = ADBController()
        self.controller.is_tiktok_in_foreground = lambda _dev: True
        self.controller.wait_for_tiktok_foreground = lambda *_args, **_kwargs: True

    @patch("adb_controller.time.sleep", return_value=None)
    def test_top_tab_coords_fhd_1080(self, _sleep):
        """Kiểm tra bắt đúng tab Top theo DOM trên màn 1080x1920."""
        root = ET.fromstring("""
        <hierarchy>
          <node text="Hỏi" bounds="[40,160][160,220]" />
          <node text="Top" bounds="[180,160][300,220]" />
          <node text="Video" bounds="[320,160][440,220]" />
          <node text="Ảnh" selected="true" bounds="[460,160][580,220]" />
        </hierarchy>
        """)
        taps = []
        self.controller.tap = lambda _dev, x, y: taps.append((x, y))
        self.controller.get_effective_screen_size = lambda _dev: (1080, 1920)

        switched = self.controller.ensure_tiktok_search_top_tab("dev-1080", root=root)
        self.assertTrue(switched)
        self.assertEqual([(240, 190)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_top_tab_coords_wqhd_1440(self, _sleep):
        """Kiểm tra bắt đúng tab Top theo DOM trên màn 1440x2560 (Note FE / S7 Edge 2K)."""
        root = ET.fromstring("""
        <hierarchy>
          <node text="Ask" bounds="[50,210][210,290]" />
          <node text="Top" bounds="[240,210][400,290]" />
          <node text="Videos" bounds="[430,210][590,290]" />
          <node text="Photos" selected="true" bounds="[620,210][780,290]" />
        </hierarchy>
        """)
        taps = []
        self.controller.tap = lambda _dev, x, y: taps.append((x, y))
        self.controller.get_effective_screen_size = lambda _dev: (1440, 2560)

        switched = self.controller.ensure_tiktok_search_top_tab("dev-1440", root=root)
        self.assertTrue(switched)
        # Tâm của node Top [240,210][400,290] là (320, 250)
        self.assertEqual([(320, 250)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_target_top_tab_wqhd_1440(self, _sleep):
        """Kiểm tra card kênh chiều cao 480px trên 1440x2560 vẫn nhận diện chính xác tên Kênh."""
        search_top_root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.EditText" bounds="[120,60][1200,180]" text="Khải Hoàn Skincare PT" />
          <node text="Top" selected="true" bounds="[240,210][400,290]" />
          <node class="android.widget.RelativeLayout" clickable="true"
                bounds="[0,340][1440,820]" resource-id="card_with_preview_videos">
            <node class="android.widget.TextView" clickable="false"
                  bounds="[330,400][1000,480]" text="Khải Hoàn Skincare PT" />
            <node class="android.widget.TextView" text="khaihoanskincare" />
            <node class="android.widget.Button" text="Following" bounds="[1130,400][1380,480]" />
          </node>
        </hierarchy>
        """)
        profile_root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Khải Hoàn Skincare PT" />
          <node class="android.widget.Button" text="Message" />
          <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
        </hierarchy>
        """)
        roots = iter([search_top_root, profile_root])
        self.controller._get_tiktok_ui_root = lambda *_args: next(roots, profile_root)
        self.controller.get_effective_screen_size = lambda _dev: (1440, 2560)
        taps = []
        self.controller.tap = lambda _dev, x, y: taps.append((x, y))

        success = self.controller.find_and_click_tiktok_channel("dev-1440", "Khải Hoàn Skincare PT")
        self.assertTrue(success)
        self.assertTrue(len(taps) >= 1)
        tap_x, tap_y = taps[0]
        # Tâm của node TextView [330,400][1000,480] là (665, 440), né hoàn toàn nút Follow ở góc phải
        self.assertEqual(440, tap_y)
        self.assertTrue(330 <= tap_x <= 1000)

    def test_profile_newest_video_unpinned_wqhd_1440(self):
        """Kiểm tra profile có video Đã ghim: ưu tiên mở video mới nhất (unpinned) Row 1 Col 2 trên 1440x2560."""
        profile_root = ET.fromstring("""
        <hierarchy>
          <node text="Khải Hoàn Skincare PT" bounds="[400,200][1040,280]" />
          <node class="android.widget.GridView" bounds="[0,1200][1440,2560]">
            <!-- Ô 1: Video Đã ghim -->
            <node class="android.widget.FrameLayout" clickable="true" bounds="[0,1200][478,1840]">
              <node text="Đã ghim" bounds="[20,1780][180,1820]" />
            </node>
            <!-- Ô 2: Video Mới nhất (không ghim) -->
            <node class="android.widget.FrameLayout" clickable="true" bounds="[480,1200][958,1840]">
              <node text="15.8K" bounds="[500,1780][660,1820]" />
            </node>
            <!-- Ô 3: Video cũ hơn -->
            <node class="android.widget.FrameLayout" clickable="true" bounds="[960,1200][1440,1840]">
              <node text="3.2K" bounds="[980,1780][1120,1820]" />
            </node>
          </node>
        </hierarchy>
        """)
        candidates, has_unpinned = self.controller._extract_tiktok_profile_video_candidates(
            profile_root, 1440, 2560
        )
        self.assertTrue(has_unpinned)
        self.assertEqual(3, len(candidates))
        # Video mới nhất phải là Ô 2: trung tâm của [480,1200][958,1840] -> ((480+958)//2, (1200+1840)//2) = (719, 1520)
        self.assertEqual((719, 1520), candidates[0])

    def test_extract_clip_interaction_coords_from_dom(self):
        """Kiểm tra trích xuất chính xác tọa độ các nút Bookmark, Like, Comment, Share từ DOM."""
        player_root = ET.fromstring("""
        <hierarchy>
          <node text="Routine phục hồi da mụn Khải Hoàn Skincare PT" bounds="[50,1800][1000,2100]" />
          <node resource-id="com.zhiliaoapp.musically:id/like_btn" content-desc="Thích"
                bounds="[1300,1200][1420,1320]" />
          <node resource-id="com.zhiliaoapp.musically:id/comment_btn" content-desc="Bình luận"
                bounds="[1300,1400][1420,1520]" />
          <node resource-id="com.zhiliaoapp.musically:id/bookmark_btn" content-desc="Lưu"
                bounds="[1300,1600][1420,1720]" />
          <node resource-id="com.zhiliaoapp.musically:id/share_btn" content-desc="Chia sẻ"
                bounds="[1300,1800][1420,1920]" />
        </hierarchy>
        """)
        sig, liked, bookmarked, coords = self.controller._extract_tiktok_clip_interaction_state(
            player_root, 1440, 2560
        )
        self.assertFalse(liked)
        self.assertFalse(bookmarked)
        self.assertIsNotNone(sig)
        self.assertEqual((1360, 1260), coords.get("like"))
        self.assertEqual((1360, 1460), coords.get("comment"))
        self.assertEqual((1360, 1660), coords.get("bookmark"))
        self.assertEqual((1360, 1860), coords.get("share"))


    def test_channel_target_101_not_mun_matching(self):
        """Kiểm tra so khớp kênh TikTok Khải Hoàn & 101 Nốt Mụn (@khaihoan.101notmun)."""
        target = "Khải Hoàn & 101 Nốt Mụn"
        self.assertTrue(self.controller._match_tiktok_channel_name("Khải Hoàn 101 Nốt Mụn", target))
        self.assertTrue(self.controller._match_tiktok_channel_name("@khaihoan.101notmun", target))
        self.assertTrue(self.controller._match_tiktok_channel_name("khaihoan.101notmun", target))
        self.assertTrue(self.controller._match_tiktok_channel_name("Khải Hoàn & 101 Nốt Mụn Official", target))

        # Phải phân biệt rõ ràng, không nhận nhầm kênh Khải Hoàn Skincare PT hay cá nhân khác
        self.assertFalse(self.controller._match_tiktok_channel_name("Khải Hoàn Skincare PT", target))
        self.assertFalse(self.controller._match_tiktok_channel_name("@khaihoanskincare", target))
        self.assertFalse(self.controller._match_tiktok_channel_name("Trần Khải Hoàn", target))
        self.assertFalse(self.controller._match_tiktok_channel_name("honkhi418", target))

    @patch("adb_controller.time.sleep", return_value=None)
    def test_channel_target_101_not_mun_click_fhd_1080(self, _sleep):
        """Kiểm tra nhận diện và click đúng card Kênh Khải Hoàn & 101 Nốt Mụn trên 1080x1920."""
        search_top_root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.EditText" bounds="[80,50][900,140]" text="Khải Hoàn &amp; 101 Nốt Mụn" />
          <node text="Top" selected="true" bounds="[180,160][300,220]" />
          <node class="android.widget.RelativeLayout" clickable="true"
                bounds="[0,260][1080,620]" resource-id="card_target_channel">
            <node class="android.widget.TextView" clickable="false"
                  bounds="[250,310][750,370]" text="Khải Hoàn &amp; 101 Nốt Mụn" />
            <node class="android.widget.TextView" text="@khaihoan.101notmun" />
            <node class="android.widget.Button" text="Follow" bounds="[850,310][1040,370]" />
          </node>
        </hierarchy>
        """)
        profile_root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Khải Hoàn &amp; 101 Nốt Mụn" />
          <node class="android.widget.Button" text="Tin nhắn" />
          <node resource-id="com.ss.android.ugc.trill:id/user_video_view" />
        </hierarchy>
        """)
        roots = iter([search_top_root, profile_root])
        self.controller._get_tiktok_ui_root = lambda *_args: next(roots, profile_root)
        self.controller.get_effective_screen_size = lambda _dev: (1080, 1920)
        taps = []
        self.controller.tap = lambda _dev, x, y: taps.append((x, y))

        success = self.controller.find_and_click_tiktok_channel("dev-1080", "Khải Hoàn & 101 Nốt Mụn")
        self.assertTrue(success)
        self.assertTrue(len(taps) >= 1)
        tap_x, tap_y = taps[0]
        # Tâm thẻ card là (540, 440), nằm trong phạm vi hiển thị hợp lệ
        self.assertEqual(440, tap_y)
        self.assertEqual(540, tap_x)

    def test_facebook_page_name_resolution_comma_separated(self):
        """Kiểm tra chọn chính xác tên Page canonical khi cấu hình danh sách Page phân tách dấu phẩy."""
        resolved_skincare = self.controller._resolve_facebook_exact_page_name("Khải Hoàn Skincare")
        self.assertIn("Khải Hoàn Skincare", resolved_skincare)
        resolved_nhathuoc = self.controller._resolve_facebook_exact_page_name("Nhà thuốc Khải Hoàn")
        self.assertIn("Nhà thuốc Khải Hoàn", resolved_nhathuoc)


    def test_ui_automator_dom_tiktok_english_liked(self):
        """Kiểm tra nhận diện nút Like (đã like) và nút Bình luận trên TikTok Tiếng Anh."""
        import ui_automator_dom
        xml_en = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Video liked" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Read or add comments, 2" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="Khải Hoàn Skincare PT" bounds="[30,1400][500,1460]" />
        </hierarchy>"""
        root = ET.fromstring(xml_en)
        ctrls = ui_automator_dom.find_tiktok_video_controls(root, 1080, 1920)
        self.assertEqual(ctrls["like"]["center"], (996, 1076))
        self.assertTrue(ctrls["like"]["is_liked"])
        self.assertEqual(ctrls["comment"]["center"], (996, 1234))
        self.assertEqual(ctrls["channel_name"], "khải hoàn skincare pt")

    def test_ui_automator_dom_tiktok_vietnamese_unliked(self):
        """Kiểm tra nhận diện nút Like (chưa like) và nút Bình luận trên TikTok Tiếng Việt."""
        import ui_automator_dom
        xml_vi = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="Khải Hoàn &amp; 101 Nốt Mụn" bounds="[30,1400][500,1460]" />
        </hierarchy>"""
        root = ET.fromstring(xml_vi)
        ctrls = ui_automator_dom.find_tiktok_video_controls(root, 1080, 1920)
        self.assertEqual(ctrls["like"]["center"], (996, 1076))
        self.assertFalse(ctrls["like"]["is_liked"])
        self.assertEqual(ctrls["comment"]["center"], (996, 1234))
        self.assertEqual(ctrls["channel_name"], "khải hoàn & 101 nốt mụn")

    def test_ui_automator_dom_tiktok_2k_resolution(self):
        """Kiểm tra nhận diện chính xác trên màn hình 2K (1440x2560)."""
        import ui_automator_dom
        xml_2k = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Thích video" bounds="[1216,1333][1440,1543]" />
          <node class="android.widget.ImageView" content-desc="Đọc hoặc viết bình luận" bounds="[1216,1543][1440,1753]" />
          <node class="android.widget.TextView" text="Khải Hoàn Skincare PT" bounds="[40,1850][700,1930]" />
        </hierarchy>"""
        root = ET.fromstring(xml_2k)
        ctrls = ui_automator_dom.find_tiktok_video_controls(root, 1440, 2560)
        self.assertEqual(ctrls["like"]["center"], (1328, 1438))
        self.assertEqual(ctrls["comment"]["center"], (1328, 1648))

    @patch("comment_controller.is_tiktok_comment_sheet_open", return_value=True)
    @patch("time.sleep", return_value=None)
    def test_post_tiktok_comment_skips_like_if_already_liked(self, _sleep, _sheet_open):
        """Kiểm tra post_tiktok_comment: Nếu video đã Like trên DOM thì KHÔNG bấm Like nữa, tuyệt đối không swipe."""
        import comment_controller
        from unittest.mock import MagicMock
        adb = MagicMock()
        adb.get_effective_screen_size.return_value = (1080, 1920)
        adb.execute_adb.return_value = (0, "", "")
        
        xml_liked = """<hierarchy>
          <node class="android.widget.ImageView" content-desc="Video liked" bounds="[912,997][1080,1155]" />
          <node class="android.widget.ImageView" content-desc="Read or add comments" bounds="[912,1155][1080,1313]" />
          <node class="android.widget.TextView" text="Bình luận test" bounds="[100,1400][500,1450]" />
        </hierarchy>"""
        with patch("ui_automator_dom.dump_ui_tree", return_value=ET.fromstring(xml_liked)):
            taps = []
            adb.tap = lambda dev, x, y: taps.append((x, y))
            ok = comment_controller.post_tiktok_comment(
                adb, "dev-test", "https://www.tiktok.com/@khaihoanskincare/video/123", "Bình luận test", dwell_time=1
            )
            self.assertTrue(ok)
            # Điểm Like (996, 1076) KHÔNG được xuất hiện trong taps vì đã like
            self.assertNotIn((996, 1076), taps)
            # Điểm Comment (996, 1234) PHẢI xuất hiện trong taps để mở sheet
            self.assertIn((996, 1234), taps)
            # Tuyệt đối KHÔNG có lệnh swipe nào
            self.assertFalse(hasattr(adb, "swipe") and adb.swipe.called)


if __name__ == "__main__":
    unittest.main()
