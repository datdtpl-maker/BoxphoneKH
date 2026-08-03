import unittest
from unittest.mock import patch

import main


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

    def test_delayed_old_shopee_worker_cannot_run_in_new_session(self):
        old_session = main.start_workflow_session()
        main.start_workflow_session()

        class Message:
            class Chat:
                id = 0

            chat = Chat()

        with (
            patch.object(main, "safe_send_message"),
            patch.object(
                main.adb,
                "shopee_find_and_click_lamdong",
            ) as shopee_workflow,
        ):
            main.run_sequential_shopee_search(
                Message(),
                ["keyword"],
                ["device"],
                use_ai=False,
                session_id=old_session,
            )

        shopee_workflow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
