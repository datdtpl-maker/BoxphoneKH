import json
import socket
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass


PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.googleMapsUri,nextPageToken"
)


class GoogleMapsRankError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GoogleMapsRankResult:
    keyword: str
    found: bool
    rank: int | None
    results_checked: int
    matched_name: str = ""
    formatted_address: str = ""
    google_maps_uri: str = ""
    error: str = ""


def normalize_place_text(value):
    raw = unicodedata.normalize("NFD", str(value or ""))
    without_marks = "".join(
        character for character in raw if unicodedata.category(character) != "Mn"
    )
    return " ".join(without_marks.casefold().split())


def split_google_maps_keywords(value):
    raw = str(value or "").replace(",", "\n")
    seen = set()
    keywords = []
    for line in raw.splitlines():
        keyword = " ".join(line.split())
        normalized = normalize_place_text(keyword)
        if keyword and normalized not in seen:
            seen.add(normalized)
            keywords.append(keyword)
    return keywords


def place_name_matches(candidate_name, target_name):
    candidate = normalize_place_text(candidate_name)
    aliases = split_google_maps_keywords(target_name)
    for alias in aliases:
        target = normalize_place_text(alias)
        if not target:
            continue
        if candidate == target or target in candidate:
            return True
        target_tokens = [token for token in target.split() if len(token) > 1]
        if target_tokens and all(token in candidate for token in target_tokens):
            return True
    return False


class GoogleMapsRankClient:
    def __init__(self, api_key, timeout=20, opener=None):
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen

    def _request_page(self, payload):
        if not self.api_key:
            raise GoogleMapsRankError(
                "missing_key", "Chưa cấu hình Google Maps Platform API Key."
            )

        request = urllib.request.Request(
            PLACES_TEXT_SEARCH_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": PLACES_FIELD_MASK,
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise GoogleMapsRankError(
                    "invalid_key",
                    "Google Maps API Key không hợp lệ hoặc Places API chưa được bật.",
                ) from None
            if exc.code == 429:
                raise GoogleMapsRankError(
                    "rate_limited", "Google Maps API đang giới hạn tần suất truy vấn."
                ) from None
            raise GoogleMapsRankError(
                "http_error", f"Google Maps API trả về HTTP {exc.code}."
            ) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            raise GoogleMapsRankError(
                "network_error", "Không thể kết nối Google Maps API."
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GoogleMapsRankError(
                "invalid_response", "Google Maps API trả về dữ liệu không hợp lệ."
            ) from None

    def search_keyword(
        self,
        keyword,
        target_name,
        location_text="",
        max_results=60,
    ):
        clean_keyword = " ".join(str(keyword or "").split())
        clean_target = " ".join(str(target_name or "").split())
        clean_location = " ".join(str(location_text or "").split())
        if not clean_keyword:
            raise GoogleMapsRankError("missing_keyword", "Từ khóa Google Maps bị trống.")
        if not clean_target:
            raise GoogleMapsRankError(
                "missing_target", "Chưa nhập tên hồ sơ Google Maps mục tiêu."
            )

        limit = max(1, min(int(max_results or 60), 60))
        query = f"{clean_keyword} {clean_location}".strip()
        checked = 0
        page_token = ""

        while checked < limit:
            payload = {
                "textQuery": query,
                "pageSize": min(20, limit - checked),
                "languageCode": "vi",
                "regionCode": "VN",
            }
            if page_token:
                payload["pageToken"] = page_token
            response = self._request_page(payload)
            places = response.get("places") or []
            for place in places:
                checked += 1
                display_name = place.get("displayName") or {}
                name = display_name.get("text") if isinstance(display_name, dict) else ""
                if place_name_matches(name, clean_target):
                    return GoogleMapsRankResult(
                        keyword=clean_keyword,
                        found=True,
                        rank=checked,
                        results_checked=checked,
                        matched_name=name or "",
                        formatted_address=place.get("formattedAddress") or "",
                        google_maps_uri=place.get("googleMapsUri") or "",
                    )
                if checked >= limit:
                    break

            page_token = response.get("nextPageToken") or ""
            if not page_token or not places:
                break

        return GoogleMapsRankResult(
            keyword=clean_keyword,
            found=False,
            rank=None,
            results_checked=checked,
        )
