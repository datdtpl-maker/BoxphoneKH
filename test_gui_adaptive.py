import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from gui_app import GUIApp


class _Entry:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value


class _BooleanVar:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value


def _run_immediately(captured):
    def fake_scheduler(devices, worker, policy, **kwargs):
        captured.append((list(devices), policy, kwargs))
        return [worker(device_id) for device_id in devices]

    return fake_scheduler


class AdaptiveGuiIntegrationTests(unittest.TestCase):
    def test_combined_switches_are_independent_by_source_module(self):
        app = GUIApp.__new__(GUIApp)
        app.tiktok_combined_var = _BooleanVar(True)
        app.facebook_combined_var = _BooleanVar(False)

        self.assertTrue(app._social_combined_enabled("tiktok"))
        self.assertFalse(app._social_combined_enabled("facebook"))
        self.assertFalse(app._social_combined_enabled())

        app.tiktok_combined_var.value = False
        app.facebook_combined_var.value = True

        self.assertFalse(app._social_combined_enabled("tiktok"))
        self.assertTrue(app._social_combined_enabled("facebook"))

    def test_combined_social_panel_routes_each_execution_mode(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_social_selection = _Entry("1-3")
        calls = []
        app.run_combined_social = lambda entry, **kwargs: calls.append(
            (entry, kwargs)
        )

        app.run_combined_social_sequential()
        app.run_combined_social_parallel()
        app.run_combined_social_adaptive()

        self.assertEqual(
            [
                (app.ent_social_selection, {}),
                (app.ent_social_selection, {"parallel": True}),
                (app.ent_social_selection, {"adaptive": True}),
            ],
            calls,
        )

    def test_combined_social_runs_both_platforms_in_randomized_order(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry("tt seed")
        app.ent_tt_channel = _Entry("tt target")
        app.ent_fb_seed = _Entry("fb seed")
        app.ent_fb_target = _Entry("fb target")
        app.parse_targets = lambda entry_widget=None: ["d1"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        events = []
        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (
                events.append("tiktok") or (True, "ok")
            ),
            facebook_automation_workflow=lambda *_args, **_kwargs: (
                events.append("facebook") or (True, "ok")
            ),
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="S1"),
            patch.object(
                GUIApp,
                "_random_social_order",
                return_value=["facebook", "tiktok"],
            ),
            patch("builtins.print"),
        ):
            app.run_combined_social(_Entry("1"))

        self.assertEqual(["facebook", "tiktok"], events)

    def test_combined_social_final_report_includes_per_device_duration(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry("tt seed")
        app.ent_tt_channel = _Entry("tt target")
        app.ent_fb_seed = _Entry("fb seed")
        app.ent_fb_target = _Entry("fb target")
        app.parse_targets = lambda entry_widget=None: ["d1"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        finished_reports = []

        class FakeTracker:
            def __init__(self, *_args, **_kwargs):
                pass

            def set_active_device(self, *_args, **_kwargs):
                return None

            def render_progress_text(self):
                return "Social realtime"

            def start_dashboard(self, _text):
                return None

            def status_callback(self, *_args, **_kwargs):
                return None

            def finish_dashboard(self, text):
                finished_reports.append(text)

        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (True, "ok"),
            facebook_automation_workflow=lambda *_args, **_kwargs: (True, "ok"),
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", [123]),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="S2"),
            patch("gui_app.main.TelegramRealtimeTracker", FakeTracker),
            patch.object(
                GUIApp,
                "_random_social_order",
                return_value=["facebook", "tiktok"],
            ),
            patch("gui_app.time.monotonic", side_effect=[100.0, 225.0]),
            patch("builtins.print"),
        ):
            app.run_combined_social(_Entry("1"))

        self.assertEqual(1, len(finished_reports))
        self.assertIn(
            "Thời gian hoàn thành: **2 phút 5 giây**",
            finished_reports[0],
        )

    def test_combined_social_clears_recents_before_success_report(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry("tt seed")
        app.ent_tt_channel = _Entry("tt target")
        app.ent_fb_seed = _Entry("fb seed")
        app.ent_fb_target = _Entry("fb target")
        app.parse_targets = lambda entry_widget=None: ["d1"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        events = []

        class FakeTracker:
            def __init__(self, *_args, **_kwargs):
                pass

            def set_active_device(self, *_args, **_kwargs):
                return None

            def render_progress_text(self):
                return "Social realtime"

            def start_dashboard(self, _text):
                return None

            def status_callback(self, *_args, **_kwargs):
                return None

            def finish_dashboard(self, _text):
                events.append("report")

        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (True, "ok"),
            facebook_automation_workflow=lambda *_args, **_kwargs: (True, "ok"),
            clear_recent_apps=lambda device_id: events.append(
                ("clear", device_id)
            ) or True,
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", [123]),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="S1"),
            patch("gui_app.main.TelegramRealtimeTracker", FakeTracker),
            patch.object(
                GUIApp,
                "_random_social_order",
                return_value=["tiktok", "facebook"],
            ),
            patch("builtins.print"),
        ):
            app.run_combined_social(_Entry("1"))

        self.assertEqual([("clear", "d1"), "report"], events)

    def test_combined_social_still_runs_second_platform_after_first_fails(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry("tt seed")
        app.ent_tt_channel = _Entry("tt target")
        app.ent_fb_seed = _Entry("fb seed")
        app.ent_fb_target = _Entry("fb target")
        app.parse_targets = lambda entry_widget=None: ["d1"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        events = []
        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (
                events.append("tiktok") or (False, "tt failed")
            ),
            facebook_automation_workflow=lambda *_args, **_kwargs: (
                events.append("facebook") or (True, "ok")
            ),
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="S1"),
            patch.object(
                GUIApp,
                "_random_social_order",
                return_value=["tiktok", "facebook"],
            ),
            patch("builtins.print"),
        ):
            app.run_combined_social(_Entry("1"))

        self.assertEqual(["tiktok", "facebook"], events)

    def test_combined_social_still_runs_second_platform_after_first_raises(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry("tt seed")
        app.ent_tt_channel = _Entry("tt target")
        app.ent_fb_seed = _Entry("fb seed")
        app.ent_fb_target = _Entry("fb target")
        app.parse_targets = lambda entry_widget=None: ["d1"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        logs = []
        app.log_message = logs.append
        events = []

        def broken_tiktok(*_args, **_kwargs):
            events.append("tiktok")
            raise RuntimeError("unexpected tt error")

        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=broken_tiktok,
            facebook_automation_workflow=lambda *_args, **_kwargs: (
                events.append("facebook") or (True, "ok")
            ),
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="S1"),
            patch.object(
                GUIApp,
                "_random_social_order",
                return_value=["tiktok", "facebook"],
            ),
            patch("builtins.print"),
        ):
            app.run_combined_social(_Entry("1"))

        self.assertEqual(["tiktok", "facebook"], events)
        self.assertTrue(
            any("BẮT ĐẦU MODULE TIKTOK ĐẦY ĐỦ" in log for log in logs)
        )
        self.assertTrue(
            any("CHUYỂN SANG MODULE FACEBOOK" in log for log in logs)
        )

    def test_combined_social_adaptive_randomizes_social_waves(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry("tt seed")
        app.ent_tt_channel = _Entry("tt target")
        app.ent_fb_seed = _Entry("fb seed")
        app.ent_fb_target = _Entry("fb target")
        app.parse_targets = lambda entry_widget=None: ["d1", "d2", "d3"]
        app.bulk_disable_rotation = lambda target_devices=None: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        captured = []
        workflow_calls = []
        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda device, **_kwargs: (
                workflow_calls.append((device, "tiktok")) or (True, "ok")
            ),
            facebook_automation_workflow=lambda device, **_kwargs: (
                workflow_calls.append((device, "facebook")) or (True, "ok")
            ),
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", side_effect=lambda d: d),
            patch("gui_app.run_adaptive", side_effect=_run_immediately(captured)),
            patch("builtins.print"),
        ):
            app.run_combined_social(_Entry("1-3"), adaptive=True)

        devices, policy, kwargs = captured[0]
        self.assertEqual(["d1", "d2", "d3"], devices)
        self.assertEqual(3, policy.max_workers)
        self.assertTrue(kwargs["randomize_queue"])
        self.assertTrue(kwargs["randomize_wave_size"])
        self.assertTrue(callable(kwargs["on_wave"]))
        self.assertCountEqual(
            [
                (device, platform)
                for device in ("d1", "d2", "d3")
                for platform in ("tiktok", "facebook")
            ],
            workflow_calls,
        )

    def test_social_queue_prepares_only_requested_social_platform(self):
        app = GUIApp.__new__(GUIApp)
        events = []
        fake_adb = SimpleNamespace(
            device_workflow_scope=lambda _device: nullcontext(),
            ensure_facebook_ready=lambda device: events.append(
                ("facebook", device)
            ) or True,
            launch_tiktok=lambda device: events.append(("tiktok", device)),
            is_tiktok_in_foreground=lambda _device: True,
        )

        with patch("gui_app.main.adb", fake_adb):
            app.prepare_social_targets(["d1", "d2"], "facebook")
            app.prepare_social_targets(["d1", "d2"], "tiktok")

        self.assertCountEqual(
            [("facebook", "d1"), ("facebook", "d2")],
            [event for event in events if event[0] == "facebook"],
        )
        self.assertCountEqual(
            [("tiktok", "d1"), ("tiktok", "d2")],
            [event for event in events if event[0] == "tiktok"],
        )

    def test_tiktok_adaptive_uses_random_social_policy(self):
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

        self.assertEqual(3, captured[0][1].max_workers)
        self.assertEqual((5, 15), captured[0][1].stagger_seconds)
        self.assertTrue(captured[0][2]["randomize_queue"])
        self.assertTrue(captured[0][2]["randomize_wave_size"])
        self.assertTrue(callable(captured[0][2]["on_wave"]))

    def test_facebook_adaptive_uses_random_social_policy(self):
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
        self.assertEqual((5, 15), captured[0][1].stagger_seconds)
        self.assertTrue(captured[0][2]["randomize_queue"])
        self.assertTrue(captured[0][2]["randomize_wave_size"])
        self.assertTrue(callable(captured[0][2]["on_wave"]))


if __name__ == "__main__":
    unittest.main()
