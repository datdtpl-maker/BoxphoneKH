import time
from adb_controller import ADBController
import xml.etree.ElementTree as ET
import re

adb = ADBController()
# S12 serial ID
dev = "52002267e20354ad"

print("Step 1: Launching Shopee and searching for 'deriva'...")
# Run the search sequence
success, msg = adb.shopee_search_sequence(dev, "deriva")
print(f"Search sequence result: Success={success}, Message={msg}")

if success:
    print("Step 2: Waiting 10 seconds for results to load...")
    time.sleep(10)
    
    print("Step 3: Dumping UI hierarchy...")
    adb.execute_adb(dev, ["shell", "rm", "-f", "/sdcard/shopee_dump.xml"])
    code, stdout, stderr = adb.execute_adb(dev, ["shell", "uiautomator", "dump", "/sdcard/shopee_dump.xml"])
    print(f"Dump code={code}, stdout={stdout}, stderr={stderr}")
    
    local_xml = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\shopee_dump.xml"
    code, stdout, stderr = adb.execute_adb(dev, ["pull", "/sdcard/shopee_dump.xml", local_xml])
    print(f"Pull code={code}, stdout={stdout}, stderr={stderr}")
    
    print("Step 4: Parsing XML to find 'Lâm Đồng'...")
    try:
        tree = ET.parse(local_xml)
        root = tree.getroot()
        
        found = []
        for elem in root.iter():
            text = elem.get('text', '')
            if 'Lâm Đồng' in text or 'L\u00e2m \u0110\u1ed3ng' in text or 'Lâm' in text or 'Đồng' in text:
                found.append((elem.get('class', ''), text, elem.get('bounds', '')))
                
        print(f"Found {len(found)} elements containing target text:")
        for idx, (cls, txt, bounds) in enumerate(found):
            safe_text = txt.encode('ascii', errors='ignore').decode('ascii')
            print(f" [{idx+1}] Class={cls} | Text='{safe_text}' | Bounds={bounds}")
    except Exception as e:
        print(f"Error parsing XML: {e}")
else:
    print("Search failed, skipping dump.")
