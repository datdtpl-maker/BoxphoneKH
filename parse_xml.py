import xml.etree.ElementTree as ET

xml_path = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\window_dump.xml"

print(f"Parsing {xml_path}...")
try:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    # Recursively find nodes containing text
    found = False
    for elem in root.iter():
        text = elem.get('text', '')
        if 'Lâm Đồng' in text or 'Lâm' in text or 'Đồng' in text:
            bounds = elem.get('bounds', '')
            resource_id = elem.get('resource-id', '')
            class_name = elem.get('class', '')
            print(f"Node found: Class={class_name} | Text='{text}' | Bounds={bounds} | ResourceID={resource_id}")
            found = True
            
    if not found:
        print("No matching nodes containing 'Lâm Đồng' found.")
except Exception as e:
    print(f"Error parsing XML: {e}")
