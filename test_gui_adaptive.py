import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui_app import GUIApp


class _Entry:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value


def _run_immediately(captured):
    def fake_scheduler(devices, worker, policy, **kwargs):
        captured.append((list(devices), policy, kwargs))
        return [worker(device_id) for device_id in devices]

    return fake_scheduler


class AdaptiveGuiIntegrationTests(unittest.TestCase):
    def test_social_queue_moves_every_target_off_shopee(self):
        app = GUIApp.__new__(GUIApp)
        events = []
        fake_adb = SimpleNamespace(
            stop_app=lambda device, package: events.append(
                ("stop", device, package)
            ),
            ensure_facebook_ready=lambda device: events.append(
                ("facebook", device)
            ) or True,
            launch_tiktok=lambda device: events.append(("tiktok", device)),
            is_tiktok_in_foreground=lambda _device: True,
        )

        with patch("gui_app.main.adb", fake_adb):
            app.prepare_social_targets(["d1", "d2"], "facebook")
            app.prepare_social_targets(["d1", "d2"], "tiktok")

        stop_events = [event for event in events if event[0] == "stop"]
        self.assertEqual(4, len(stop_events))
        self.assertTrue(
            all(event[2] == "com.shopee.vn" for event in stop_events)
        )
        self.assertCountEqual(
            [("facebook", "d1"), ("facebook", "d2")],
            [event for event in events if event[0] == "facebook"],
        )
        self.assertCountEqual(
            [("tiktok", "d1"), ("tiktok", "d2")],
            [event for event in events if event[0] == "tiktok"],
        )

    def test_shopee_adaptive_uses_shopee_policy(self):
        app = GUIApp.__new__(GUIApp)
        app.keyword_mode = SimpleNamespace(get=lambda: "original")
        app.txt_main_keywords = _Entry("keyword-1\nkeyword-2")
        app.ent_selection = _Entry("1-2")
        app.parse_targets = lambda entry_widget=None: ["d1", "d2"]
        app.run_in_thread = lambda action: action()
        captured = []
        fake_adb = SimpleNamespace(
            shopee_find_and_click_lamdong=(
                lambda *_args, **_kwargs: (True, "")
            )
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", side_effect=lambda d: d),
            patch("gui_app.run_adaptive", side_effect=_run_immediately(captured)),
            patch("builtins.print"),
        ):
            app.run_par_search(adaptive=True)

        self.assertEqual(2, captured[0][1].max_workers)
        self.assertEqual((30, 90), captured[0][1].stagger_seconds)

    def test_tiktok_adaptive_uses_tiktok_policy(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_selection = _Entry("1-2")
        app.ent_tt_seed = _Entry("seed")
        app.ent_tt_channel = _Entry("target")
        app.parse_targets = lambda entry_widget=None: ["d1", "d2"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        captured = []
        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (True, "")
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", side_effect=lambda d: d),
            patch("gui_app.run_adaptive", side_effect=_run_immediately(captured)),
            patch("builtins.print"),
        ):
            app.run_par_tiktok(adaptive=True)

        self.assertEqual(4, captured[0][1].max_workers)
        self.assertEqual((30, 90), captured[0][1].stagger_seconds)

    def test_facebook_adaptive_uses_facebook_policy(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_fb_selection = _Entry("1-2")
        app.ent_fb_seed = _Entry("seed")
        app.ent_fb_target = _Entry("target")
        app.parse_targets = lambda entry_widget=None: ["d1", "d2"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        captured = []
        fake_adb = SimpleNamespace(
            facebook_automation_workflow=lambda *_args, **_kwargs: (True, "")
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", side_effect=lambda d: d),
            patch("gui_app.run_adaptive", side_effect=_run_immediately(captured)),
            patch("builtins.print"),
        ):
            app.run_par_facebook(adaptive=True)

        self.assertEqual(3, captured[0][1].max_workers)
        self.assertEqual((30, 90), captured[0][1].stagger_seconds)


if __name__ == "__main__":
    unittest.main()
