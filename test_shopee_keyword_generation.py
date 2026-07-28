import unittest
from unittest.mock import patch

import config


class ShopeeKeywordGenerationTests(unittest.TestCase):
    @patch("config.urllib.request.urlopen", side_effect=OSError("offline"))
    def test_expanded_keywords_generate_ten_per_input(self, _urlopen):
        inputs = [f"từ khóa {index}" for index in range(10)]
        generated = config.generate_keywords_via_gemini("key", inputs)
        self.assertEqual(100, len(generated))

    @patch("config.urllib.request.urlopen", side_effect=OSError("offline"))
    def test_tier2_keywords_generate_ten_per_input(self, _urlopen):
        inputs = [f"tiêu đề sản phẩm {index}" for index in range(10)]
        generated = config.generate_keywords_tier2_via_gemini("key", inputs)
        self.assertEqual(100, len(generated))


if __name__ == "__main__":
    unittest.main()
