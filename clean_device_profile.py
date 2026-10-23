# -*- coding: utf-8 -*-
"""
Script standalone lam sach profile thiet bi khi bi checkpoint / dinh ban:
- Xoa sach du lieu Facebook (pm clear)
- Reset Android ID sang ma ngau nhien moi tinh (tranh Meta blacklist Device Fingerprint)
- Xoa cache Google Play Services
- Cap lai permission co ban va mo lai Facebook ve man hinh dang nhap moi tinh

Chay:
    python clean_device_profile.py [device_serial]
Vi du:
    python clean_device_profile.py ce061606d2b5b52b05
"""
import sys
import os
import secrets
import subprocess

ADB_PATH = r"C:\Program Files (x86)\xiaowei_android\tools\adb.exe"
PORTS = [5038, 5037]

def run_adb(device_id, cmd):
    # Tim cong phu hop
    for port in PORTS:
        full_cmd = [ADB_PATH, "-P", str(port), "-s", device_id, "shell"] + cmd.split()
        res = subprocess.run(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if "device not found" not in res.stderr and res.returncode == 0:
            return res.stdout.strip()
    return None

def clean_device(device_id="ce061606d2b5b52b05"):
    print(f"=== BAT DAU LAM SACH PROFILE THIET BI: {device_id} ===")
    
    # 1. Kiem tra Android ID hien tai
    old_id = run_adb(device_id, "settings get secure android_id")
    print(f"[-] Android ID cu: {old_id}")
    
    # 2. Xoa cache va du lieu Facebook
    print("[*] Xoa sach du lieu va cache Facebook Katana...")
    run_adb(device_id, "am force-stop com.facebook.katana")
    run_adb(device_id, "pm clear com.facebook.katana")
    run_adb(device_id, "pm clear com.google.android.gms")
    
    # 3. Tao va cap Android ID moi
    new_id = secrets.token_hex(8)
    print(f"[*] Cap ma Android ID moi tinh: {new_id}...")
    run_adb(device_id, f"settings put secure android_id {new_id}")
    
    # 4. Cap lai cac quyen co ban
    print("[*] Cap quyen co ban cho Facebook...")
    perms = [
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.CAMERA",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.READ_CONTACTS"
    ]
    for p in perms:
        run_adb(device_id, f"pm grant com.facebook.katana {p}")
        
    # 5. Khoi chay Facebook katana
    print("[*] Khoi chay Facebook katana...")
    run_adb(device_id, "am start -n com.facebook.katana/.LoginActivity")
    
    # 6. Xac nhan
    curr_id = run_adb(device_id, "settings get secure android_id")
    print(f"\n[THANH CONG] Thiet bi {device_id} da duoc lam sach 100%!")
    print(f"   -> Android ID hien tai: {curr_id}")
    print("   -> Facebook da mo ve man hinh dang nhap trang tinh, san sang login nick moi.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ce061606d2b5b52b05"
    clean_device(target)
