import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = ROOT / "installer.iss"
INSTALLER_PATH = ROOT / "release" / "BoxPhoneControl-Setup.exe"


def find_iscc():
    configured = os.getenv("INNO_SETUP_COMPILER")
    candidates = [
        Path(configured) if configured else None,
        Path(os.getenv("LOCALAPPDATA", ""))
        / "Programs"
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.getenv("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.getenv("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    discovered = shutil.which("ISCC.exe") or shutil.which("iscc")
    if discovered:
        candidates.insert(0, Path(discovered))

    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Khong tim thay Inno Setup 6 (ISCC.exe). "
        "Cai dat JRSoftware.InnoSetup hoac dat INNO_SETUP_COMPILER."
    )


def build_installer():
    app_exe = ROOT / "dist" / "BoxPhoneControl" / "BoxPhoneControl.exe"
    if not app_exe.is_file():
        raise FileNotFoundError(
            "Chua co ban onedir. Hay chay python build_exe.py truoc."
        )

    INSTALLER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if INSTALLER_PATH.exists():
        INSTALLER_PATH.unlink()

    command = [str(find_iscc()), "/Qp", str(SCRIPT_PATH)]
    subprocess.run(command, cwd=ROOT, check=True)
    if not INSTALLER_PATH.is_file():
        raise FileNotFoundError(f"Inno Setup khong tao ra {INSTALLER_PATH}")

    copy_dir = ROOT / "CHỈ COPY FILE NÀY"
    if copy_dir.exists():
        shutil.copy2(INSTALLER_PATH, copy_dir / "BoxPhoneControl-Setup.exe")
        print("[Build] Da sao chep bo cai vao thu muc: CHI COPY FILE NAY/BoxPhoneControl-Setup.exe")

    return INSTALLER_PATH


if __name__ == "__main__":
    print(build_installer())
