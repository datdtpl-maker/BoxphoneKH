import os
import re

search_dirs = [
    r"C:\Users\datdt\AppData\Local\xiaowei\EBWebView\Default\Local Storage\leveldb",
    r"C:\Users\datdt\AppData\Local\xiaowei\EBWebView\Default\IndexedDB\https_tauri.localhost_0.indexeddb.leveldb",
    r"C:\Users\datdt\AppData\Local\com.xiaowei.android\EBWebView\Default\IndexedDB\https_tauri.localhost_0.indexeddb.leveldb"
]

serials = [
    "520019e3ee625411", "52002267e20354ad", "520029f7fe8084f9", 
    "520036e8f4fab4b9", "52005059ec25b43f", "52005059ec7ab445", 
    "52005948ec445465", "52006044b205b407", "520064f249bba44d", 
    "520072175aa894a7", "520081424fcb15ad", "52009f0df4f81551", 
    "5200b7abe2bd1557", "5200d2cbb43e54f3", "5200ebc9fe6664c9", 
    "ce04160460485f2d05", "ce0516051dd00c3e01", "ce10160a5d76513305", 
    "ce11160bdcf0ce1804", "ce12160c1172c81704"
]

mapping = {}

for sdir in search_dirs:
    if not os.path.exists(sdir):
        continue
    for root, _, files in os.walk(sdir):
        for file in files:
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                
                for serial in serials:
                    serial_bytes = serial.encode('utf-8')
                    idx = 0
                    while True:
                        idx = data.find(serial_bytes, idx)
                        if idx == -1:
                            break
                        
                        # Scan forward 300 bytes from idx
                        chunk = data[idx:idx+350]
                        # Look for "name" and extract string
                        # The pattern might be "name" followed by length and string, or JSON-like
                        # Let's try finding the word "name" in chunk
                        name_idx = chunk.find(b'name')
                        if name_idx != -1:
                            # Extract characters after 'name'
                            # e.g., "name"\x03S16 or similar. Let's find printable ascii string
                            subchunk = chunk[name_idx + 4 : name_idx + 30]
                            # Let's clean subchunk and find the first printable string
                            m = re.search(b'[a-zA-Z0-9_\\-\\+]+', subchunk)
                            if m:
                                name_val = m.group(0).decode('utf-8')
                                if name_val not in ['name', 'onlySerial', 'serial', 'sort']:
                                    if serial not in mapping:
                                        mapping[serial] = name_val
                        
                        idx += len(serial_bytes)
            except Exception:
                pass

print("Extracted mappings:")
for serial, name in sorted(mapping.items(), key=lambda x: x[1]):
    print(f"Serial: {serial} -> Name in GUI: {name}")
