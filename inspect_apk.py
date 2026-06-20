import zipfile
import re

apk_path = r"C:\Program Files (x86)\xiaowei\tools\XWKeyboard.apk"

def extract_strings(data):
    # Try finding UTF-8 strings
    utf8 = re.findall(b'[\x20-\x7E]{4,}', data)
    # Try finding UTF-16 strings (characters followed by nulls or just wide strings)
    utf16_matches = re.findall(b'(?:[\x20-\x7E]\x00){4,}', data)
    utf16 = []
    for m in utf16_matches:
        try:
            utf16.append(m.decode('utf-16le').encode('utf-8'))
        except Exception:
            pass
    return [s.decode('utf-8', errors='ignore') for s in (utf8 + utf16)]

print(f"Opening {apk_path}...")
with zipfile.ZipFile(apk_path, 'r') as zip_ref:
    # AndroidManifest.xml
    manifest_data = zip_ref.read("AndroidManifest.xml")
    strings = extract_strings(manifest_data)
    print("\nStrings found in AndroidManifest.xml:")
    for s in sorted(set(strings)):
        if any(kw in s.lower() for kw in ['input', 'key', 'text', 'bcast', 'broadcast', 'action', 'receiver', 'service', 'ime']):
            print(f"  {s}")

    # Let's search inside classes.dex for broadcasts or commands
    print("\nSearching dex files...")
    for filename in zip_ref.namelist():
        if filename.endswith(".dex"):
            dex_data = zip_ref.read(filename)
            dex_strings = extract_strings(dex_data)
            matching = [s for s in dex_strings if "action" in s.lower() or "input" in s.lower() or "keyboard" in s.lower()]
            if matching:
                print(f"  Found in {filename} ({len(matching)} matches):")
                # print top 10 matches
                for s in sorted(set(matching))[:10]:
                    print(f"    {s}")
