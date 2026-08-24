import unittest

import config


class SocialTimingPolicyTests(unittest.TestCase):
    def test_pre_target_browsing_is_short_and_target_browsing_is_primary(self):
        self.assertLessEqual(config.SOCIAL_CROSS_WARMUP_MAX, 20)
        self.assertLessEqual(config.TIKTOK_STEP1_TOTAL_MAX, 20)
        self.assertLessEqual(config.TIKTOK_STEP2_TOTAL_MAX, 15)
        self.assertLessEqual(
            config.SOCIAL_CROSS_WARMUP_MAX
            + config.TIKTOK_STEP1_TOTAL_MAX
            + config.TIKTOK_STEP2_TOTAL_MAX,
            60,
        )
        self.assertGreaterEqual(config.TIKTOK_STEP3_TOTAL_MIN, 180)

        self.assertLessEqual(config.FACEBOOK_STEP1_FEED_MAX, 20)
        self.assertLessEqual(config.FACEBOOK_STEP2_RESULTS_MAX, 15)
        self.assertLessEqual(
            config.SOCIAL_CROSS_WARMUP_MAX
            + config.FACEBOOK_STEP1_FEED_MAX
            + config.FACEBOOK_STEP2_RESULTS_MAX,
            60,
        )
        self.assertGreaterEqual(config.FACEBOOK_STEP3_PAGE_MIN, 180)


if __name__ == "__main__":
    unittest.main()
