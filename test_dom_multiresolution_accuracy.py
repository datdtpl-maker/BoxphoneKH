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


if __name__ == "__main__":
    unittest.main()
