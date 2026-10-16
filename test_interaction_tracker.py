# -*- coding: utf-8 -*-
import unittest
import tempfile
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import interaction_tracker
from interaction_tracker import InteractionTracker
from adb_controller import ADBController


class TestInteractionTracker(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.file_path = Path(self.test_dir) / "test_history.json"
        self.tracker = InteractionTracker(file_path=self.file_path, max_records_per_device=5)
        # Patch singleton default_tracker
        self.orig_tracker = interaction_tracker.default_tracker
        interaction_tracker.default_tracker = self.tracker

        self.adb = ADBController(adb_path="adb")
        self.adb.get_effective_screen_size = lambda _dev: (1080, 1920)
        self.adb._get_tiktok_ui_root = lambda _dev, _p="": None

    def tearDown(self):
        interaction_tracker.default_tracker = self.orig_tracker
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_record_and_has_interacted(self):
        self.assertFalse(self.tracker.has_interacted("dev1", "tiktok", "clip_101", "like"))
        self.tracker.record_interaction("dev1", "tiktok", "clip_101", "like")
        self.assertTrue(self.tracker.has_interacted("dev1", "tiktok", "clip_101", "like"))

        # Khác device hoặc khác action/platform không bị lẫn
        self.assertFalse(self.tracker.has_interacted("dev2", "tiktok", "clip_101", "like"))
        self.assertFalse(self.tracker.has_interacted("dev1", "facebook", "clip_101", "like"))
        self.assertFalse(self.tracker.has_interacted("dev1", "tiktok", "clip_101", "bookmark"))

    def test_persistence_across_instances(self):
        self.tracker.record_interaction("dev1", "facebook", "post_abc", "like")
        
        # Load instance mới từ cùng file
        tracker2 = InteractionTracker(file_path=self.file_path)
        self.assertTrue(tracker2.has_interacted("dev1", "facebook", "post_abc", "like"))
        self.assertFalse(tracker2.has_interacted("dev1", "facebook", "post_xyz", "like"))

    def test_auto_pruning_max_records(self):
        for i in range(10):
            self.tracker.record_interaction("dev1", "tiktok", f"clip_{i}", "like")
        
        # max_records_per_device = 5
        count = self.tracker.get_interaction_count("dev1", "tiktok", "like")
        self.assertEqual(5, count)
        # Các bản ghi cũ nhất (0..4) bị cắt tỉa, mới nhất (5..9) còn lại
        self.assertFalse(self.tracker.has_interacted("dev1", "tiktok", "clip_0", "like"))
        self.assertTrue(self.tracker.has_interacted("dev1", "tiktok", "clip_9", "like"))

    def test_clear_history(self):
        self.tracker.record_interaction("dev1", "tiktok", "clip_1", "like")
        self.tracker.record_interaction("dev1", "facebook", "post_1", "like")
        self.tracker.record_interaction("dev2", "tiktok", "clip_1", "like")

        # Xóa tiktok của dev1
        self.tracker.clear_history(device_id="dev1", platform="tiktok")
        self.assertFalse(self.tracker.has_interacted("dev1", "tiktok", "clip_1", "like"))
        self.assertTrue(self.tracker.has_interacted("dev1", "facebook", "post_1", "like"))
        self.assertTrue(self.tracker.has_interacted("dev2", "tiktok", "clip_1", "like"))

    def test_tiktok_micro_interactions_likes_when_new(self):
        taps = []
        statuses = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        # Giả lập random để luôn like (random < rate)
        with patch("adb_controller.random.random", side_effect=[0.001, 0.99, 0.99, 0.99]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_tiktok_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg),
                clip_signature="kenh_target_clip_1"
            )

        self.assertEqual(2, len(taps)) # Double tap
        self.assertTrue(self.tracker.has_interacted("dev1", "tiktok", "kenh_target_clip_1", "like"))
        self.assertTrue(any("Thả tim" in s for s in statuses))

    def test_tiktok_micro_interactions_skips_when_already_liked(self):
        # Đánh dấu đã like
        self.tracker.record_interaction("dev1", "tiktok", "kenh_target_clip_1", "like")

        taps = []
        statuses = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        with patch("adb_controller.random.random", side_effect=[0.001, 0.99, 0.99, 0.99]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_tiktok_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg),
                clip_signature="kenh_target_clip_1"
            )

        self.assertEqual(0, len(taps)) # Không double tap
        self.assertTrue(any("đã từng thả tim trước đây" in s for s in statuses))

    def test_facebook_micro_interactions_skips_when_selected_true(self):
        # Nút like có selected="true" -> Không tap, không gây hủy like
        root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Bài viết mẫu trị mụn" bounds="[50,600][1000,750]" />
          <node class="android.widget.Button" text="Thích" content-desc="Thích" selected="true" bounds="[50,800][250,880]" />
        </hierarchy>
        """)
        self.adb._get_facebook_ui_root = lambda _dev, _p: root
        taps = []
        statuses = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        with patch("adb_controller.random.random", side_effect=[0.99, 0.001]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_facebook_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg)
            )

        self.assertEqual(0, len(taps)) # Không tap
        self.assertTrue(any("tránh hủy Like" in s for s in statuses))

    def test_facebook_micro_interactions_likes_and_records_new_post(self):
        # Nút like bình thường chưa selected
        root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Bài viết mẫu trị mụn chuyên sâu" bounds="[50,600][1000,750]" />
          <node class="android.widget.Button" text="Thích" content-desc="Thích" selected="false" bounds="[50,800][250,880]" />
        </hierarchy>
        """)
        self.adb._get_facebook_ui_root = lambda _dev, _p: root
        taps = []
        statuses = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        with patch("adb_controller.random.random", side_effect=[0.99, 0.001]), \
             patch("adb_controller.time.sleep", return_value=None):
            res = self.adb.perform_facebook_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg)
            )

        self.assertTrue(res)
        self.assertEqual(1, len(taps))
        self.assertEqual(1, self.tracker.get_interaction_count("dev1", "facebook", "like"))
        self.assertTrue(any("Thả Like bài viết mới" in s for s in statuses))

    def test_facebook_micro_interactions_skips_when_in_tracker_history(self):
        root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Bài viết mẫu trị mụn chuyên sâu" bounds="[50,600][1000,750]" />
          <node class="android.widget.Button" text="Thích" content-desc="Thích" selected="false" bounds="[50,800][250,880]" />
        </hierarchy>
        """)
        self.adb._get_facebook_ui_root = lambda _dev, _p: root
        taps = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        # Lần 1: Like thành công
        with patch("adb_controller.random.random", side_effect=[0.99, 0.001]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_facebook_micro_interactions("dev1", 1080, 1920)
        self.assertEqual(1, len(taps))

        # Lần 2: Cùng bài viết đó -> Bỏ qua vì tracker đã có
        statuses = []
        with patch("adb_controller.random.random", side_effect=[0.99, 0.001]), \
             patch("adb_controller.time.sleep", return_value=None):
            res = self.adb.perform_facebook_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg)
            )
        self.assertFalse(res)
        self.assertEqual(1, len(taps)) # Vẫn là 1, không tap thêm
        self.assertTrue(any("đã từng Like bài viết này • Bỏ qua" in s for s in statuses))

    def test_tiktok_micro_interactions_skips_when_ui_heart_selected(self):
        root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Kem dưỡng ẩm phục hồi da chuyên sâu #skincare" bounds="[30,1450][750,1580]" />
          <node class="android.widget.ImageView" content-desc="Thích video" resource-id="com.ss.android.ugc.trill:id/like_icon" selected="true" bounds="[940,1020][1040,1120]" />
        </hierarchy>
        """)
        self.adb._get_tiktok_ui_root = lambda _dev, _p="": root
        taps = []
        statuses = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        with patch("adb_controller.random.random", side_effect=[0.001, 0.99, 0.99, 0.99]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_tiktok_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg),
                clip_signature="kenh_target_clip_99"
            )

        self.assertEqual(0, len(taps))
        self.assertTrue(self.tracker.has_interacted("dev1", "tiktok", "kenh_target_clip_99", "like"))
        self.assertTrue(any("đã từng thả tim trước đây" in s for s in statuses))

    def test_tiktok_micro_interactions_skips_when_same_caption_content_different_clip_index(self):
        root = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Serum trị mụn tái tạo làn da sáng mịn tự nhiên" bounds="[30,1450][750,1580]" />
          <node class="android.widget.ImageView" content-desc="Thích video" resource-id="com.ss.android.ugc.trill:id/like_icon" selected="false" bounds="[940,1020][1040,1120]" />
        </hierarchy>
        """)
        self.adb._get_tiktok_ui_root = lambda _dev, _p="": root
        taps = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        # Lần 1 ở vị trí clip_1 -> thả tim
        with patch("adb_controller.random.random", side_effect=[0.001, 0.99, 0.99, 0.99]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_tiktok_micro_interactions(
                "dev1", 1080, 1920, clip_signature="kenh_target_clip_1"
            )
        self.assertEqual(2, len(taps))

        # Lần 2 kênh đăng thêm bài mới làm clip này lùi xuống clip_2 -> vẫn nhận diện qua content_sig và bỏ qua
        statuses = []
        with patch("adb_controller.random.random", side_effect=[0.001, 0.99, 0.99, 0.99]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_tiktok_micro_interactions(
                "dev1", 1080, 1920, status_callback=lambda _d, msg: statuses.append(msg),
                clip_signature="kenh_target_clip_2"
            )
        self.assertEqual(2, len(taps))
        self.assertTrue(any("đã từng thả tim trước đây" in s for s in statuses))

    def test_facebook_micro_interactions_reaction_bar_and_dynamic_counts(self):
        # Bài viết có dòng đếm động "15 người khác" thay đổi thành "28 người khác" vẫn giữ nguyên post_sig
        root1 = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Kem chống nắng phổ rộng bảo vệ da tối ưu" bounds="[50,550][1000,680]" />
          <node class="android.widget.TextView" text="15 lượt thích" bounds="[50,740][400,785]" />
          <node class="android.widget.Button" text="Thích" content-desc="Thích" selected="false" bounds="[50,800][250,880]" />
        </hierarchy>
        """)
        self.adb._get_facebook_ui_root = lambda _dev, _p: root1
        taps = []
        self.adb.tap = lambda _dev, x, y: taps.append((x, y))

        with patch("adb_controller.random.random", side_effect=[0.99, 0.001]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_facebook_micro_interactions("dev1", 1080, 1920)
        self.assertEqual(1, len(taps))

        # Lần sau số lượt thích tăng lên "28 lượt thích" -> vẫn khớp post_sig đã lưu, không bấm lại
        root2 = ET.fromstring("""
        <hierarchy>
          <node class="android.widget.TextView" text="Kem chống nắng phổ rộng bảo vệ da tối ưu" bounds="[50,550][1000,680]" />
          <node class="android.widget.TextView" text="28 lượt thích" bounds="[50,740][400,785]" />
          <node class="android.widget.Button" text="Thích" content-desc="Thích" selected="false" bounds="[50,800][250,880]" />
        </hierarchy>
        """)
        self.adb._get_facebook_ui_root = lambda _dev, _p: root2
        with patch("adb_controller.random.random", side_effect=[0.99, 0.001]), \
             patch("adb_controller.time.sleep", return_value=None):
            self.adb.perform_facebook_micro_interactions("dev1", 1080, 1920)
        self.assertEqual(1, len(taps))


if __name__ == "__main__":
    unittest.main()