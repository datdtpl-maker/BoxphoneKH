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

    def test_randomized_waves_shuffle_positions_and_run_every_device(self):
        started = []
        waves = []
        randint_calls = []

        def deterministic_randint(low, high):
            randint_calls.append((low, high))
            if low in (1, 2):
                return min(2, high)
            return 0

        def reverse_in_place(items):
            items.reverse()

        results = run_adaptive(
            ["S1", "S2", "S3", "S4", "S5"],
            lambda device_id: started.append(device_id) or device_id,
            AdaptivePolicy(3, (0, 0)),
            sleep_fn=lambda _seconds: None,
            randint_fn=deterministic_randint,
            shuffle_fn=reverse_in_place,
            randomize_queue=True,
            randomize_wave_size=True,
            on_wave=lambda devices, wave, total: waves.append(
                (list(devices), wave, total)
            ),
        )

        self.assertEqual(["S5", "S4", "S3", "S2", "S1"], started)
        self.assertEqual(["S1", "S2", "S3", "S4", "S5"], results)
        self.assertEqual(
            [
                (["S5", "S4"], 1, 5),
                (["S3", "S2"], 2, 5),
                (["S1"], 3, 5),
            ],
            waves,
        )
        self.assertIn((2, 3), randint_calls)

    def test_randomized_wave_starts_at_least_two_when_devices_are_available(self):
        waves = []

        run_adaptive(
            ["S1", "S2", "S3"],
            lambda device_id: device_id,
            AdaptivePolicy(3, (0, 0)),
            randint_fn=lambda low, _high: low,
            sleep_fn=lambda _seconds: None,
            randomize_wave_size=True,
            on_wave=lambda devices, *_: waves.append(list(devices)),
        )

        self.assertEqual(2, len(waves[0]))

    def test_staggered_rolling_waves_intervals(self):
        sleeps = []
        waves = []

        results = run_adaptive(
            ["S1", "S2", "S3", "S4", "S5", "S6"],
            lambda device_id: device_id,
            AdaptivePolicy(
                40,
                (0, 0),
                wave_size_range=(2, 3),
                wave_interval_seconds=(60, 120),
            ),
            randint_fn=lambda low, high: 2 if high in (2, 3) else 75,
            sleep_fn=lambda seconds: sleeps.append(seconds),
            randomize_wave_size=True,
            on_wave=lambda devices, wave, total: waves.append(list(devices)),
        )

        self.assertEqual(["S1", "S2", "S3", "S4", "S5", "S6"], results)
        self.assertEqual([["S1", "S2"], ["S3", "S4"], ["S5", "S6"]], waves)
        # Giữa 3 đợt có 2 khoảng chờ (75s x 2 = 150s)
        self.assertAlmostEqual(150, sum(sleeps))


if __name__ == "__main__":
    unittest.main()
