import sys
import os

# Them thu muc hien tai vao sys.path de import adb_controller
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from adb_controller import ADBController

def disable_rotation_all():
    adb = ADBController()
    devices = adb.get_devices()
    print(f"Tim thay {len(devices)} thiet bi dang ket noi.")
    for idx, dev in enumerate(devices):
        dev_label = f"S{idx+1}" if idx < 19 else "Samsung S7"
        print(f"[{idx+1}/{len(devices)}] Dang tat xoay man hinh cho thiet bi {dev} ({dev_label})...")
        # accelerometer_rotation = 0 (tat tu dong xoay)
        code, stdout, stderr = adb.execute_adb(dev, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
        # user_rotation = 0 (khoa o che do dung - Portrait)
        adb.execute_adb(dev, ["shell", "settings", "put", "system", "user_rotation", "0"])
        if code == 0:
            print(f"  -> Thanh cong!")
        else:
            print(f"  -> That bai! Loi: {stderr}")

if __name__ == "__main__":
    disable_rotation_all()
