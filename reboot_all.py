import sys
import os
from concurrent.futures import ThreadPoolExecutor

# Them thu muc hien tai vao sys.path de import adb_controller
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from adb_controller import ADBController

def reboot_single_device(adb, dev, idx, total):
    dev_label = f"S{idx+1}" if idx < 19 else "Samsung S7"
    print(f"[{idx+1}/{total}] Dang gui lenh reboot thiet bi {dev} ({dev_label})...")
    # Dat timeout ngan 3s de khong bi treo khi thiet bi ngat ket noi adb dot ngot
    try:
        adb.execute_adb(dev, ["reboot"], timeout=3)
        print(f"[{idx+1}/{total}] Gui lenh reboot den {dev_label} thanh cong!")
    except Exception as e:
        print(f"[{idx+1}/{total}] Gui lenh reboot den {dev_label} co loi (co the da ngat ket noi): {e}")

def reboot_all_devices():
    adb = ADBController()
    devices = adb.get_devices()
    total = len(devices)
    print(f"Tim thay {total} thiet bi dang ket noi.")
    
    # Su dung ThreadPoolExecutor de gui lenh song song cho tat ca cac thiet bi cung luc
    with ThreadPoolExecutor(max_workers=max(1, total)) as executor:
        for idx, dev in enumerate(devices):
            executor.submit(reboot_single_device, adb, dev, idx, total)
            
    print("Hoan thanh gui lenh reboot cho toan bo may.")

if __name__ == "__main__":
    reboot_all_devices()
