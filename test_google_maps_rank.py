import io
import json
import unittest
import urllib.error

from google_maps_rank import (
    GoogleMapsRankClient,
    GoogleMapsRankError,
    place_name_matches,
    split_google_maps_keywords,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class GoogleMapsRankTests(unittest.TestCase):
    def test_keyword_parser_deduplicates_accents_and_commas(self):
        self.assertEqual(
            ["Spa Phan Thiết", "trị mụn"],
            split_google_maps_keywords(
                "Spa Phan Thiết, spa phan thiet\ntrị mụn"
            ),
        )

    def test_place_match_accepts_target_inside_full_profile_name(self):
        self.assertTrue(
            place_name_matches(
                "Nhà thuốc Khải Hoàn Skincare - Spa lấy mụn Phan Thiết",
                "Khải Hoàn Skincare",
            )
        )

    def test_search_returns_rank_across_multiple_pages(self):
        pages = iter(
            [
                {
                    "places": [
                        {"displayName": {"text": "Địa điểm A"}},
                        {"displayName": {"text": "Địa điểm B"}},
                    ],
                    "nextPageToken": "page-2",
                },
                {
                    "places": [
                        {
                            "displayName": {
                                "text": "Nhà thuốc Khải Hoàn Skincare - Spa"
                            },
                            "formattedAddress": "Địa chỉ mẫu",
                            "googleMapsUri": "https://maps.google.com/example",
                        }
                    ]
                },
            ]
        )
        requests = []

        def opener(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return _Response(next(pages))

        result = GoogleMapsRankClient("test-key", opener=opener).search_keyword(
            "spa lấy mụn", "Khải Hoàn Skincare", "Phan Thiết"
        )

        self.assertTrue(result.found)
        self.assertEqual(3, result.rank)
        self.assertEqual("page-2", requests[1]["pageToken"])
        self.assertEqual("spa lấy mụn Phan Thiết", requests[0]["textQuery"])

    def test_search_returns_not_found_with_checked_count(self):
        client = GoogleMapsRankClient(
            "test-key", opener=lambda *_args, **_kwargs: _Response(
                {"places": [{"displayName": {"text": "Địa điểm khác"}}]}
            )
        )
        result = client.search_keyword("spa", "Hồ sơ mục tiêu")
        self.assertFalse(result.found)
        self.assertEqual(1, result.results_checked)

    def test_missing_key_is_reported_without_network_call(self):
        with self.assertRaises(GoogleMapsRankError) as context:
            GoogleMapsRankClient("").search_keyword("spa", "Hồ sơ")
        self.assertEqual("missing_key", context.exception.code)

    def test_http_auth_error_has_actionable_message(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", {}, io.BytesIO()
            )

        with self.assertRaises(GoogleMapsRankError) as context:
            GoogleMapsRankClient("bad", opener=opener).search_keyword(
                "spa", "Hồ sơ"
            )
        self.assertEqual("invalid_key", context.exception.code)


if __name__ == "__main__":
    unittest.main()
