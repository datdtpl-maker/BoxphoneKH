import xml.etree.ElementTree as ET
import os

xml_path = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\shopee_dump.xml"
out_path = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\shopee_results.txt"

print("Parsing XML in Python...")
try:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    results = []
    for elem in root.iter():
        text = elem.get('text', '')
        # Check for 'Lâm Đồng' in various forms
        if 'Lâm Đồng' in text or 'Tỉnh Lâm Đồng' in text:
            bounds = elem.get('bounds', '')
            class_name = elem.get('class', '')
            results.append((class_name, text, bounds))
            
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"Found {len(results)} nodes matching Lâm Đồng:\n")
        for idx, (cls, txt, bounds) in enumerate(results):
            f.write(f"[{idx+1}] Class={cls} | Text='{txt}' | Bounds={bounds}\n")
            
    print(f"Found {len(results)} nodes. Written to {out_path}.")
except Exception as e:
    print(f"Error: {e}")
