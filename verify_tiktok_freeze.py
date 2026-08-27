"""Guard chống chỉnh sửa ngoài ý muốn đối với module TikTok đã ổn định."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "tiktok_freeze_manifest.json"
PRODUCTION_FILES = (
    "adb_controller.py",
    "gui_app.py",
    "main.py",
    "config.py",
    "notion_keyword_sync.py",
    "adaptive_scheduler.py",
)
FROZEN_TEST_FILES = (
    "test_tiktok_search_input.py",
    "test_gui_tiktok_status.py",
    "test_tiktok_telegram_tracker.py",
)
TT_NAME_PATTERN = re.compile(r"(?:^|_)tt(?:_|$)")


def _is_tiktok_name(value: str) -> bool:
    lowered = value.casefold()
    return "tiktok" in lowered or TT_NAME_PATTERN.search(lowered) is not None


def _contains_tiktok_marker(node: ast.AST) -> bool:
    return _is_tiktok_name(ast.dump(node, include_attributes=False))


class TikTokSurfaceCollector(ast.NodeVisitor):
    """Thu thập implementation TikTok mà không khóa nguyên file dùng chung."""

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []
        self.scope: list[str] = []

    def _add(self, kind: str, node: ast.AST) -> None:
        identity = ".".join(self.scope) or "<module>"
        payload = ast.dump(node, annotate_fields=True, include_attributes=False)
        self.items.append((f"{kind}:{identity}", payload))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        if _is_tiktok_name(node.name):
            self._add("function", node)
        else:
            self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if _contains_tiktok_marker(node):
            self._add("assign", node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if _contains_tiktok_marker(node):
            self._add("annassign", node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _contains_tiktok_marker(node):
            self._add("call", node)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            if key is None:
                continue
            pair = ast.Tuple(elts=[key, value], ctx=ast.Load())
            if _contains_tiktok_marker(pair):
                self._add("dict-entry", pair)
        self.generic_visit(node)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _production_fingerprint(path: Path) -> tuple[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = TikTokSurfaceCollector()
    collector.visit(tree)
    items = sorted(set(collector.items))
    payload = json.dumps(
        items,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload), len(items)


def current_baseline() -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    for relative in PRODUCTION_FILES:
        digest, item_count = _production_fingerprint(ROOT / relative)
        files[relative] = {"sha256": digest, "items": item_count}
    for relative in FROZEN_TEST_FILES:
        payload = (ROOT / relative).read_bytes()
        files[relative] = {
            "sha256": _sha256_bytes(payload),
            "items": 1,
        }
    return {
        "schema": 1,
        "baseline": "BoxPhoneControl 1.0.16 - TikTok frozen",
        "files": files,
    }


def verify(manifest_path: Path = MANIFEST_PATH) -> list[str]:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = current_baseline()
    errors: list[str] = []
    expected_files = expected.get("files", {})
    actual_files = actual["files"]
    for relative, expected_info in expected_files.items():
        actual_info = actual_files.get(relative)
        if actual_info is None:
            errors.append(f"Thiếu file được bảo vệ: {relative}")
            continue
        if expected_info != actual_info:
            errors.append(
                f"TikTok đã thay đổi ngoài baseline: {relative} "
                f"(expected {expected_info}, actual {actual_info})"
            )
    for relative in sorted(set(actual_files) - set(expected_files)):
        errors.append(f"Manifest TikTok thiếu file: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--print-baseline",
        action="store_true",
        help="In baseline hiện tại để cập nhật khi người dùng cho phép rõ ràng.",
    )
    args = parser.parse_args()
    if args.print_baseline:
        print(json.dumps(current_baseline(), ensure_ascii=False, indent=2))
        return 0
    errors = verify()
    if errors:
        print("\n".join(errors))
        return 1
    print("TikTok freeze guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
