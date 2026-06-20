import os
import re

search_dir = r"C:\Program Files (x86)\xiaowei"
serials = [
    "520019e3ee625411", "52002267e20354ad", "520029f7fe8084f9", 
    "520036e8f4fab4b9", "52005059ec25b43f", "52005059ec7ab445", 
    "52005948ec445465", "52006044b205b407", "520064f249bba44d", 
    "520072175aa894a7", "520081424fcb15ad", "52009f0df4f81551", 
    "5200b7abe2bd1557", "5200d2cbb43e54f3", "5200ebc9fe6664c9", 
    "ce04160460485f2d05", "ce0516051dd00c3e01", "ce10160a5d76513305", 
    "ce11160bdcf0ce1804", "ce12160c1172c81704"
]

print("Scanning directory for files containing device serials...")
for root, dirs, files in os.walk(search_dir):
    for file in files:
        filepath = os.path.join(root, file)
        # Skip very large or binary files except .db
        ext = os.path.splitext(file)[1].lower()
        if ext in ['.dll', '.exe', '.zip', '.apk', '.dat'] and ext != '.db':
            continue
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            for serial in serials:
                if serial.encode('utf-8') in content:
                    print(f"Match found in: {filepath} for serial {serial}")
                    break
        except Exception as e:
            pass

print("Scan complete.")
