import os
import shutil
import subprocess
import sys
from pathlib import Path

from build_installer import build_installer


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "BoxPhoneControl"
APP_EXE = APP_DIR / "BoxPhoneControl.exe"


def _run(command):
    rendered = subprocess.list2cmdline([str(item) for item in command])
    print(f"[Build] Chay: {rendered}")
    subprocess.run(command, cwd=ROOT, check=True)


def _clean_build_directories():
    for path in (ROOT / "build", DIST_DIR):
        if path.exists():
            shutil.rmtree(path)
    spec_path = ROOT / "BoxPhoneControl.spec"
    if spec_path.exists():
        spec_path.unlink()


def build():
    print("[Build] Tao ban onedir toi uu toc do khoi dong...")
    _clean_build_directories()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        f"--icon={ROOT / 'app_icon.ico'}",
        f"--add-data={ROOT / 'app_icon.ico'}{os.pathsep}.",
        "--collect-all",
        "customtkinter",
        "--name",
        "BoxPhoneControl",
        str(ROOT / "gui_app.py"),
    ]
    _run(command)

    if not APP_EXE.is_file():
        raise FileNotFoundError(f"Khong tim thay file ung dung: {APP_EXE}")

    installer = build_installer()
    print(f"[Build] Ung dung onedir: {APP_EXE}")
    print(f"[Build] Bo cai Windows: {installer}")
    return installer


if __name__ == "__main__":
    try:
        build()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[Build] THAT BAI: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
