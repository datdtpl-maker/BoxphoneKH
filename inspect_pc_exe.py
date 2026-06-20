import re

def search_strings_in_file(filepath, keywords):
    print(f"\nSearching in {filepath}...")
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        
        # Find printable strings (ASCII and UTF-16)
        ascii_strings = re.findall(b'[\x20-\x7E]{4,}', data)
        utf16_matches = re.findall(b'(?:[\x20-\x7E]\x00){4,}', data)
        
        all_strings = []
        for s in ascii_strings:
            try:
                all_strings.append(s.decode('ascii'))
            except Exception:
                pass
        for s in utf16_matches:
            try:
                all_strings.append(s.decode('utf-16le'))
            except Exception:
                pass
        
        matched_count = 0
        for s in set(all_strings):
            if any(kw.lower() in s.lower() for kw in keywords):
                print(f"  Found: {s}")
                matched_count += 1
                if matched_count > 50:
                    print("  ... too many matches, truncating ...")
                    break
    except Exception as e:
        print(f"Error: {e}")

search_strings_in_file(r"C:\Program Files (x86)\xiaowei\xiaowei.exe", ["xwkeyboard", "xwime", "broadcast", "input", "am broadcast"])
search_strings_in_file(r"C:\Program Files (x86)\xiaowei\bridge.exe", ["xwkeyboard", "xwime", "broadcast", "input", "am broadcast"])
