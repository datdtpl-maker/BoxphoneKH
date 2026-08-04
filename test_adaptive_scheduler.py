import threading
import time
import unittest

from adaptive_scheduler import AdaptivePolicy, run_adaptive


class AdaptiveSchedulerTests(unittest.TestCase):
    def test_limits_concurrency_and_preserves_device_order(self):
        lock = threading.Lock()
        active = 0
        peak = 0

        def worker(device_id):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return f"done-{device_id}"

        results = run_adaptive(
            ["S1", "S2", "S3", "S4"],
            worker,
            AdaptivePolicy(2, (0, 0)),
        )

        self.assertEqual(2, peak)
        self.assertEqual(
            ["done-S1", "done-S2", "done-S3", "done-S4"], results
        )

    def test_staggers_every_start_after_the_first(self):
        waits = []
        sleeps = []

        results = run_adaptive(
            ["S1", "S2", "S3"],
            lambda device_id: device_id,
            AdaptivePolicy(2, (30, 90)),
            on_wait=lambda device, delay, *_: waits.append((device, delay)),
            sleep_fn=lambda seconds: sleeps.append(seconds),
            randint_fn=lambda low, high: 45,
        )

        self.assertEqual(["S1", "S2", "S3"], results)
        self.assertEqual([("S2", 45), ("S3", 45)], waits)
        self.assertAlmostEqual(90, sum(sleeps))

    def test_cancellation_does_not_start_queued_devices(self):
        cancelled = threading.Event()
        started = []

        def worker(device_id):
            started.append(device_id)
            cancelled.set()
            return device_id

        results = run_adaptive(
            ["S1", "S2", "S3"],
            worker,
            AdaptivePolicy(1, (0, 0)),
            is_cancelled=cancelled.is_set,
        )

        self.assertEqual(["S1"], started)
        self.assertEqual(["S1"], results)


if __name__ == "__main__":
    unittest.main()
