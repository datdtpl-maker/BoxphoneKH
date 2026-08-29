"""Bounded, staggered scheduling for device automation workflows."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import random
import time


@dataclass(frozen=True)
class AdaptivePolicy:
    max_workers: int
    stagger_seconds: tuple[int, int]
    wave_size_range: tuple[int, int] = (2, 3)
    wave_interval_seconds: tuple[int, int] = (60, 120)


PLATFORM_POLICIES = {
    "facebook": AdaptivePolicy(
        max_workers=40,
        stagger_seconds=(5, 15),
        wave_size_range=(2, 3),
        wave_interval_seconds=(60, 120),
    ),
    "tiktok": AdaptivePolicy(
        max_workers=40,
        stagger_seconds=(5, 15),
        wave_size_range=(2, 3),
        wave_interval_seconds=(60, 120),
    ),
    "social": AdaptivePolicy(
        max_workers=40,
        stagger_seconds=(5, 15),
        wave_size_range=(2, 3),
        wave_interval_seconds=(60, 120),
    ),
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

    total_devices = len(queued)
    results = {}
    active_futures = {}

    # Cơ chế Cuốn Chiếu Theo Đợt (Staggered Rolling Waves):
    # Mỗi đợt mở 2 - 3 profile, sau đó đợi 1 - 2 phút (60 - 120s) rồi tự động mở tiếp đợt sau
    # Các đợt chạy song song gối đầu nhau, không cần chờ đợt trước kết thúc.
    if randomize_wave_size:
        wave_number = 0
        started_position = 0
        has_started_any = False
        wave_size_range = getattr(policy, "wave_size_range", (2, 3))
        wave_interval_range = getattr(
            policy, "wave_interval_seconds", (60, 120)
        )

        with ThreadPoolExecutor(max_workers=max(len(queued), 32)) as executor:
            while queued and not is_cancelled():
                # 1. Chọn kích thước đợt (2 - 3 máy)
                wave_min = wave_size_range[0]
                wave_max = wave_size_range[1]
                wave_limit = min(wave_max, len(queued))
                if len(queued) >= wave_min:
                    wave_size = randint_fn(wave_min, wave_limit)
                else:
                    wave_size = len(queued)
                wave_size = max(1, min(wave_size, len(queued)))

                current_wave = [queued.pop(0) for _ in range(wave_size)]
                wave_number += 1
                if on_wave:
                    on_wave(
                        [device_id for _, device_id in current_wave],
                        wave_number,
                        total_devices,
                    )

                # 2. Khởi chạy các máy trong đợt này (với độ trễ nhẹ 5-15s giữa các máy trong cùng đợt)
                for index, device_id in current_wave:
                    if is_cancelled():
                        break
                    if has_started_any and policy.stagger_seconds[1] > 0:
                        stagger = randint_fn(*policy.stagger_seconds)
                        if stagger > 0:
                            if on_wait:
                                on_wait(
                                    device_id,
                                    stagger,
                                    started_position,
                                    total_devices,
                                )
                            if not _interruptible_sleep(
                                stagger, is_cancelled, sleep_fn
                            ):
                                break

                    fut = executor.submit(worker, device_id)
                    active_futures[fut] = index
                    started_position += 1
                    has_started_any = True

                # 3. Tính từ thời điểm đợt hiện tại mở: chờ 1 - 2 phút (60 - 120s) rồi mở đợt tiếp theo
                if queued and not is_cancelled():
                    wave_interval = randint_fn(*wave_interval_range)
                    if wave_interval > 0:
                        _interruptible_sleep(
                            wave_interval, is_cancelled, sleep_fn
                        )

            # 4. Đợi tất cả các máy đang chạy hoàn tất
            while active_futures:
                done, _ = wait(
                    tuple(active_futures),
                    timeout=0.25,
                    return_when=FIRST_COMPLETED,
                )
                for fut in done:
                    index = active_futures.pop(fut)
                    results[index] = fut.result()

        return [results[index] for index in sorted(results)]

    # Trường hợp không phân chia đợt ngẫu nhiên (chạy pool giới hạn max_workers)
    max_workers = max(1, min(policy.max_workers, len(queued)))
    next_position = 0
    has_started = False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while next_position < len(queued) or active_futures:
            while (
                next_position < len(queued)
                and len(active_futures) < max_workers
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
                active_futures[future] = index
                next_position += 1
                has_started = True

            if not active_futures:
                break

            done, _ = wait(
                tuple(active_futures), timeout=0.25, return_when=FIRST_COMPLETED
            )
            for future in done:
                index = active_futures.pop(future)
                results[index] = future.result()

    return [results[index] for index in sorted(results)]
