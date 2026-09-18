# -*- coding: utf-8 -*-
"""
interaction_tracker.py - Quản lý lịch sử tương tác (Like, Thả tim, Bookmark...)
cho từng thiết bị/tài khoản nhằm chống tương tác trùng lặp hoặc hủy Like.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

try:
    import config
    DEFAULT_STORAGE_DIR = config.BASE_DIR
except Exception:
    DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger("InteractionTracker")


class InteractionTracker:
    """Quản lý bộ nhớ tương tác thread-safe lưu vào interaction_history.json."""

    def __init__(self, file_path: Optional[Path] = None, max_records_per_device: int = 5000):
        if file_path is None:
            self.file_path = Path(DEFAULT_STORAGE_DIR) / "interaction_history.json"
        else:
            self.file_path = Path(file_path)
        self.max_records_per_device = max_records_per_device
        self._lock = threading.Lock()
        self._data = {"version": 1, "records": {}}
        self._load()

    def _load(self):
        """Đọc lịch sử từ ổ đĩa với cơ chế tự phục hồi nếu file hỏng."""
        if not self.file_path.exists():
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    loaded = json.loads(content)
                    if isinstance(loaded, dict) and "records" in loaded:
                        self._data = loaded
        except Exception as e:
            logger.warning(f"Không thể đọc file {self.file_path}: {e}. Khởi tạo rỗng.")
            self._data = {"version": 1, "records": {}}

    def _save(self):
        """Lưu dữ liệu xuống ổ đĩa dạng nguyên tử (atomic write qua file tạm)."""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.file_path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            # Thay thế nguyên tử
            temp_file.replace(self.file_path)
        except Exception as e:
            logger.error(f"Lỗi khi lưu interaction_history xuống {self.file_path}: {e}")

    def _normalize_key(self, text: str) -> str:
        if not text:
            return ""
        return str(text).strip().lower()

    def has_interacted(
        self, device_id: str, platform: str, item_id: str, action: str = "like"
    ) -> bool:
        """
        Kiểm tra xem thiết bị device_id đã từng tương tác item_id trên platform chưa.
        Trả về True nếu đã tương tác, False nếu chưa.
        """
        if not device_id or not item_id:
            return False
        dev_k = self._normalize_key(device_id)
        plat_k = self._normalize_key(platform)
        act_k = self._normalize_key(action)
        item_k = self._normalize_key(item_id)

        with self._lock:
            dev_records = self._data["records"].get(dev_k, {})
            plat_records = dev_records.get(plat_k, {})
            act_records = plat_records.get(act_k, {})
            return item_k in act_records

    def record_interaction(
        self, device_id: str, platform: str, item_id: str, action: str = "like"
    ) -> bool:
        """
        Ghi nhận thiết bị device_id đã tương tác item_id trên platform kèm timestamp.
        """
        if not device_id or not item_id:
            return False
        dev_k = self._normalize_key(device_id)
        plat_k = self._normalize_key(platform)
        act_k = self._normalize_key(action)
        item_k = self._normalize_key(item_id)
        now_ts = time.time()

        with self._lock:
            if dev_k not in self._data["records"]:
                self._data["records"][dev_k] = {}
            if plat_k not in self._data["records"][dev_k]:
                self._data["records"][dev_k][plat_k] = {}
            if act_k not in self._data["records"][dev_k][plat_k]:
                self._data["records"][dev_k][plat_k][act_k] = {}

            act_records = self._data["records"][dev_k][plat_k][act_k]
            act_records[item_k] = now_ts

            # Giới hạn số lượng bản ghi tránh phình to
            if len(act_records) > self.max_records_per_device:
                sorted_items = sorted(act_records.items(), key=lambda x: x[1])
                excess = len(act_records) - self.max_records_per_device
                for old_key, _ in sorted_items[:excess]:
                    del act_records[old_key]

            self._save()
        return True

    def get_interaction_count(
        self, device_id: Optional[str] = None, platform: Optional[str] = None, action: Optional[str] = None
    ) -> int:
        """Lấy số lượng tương tác đã ghi nhận theo điều kiện lọc."""
        with self._lock:
            total = 0
            dev_k = self._normalize_key(device_id) if device_id else None
            plat_k = self._normalize_key(platform) if platform else None
            act_k = self._normalize_key(action) if action else None

            for d_k, plats in self._data["records"].items():
                if dev_k and d_k != dev_k:
                    continue
                for p_k, acts in plats.items():
                    if plat_k and p_k != plat_k:
                        continue
                    for a_k, items in acts.items():
                        if act_k and a_k != act_k:
                            continue
                        total += len(items)
            return total

    def clear_history(self, device_id: Optional[str] = None, platform: Optional[str] = None):
        """Xóa lịch sử theo thiết bị hoặc nền tảng (dùng khi cần reset)."""
        with self._lock:
            dev_k = self._normalize_key(device_id) if device_id else None
            plat_k = self._normalize_key(platform) if platform else None

            if not dev_k:
                self._data["records"] = {}
            elif dev_k in self._data["records"]:
                if not plat_k:
                    del self._data["records"][dev_k]
                elif plat_k in self._data["records"][dev_k]:
                    del self._data["records"][dev_k][plat_k]
            self._save()


# Singleton dùng chung cho toàn bộ controller và worker
default_tracker = InteractionTracker()


def has_interacted(device_id: str, platform: str, item_id: str, action: str = "like") -> bool:
    return default_tracker.has_interacted(device_id, platform, item_id, action)


def record_interaction(device_id: str, platform: str, item_id: str, action: str = "like") -> bool:
    return default_tracker.record_interaction(device_id, platform, item_id, action)