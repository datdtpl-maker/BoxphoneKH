import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

from adb_controller import ADBController


class RecentAppsCleanupTests(unittest.TestCase):
    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_clear_recent_apps_uses_samsung_clear_all_resource_id_when_text_hidden(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node clickable="true" text="" content-desc=""
                    resource-id="com.sec.android.app.launcher:id/clear_all"
                    bounds="[210,1510][870,1690]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.keyevent = lambda *_args: None
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            cleared = controller.clear_recent_apps("device-samsung")

        self.assertTrue(cleared)
        self.assertEqual([(540, 1600)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_clear_recent_apps_taps_exact_vietnamese_label_center(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node clickable="true" bounds="[40,1300][1040,1880]">
                <node clickable="false" text="Đóng tất cả"
                      bounds="[350,1580][730,1720]" />
              </node>
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.keyevent = lambda *_args: None
        taps = []
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            cleared = controller.clear_recent_apps("device-vietnamese")

        self.assertTrue(cleared)
        # Tọa độ phải lấy từ chính node chữ, không lấy tâm khung cha hoặc
        # hardcode theo một model điện thoại cụ thể.
        self.assertEqual([(540, 1650)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_clear_recent_apps_taps_clear_all_and_returns_home(
        self, _exists, _remove, _sleep
    ):
        root = ET.fromstring(
            """
            <hierarchy>
              <node clickable="true" content-desc="Xóa tất cả"
                    bounds="[420,1600][660,1840]" />
            </hierarchy>
            """
        )
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        keyevents = []
        taps = []
        controller.keyevent = (
            lambda _device_id, keycode: keyevents.append(keycode)
        )
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            return_value=SimpleNamespace(getroot=lambda: root),
        ):
            cleared = controller.clear_recent_apps("device-1")

        self.assertTrue(cleared)
        self.assertEqual([187, 3], keyevents)
        self.assertEqual([(540, 1720)], taps)

    @patch("adb_controller.time.sleep", return_value=None)
    @patch("adb_controller.os.remove")
    @patch("adb_controller.os.path.exists", return_value=True)
    def test_clear_recent_apps_scrolls_to_pixel_clear_all_when_needed(
        self, _exists, _remove, _sleep
    ):
        first_root = ET.fromstring("<hierarchy />")
        second_root = ET.fromstring(
            """
            <hierarchy>
              <node clickable="true" content-desc="Clear all"
                    bounds="[30,800][250,1050]" />
            </hierarchy>
            """
        )
        roots = iter([first_root, second_root])
        controller = ADBController(adb_path="adb")
        controller.lock_portrait = lambda *_args, **_kwargs: True
        controller.execute_adb = lambda *_args, **_kwargs: (0, "", "")
        controller.get_effective_screen_size = lambda _device_id: (1080, 1920)
        controller.keyevent = lambda *_args: None
        swipes = []
        taps = []
        controller.swipe = (
            lambda _device_id, x1, y1, x2, y2, duration=500:
            swipes.append((x1, y1, x2, y2, duration))
        )
        controller.tap = lambda _device_id, x, y: taps.append((x, y))

        with patch(
            "adb_controller.ET.parse",
            side_effect=lambda _path: SimpleNamespace(
                getroot=lambda: next(roots)
            ),
        ):
            cleared = controller.clear_recent_apps("device-pixel")

        self.assertTrue(cleared)
        self.assertEqual(1, len(swipes))
        self.assertLess(swipes[0][0], swipes[0][2])
        self.assertEqual([(140, 925)], taps)


if __name__ == "__main__":
    unittest.main()
