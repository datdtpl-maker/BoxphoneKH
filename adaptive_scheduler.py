"""Bounded, staggered scheduling for device automation workflows."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import random
import time


@dataclass(frozen=True)
class AdaptivePolicy:
    max_workers: int
    stagger_seconds: tuple[int, int]


PLATFORM_POLICIES = {
    "facebook": AdaptivePolicy(max_workers=3, stagger_seconds=(5, 15)),
    "tiktok": AdaptivePolicy(max_workers=4, stagger_seconds=(5, 15)),
    "social": AdaptivePolicy(max_workers=3, stagger_seconds=(5, 15)),
}


def _interruptible_sleep(seconds, is_cancelled, sleep_fn):
    remaining = max(0.0, float(seconds))
    while remaining > 0 and not is_cancelled():
        chunk = min(0.25, remaining)
        sleep_fn(chunk)
        remaining -= chunk
    return not is_cancelled()


def run_adaptive(
    devices,
    worker,
    policy,
    *,
    is_cancelled=lambda: False,
    on_wait=None,
    sleep_fn=time.sleep,
    randint_fn=random.randint,
    shuffle_fn=random.shuffle,
    randomize_queue=False,
    randomize_wave_size=False,
    on_wave=None,
):
    """Run one platform with bounded concurrency and staggered starts.

    Results preserve device order. Devices that have not started when the
    workflow is cancelled are intentionally omitted.
    """
    queued = list(enumerate(devices))
    if not queued:
        return []

    if randomize_queue:
        shuffle_fn(queued)

    max_workers = max(1, min(policy.max_workers, len(queued)))
    results = {}
    has_started = False

    if randomize_wave_size:
        total_devices = len(queued)
        started_position = 0
        wave_number = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while queued and not is_cancelled():
                wave_limit = min(max_workers, len(queued))
                # Khi còn ít nhất hai thiết bị, một đợt thích ứng phải khởi
                # động tối thiểu hai máy để không tạo cảm giác chỉ chạy 1 profile.
                wave_min = 2 if wave_limit >= 2 else 1
                wave_size = max(
                    wave_min,
                    min(randint_fn(wave_min, wave_limit), wave_limit),
                )
                wave = [queued.pop(0) for _ in range(wave_size)]
                wave_number += 1
                if on_wave:
                    on_wave(
                        [device_id for _, device_id in wave],
                        wave_number,
                        total_devices,
                    )

                active = {}
                for index, device_id in wave:
                    if is_cancelled():
                        break
                    if has_started:
                        delay = randint_fn(*policy.stagger_seconds)
                        if on_wait:
                            on_wait(
                                device_id,
                                delay,
                                started_position,
                                total_devices,
                            )
                        if not _interruptible_sleep(
                            delay, is_cancelled, sleep_fn
                        ):
                            break

                    future = executor.submit(worker, device_id)
                    active[future] = index
                    started_position += 1
                    has_started = True

                while active:
                    done, _ = wait(
                        tuple(active),
                        timeout=0.25,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in done:
                        index = active.pop(future)
                        results[index] = future.result()

        return [results[index] for index in sorted(results)]

    active = {}
    next_position = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while next_position < len(queued) or active:
            while (
                next_position < len(queued)
                and len(active) < max_workers
                and not is_cancelled()
            ):
                index, device_id = queued[next_position]
                if has_started:
                    delay = randint_fn(*policy.stagger_seconds)
                    if on_wait:
                        on_wait(device_id, delay, next_position, len(queued))
                    if not _interruptible_sleep(
                        delay, is_cancelled, sleep_fn
                    ):
                        break

                future = executor.submit(worker, device_id)
                active[future] = index
                next_position += 1
                has_started = True

            if not active:
                break

            done, _ = wait(
                tuple(active), timeout=0.25, return_when=FIRST_COMPLETED
            )
            for future in done:
                index = active.pop(future)
                results[index] = future.result()

    return [results[index] for index in sorted(results)]
