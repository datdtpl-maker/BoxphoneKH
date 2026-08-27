import json
import tempfile
import unittest
from pathlib import Path

from verify_tiktok_freeze import MANIFEST_PATH, verify


class TikTokFreezeTests(unittest.TestCase):
    def test_tiktok_module_matches_frozen_baseline(self):
        self.assertEqual([], verify())

    def test_guard_rejects_a_changed_tiktok_hash(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["files"]["adb_controller.py"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            altered = Path(temp_dir) / "manifest.json"
            altered.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            errors = verify(altered)
        self.assertTrue(errors)
        self.assertIn("adb_controller.py", errors[0])


if __name__ == "__main__":
    unittest.main()
