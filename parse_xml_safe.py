import xml.etree.ElementTree as ET
import re

xml_path = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\window_dump.xml"
output_path = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\parse_results.txt"

print(f"Parsing {xml_path}...")
try:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    results = []
    for elem in root.iter():
        text = elem.get('text', '')
        # Search case-insensitive and unaccented
        if 'Lâm Đồng' in text or 'Lam Dong' in text or 'L\u00e2m \u0110\u1ed3ng' in text:
            bounds = elem.get('bounds', '')
            resource_id = elem.get('resource-id', '')
            class_name = elem.get('class', '')
            results.append((class_name, text, bounds, resource_id))
            
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"Found {len(results)} nodes:\n")
        for idx, (cls, text, bounds, res_id) in enumerate(results):
            f.write(f"[{idx+1}] Class={cls} | Text='{text}' | Bounds={bounds} | ResourceID={res_id}\n")
            
    print(f"Found {len(results)} nodes. Saved results to {output_path}.")
    # Safe terminal print (remove accents)
    for idx, (cls, text, bounds, res_id) in enumerate(results):
        safe_text = text.encode('ascii', errors='ignore').decode('ascii')
        print(f"[{idx+1}] Class={cls} | Text='{safe_text}' | Bounds={bounds} | ResourceID={res_id}")
        
except Exception as e:
    print(f"Error: {e}")
