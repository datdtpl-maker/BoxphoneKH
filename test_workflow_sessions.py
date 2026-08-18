import unittest
import threading
import time
import main
from adb_controller import ADBController


class WorkflowSessionTests(unittest.TestCase):
    def setUp(self):
        main.cancel_flag = False
        main.cancel_sequential = False

    def tearDown(self):
        main.cancel_flag = False
        main.cancel_sequential = False

    def test_old_worker_stays_cancelled_after_new_workflow_starts(self):
        old_session = main.start_workflow_session()
        old_is_cancelled = main.make_session_cancel_checker(old_session)

        main.cancel_all_workflows()
        new_session = main.start_workflow_session()
        new_is_cancelled = main.make_session_cancel_checker(new_session)

        self.assertTrue(old_is_cancelled())
        self.assertFalse(new_is_cancelled())

    def test_starting_new_workflow_invalidates_previous_workflow(self):
        old_session = main.start_workflow_session()
        old_is_cancelled = main.make_session_cancel_checker(old_session)

        new_session = main.start_workflow_session()
        new_is_cancelled = main.make_session_cancel_checker(new_session)

        self.assertTrue(old_is_cancelled())
        self.assertFalse(new_is_cancelled())

    def test_global_emergency_stop_cancels_current_session(self):
        session = main.start_workflow_session()
        is_cancelled = main.make_session_cancel_checker(session)

        main.cancel_all_workflows()

        self.assertTrue(is_cancelled())

    def test_new_platform_waits_until_old_device_workflow_releases_control(self):
        controller = ADBController(adb_path="adb")
        old_entered = threading.Event()
        release_old = threading.Event()
        new_entered = threading.Event()

        def old_workflow():
            with controller.device_workflow_scope("device-1"):
                old_entered.set()
                release_old.wait(timeout=2)

        def new_workflow():
            with controller.device_workflow_scope("device-1"):
                new_entered.set()

        old_thread = threading.Thread(target=old_workflow)
        new_thread = threading.Thread(target=new_workflow)
        old_thread.start()
        self.assertTrue(old_entered.wait(timeout=1))
        new_thread.start()
        time.sleep(0.05)

        self.assertFalse(
            new_entered.is_set(),
            "Hai nền tảng không được đồng thời điều khiển cùng một thiết bị",
        )

        release_old.set()
        old_thread.join(timeout=1)
        new_thread.join(timeout=1)
        self.assertTrue(new_entered.is_set())


if __name__ == "__main__":
    unittest.main()
