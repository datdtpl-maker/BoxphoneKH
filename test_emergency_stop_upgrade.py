import unittest
from unittest.mock import patch, MagicMock
import threading
import time

from adb_controller import ADBController, WorkflowCancelledException
import main


class EmergencyStopUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.adb = ADBController(adb_path="adb")
        self.adb._emergency_stopped = False

    def tearDown(self):
        self.adb._emergency_stopped = False
        main.start_workflow_session()

    def test_emergency_stop_blocks_normal_adb_execution(self):
        self.adb.set_emergency_stopped(True)
        self.assertTrue(self.adb.is_emergency_stopped())

        with self.assertRaises(WorkflowCancelledException):
            self.adb.execute_adb("dev-1", ["shell", "input", "tap", "500", "500"])

    def test_emergency_stop_allows_bypass_emergency(self):
        self.adb.set_emergency_stopped(True)
        # Mock _run_cmd to return success
        self.adb._run_cmd = MagicMock(return_value=(0, "OK", ""))

        code, stdout, stderr = self.adb.execute_adb(
            "dev-1",
            ["shell", "am", "force-stop", "com.ss.android.ugc.trill"],
            bypass_emergency=True,
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "OK")

    def test_keyevent_home_and_recents_bypass_emergency(self):
        self.adb.set_emergency_stopped(True)
        self.adb._run_cmd = MagicMock(return_value=(0, "", ""))

        # Keycode 3 (Home) and 187 (Recents) bypass emergency by default
        code3, _, _ = self.adb.keyevent("dev-1", 3)
        self.assertEqual(code3, 0)

        code187, _, _ = self.adb.keyevent("dev-1", 187)
        self.assertEqual(code187, 0)

        # Other keys do not bypass and raise WorkflowCancelledException
        with self.assertRaises(WorkflowCancelledException):
            self.adb.keyevent("dev-1", 66)  # Enter key

    def test_interruptible_sleep_aborts_immediately_on_emergency_stop(self):
        self.adb.set_emergency_stopped(True)
        start = time.monotonic()
        with self.assertRaises(WorkflowCancelledException):
            self.adb.interruptible_sleep(10.0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.5)

    def test_interruptible_sleep_aborts_when_stopped_from_another_thread(self):
        self.adb.set_emergency_stopped(False)

        def stop_after_delay():
            time.sleep(0.1)
            self.adb.set_emergency_stopped(True)

        threading.Thread(target=stop_after_delay, daemon=True).start()

        start = time.monotonic()
        with self.assertRaises(WorkflowCancelledException):
            self.adb.interruptible_sleep(5.0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0)

    def test_main_cancel_all_workflows_engages_emergency_stop(self):
        main.start_workflow_session()
        self.assertFalse(main.adb.is_emergency_stopped())

        main.cancel_all_workflows()
        self.assertTrue(main.adb.is_emergency_stopped())
        self.assertTrue(main.is_cancelled())

    def test_main_start_workflow_session_clears_emergency_stop(self):
        main.cancel_all_workflows()
        self.assertTrue(main.adb.is_emergency_stopped())

        main.start_workflow_session()
        self.assertFalse(main.adb.is_emergency_stopped())
        self.assertFalse(main.is_cancelled())

    @patch("main.get_ordered_devices", return_value=["dev-mock-1", "dev-mock-2"])
    def test_emergency_stop_all_devices_resets_flag_at_completion(self, _mock_devices):
        with patch.object(main.adb, "emergency_stop_and_clear_recents", return_value=True):
            main.emergency_stop_all_devices()
            # Flag should be reset to False so next actions are accepted
            self.assertFalse(main.adb.is_emergency_stopped())


if __name__ == "__main__":
    unittest.main()
