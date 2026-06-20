import subprocess
from adb_controller import ADBController

adb = ADBController()
devices = adb.get_devices()

print("Listing properties for all devices:")
for idx, dev in enumerate(devices):
    _, model, _ = adb.execute_adb(dev, ["shell", "getprop", "ro.product.model"])
    _, name, _ = adb.execute_adb(dev, ["shell", "getprop", "ro.product.name"])
    _, hostname, _ = adb.execute_adb(dev, ["shell", "getprop", "net.hostname"])
    _, device, _ = adb.execute_adb(dev, ["shell", "getprop", "ro.product.device"])
    
    # Check if there is a nickname or custom label set
    _, nickname, _ = adb.execute_adb(dev, ["shell", "settings", "get", "global", "device_name"])
    
    print(f"Index {idx+1}: Serial={dev} | Model={model} | Name={name} | Device={device} | DeviceName={nickname} | Hostname={hostname}")
