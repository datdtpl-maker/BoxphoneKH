import os
import shutil
import subprocess
import sys

def build():
    print("[Build] Bat dau qua trinh dong goi BoxPhoneControl.exe...")
    
    # 1. Chay lenh PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--collect-all", "customtkinter",
        "--name", "BoxPhoneControl",
        "gui_app.py"
    ]
    
    print(f"[Build] Thuc thi lenh: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore')
    
    if result.returncode != 0:
        print("[Build] Loi! PyInstaller gap su co khi dong goi.")
        print(result.stderr)
        sys.exit(1)
        
    print("[Build] PyInstaller da dong goi xong. Dang kiem tra file dau ra...")
    
    # 2. Di chuyen file exe ra thu muc goc
    exe_src = os.path.join("dist", "BoxPhoneControl.exe")
    exe_dest = "BoxPhoneControl.exe"
    
    if os.path.exists(exe_src):
        if os.path.exists(exe_dest):
            print("[Build] Da co file BoxPhoneControl.exe cu o thu muc goc, dang xoa de thay the...")
            try:
                os.remove(exe_dest)
            except Exception as e:
                print(f"[Build] Loi khi xoa file cu: {e}. Vui long kiem tra xem co dang chay chuong trinh khong.")
                sys.exit(1)
        shutil.move(exe_src, exe_dest)
        print(f"[Build] Success! Da di chuyen file den: {os.path.abspath(exe_dest)}")
    else:
        print("[Build] Xay ra loi! Khong tim thay file exe dau ra trong thu muc dist.")
        sys.exit(1)
        
    # 3. Don dep thu muc tam
    print("[Build] Dang don dep cac thu muc build va file spec...")
    for path in ["build", "dist", "BoxPhoneControl.spec"]:
        if os.path.exists(path):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except Exception as e:
                print(f"[Build] Canh bao: Khong the xoa {path}. Loi: {e}")
                
    print("[Build] Hoan tat toan bo qua trinh build!")

if __name__ == "__main__":
    build()
