import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class DeviceMappingCacheTests(unittest.TestCase):
    def setUp(self):
        main.cached_mapping = {}
        main._device_mapping_cache_key = None
        main._ordered_devices_cache = []

    def _make_leveldb(self, directory, serials):
        path = Path(directory) / "000001.log"
        payload = b"".join(
            serial.encode("utf-8")
            + b"name\x00s"
            + str(index).encode("ascii")
            + b"\x00"
            for index, serial in enumerate(serials, start=1)
        )
        path.write_bytes(payload)
        return path

    def test_repeated_device_queries_reuse_leveldb_mapping(self):
        serials = [f"device-{index:02d}" for index in range(1, 41)]
        real_open = open
        with tempfile.TemporaryDirectory() as folder:
            self._make_leveldb(folder, serials)
            with (
                patch.object(main.adb, "get_devices", return_value=serials),
                patch("main.get_xiaowei_leveldb_dirs", return_value=[folder]),
                patch("builtins.open", wraps=real_open) as open_spy,
            ):
                first = main.get_ordered_devices()
                second = main.get_ordered_devices()

        self.assertEqual(serials, first)
        self.assertEqual(first, second)
        self.assertEqual(1, open_spy.call_count)

    def test_leveldb_change_invalidates_mapping_cache(self):
        serials = ["device-01"]
        real_open = open
        with tempfile.TemporaryDirectory() as folder:
            leveldb = self._make_leveldb(folder, serials)
            with (
                patch.object(main.adb, "get_devices", return_value=serials),
                patch("main.get_xiaowei_leveldb_dirs", return_value=[folder]),
                patch("builtins.open", wraps=real_open) as open_spy,
            ):
                main.get_ordered_devices()
                current_mtime = leveldb.stat().st_mtime
                os.utime(leveldb, (current_mtime + 2, current_mtime + 2))
                main.get_ordered_devices()

        self.assertEqual(2, open_spy.call_count)


if __name__ == "__main__":
    unittest.main()
