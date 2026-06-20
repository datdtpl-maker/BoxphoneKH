import xml.etree.ElementTree as ET

xml_path = r"C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot\window_dump.xml"

try:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    print("Listing all non-empty text attributes in XML:")
    count = 0
    for elem in root.iter():
        text = elem.get('text', '')
        if text.strip():
            safe_text = text.encode('ascii', errors='ignore').decode('ascii')
            print(f" - Text: '{safe_text}' | Class: {elem.get('class', '')} | Bounds: {elem.get('bounds', '')}")
            count += 1
            if count >= 30:
                print("... truncated ...")
                break
except Exception as e:
    print(f"Error: {e}")
