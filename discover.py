"""
BroadLink AC direct connect — tries multiple discovery approaches and
known AC device types to bypass the broken discovery/hello.
"""
import socket, struct, time, broadlink
from broadlink.device import Device

DEVICE_IP = '192.168.1.74'
# Paste your full MAC here once you have it, e.g. '348E89AABBCC'
DEVICE_MAC_HEX = '348E89XXXXXX'   # <-- replace XX with real values

# ── Approach 1: broadlink.discover() bound to correct interface ───────────────
print('=== Approach 1: discover() on LAN ===')
try:
    devs = broadlink.discover(timeout=8, discover_ip_address='192.168.1.255')
    print(f'Found {len(devs)} device(s)')
    for d in devs:
        mac = ':'.join(f'{b:02X}' for b in d.mac)
        print(f'  {d.host[0]}  type={hex(d.devtype)}  mac={mac}')
except Exception as e:
    print(f'  Error: {e}')

# ── Approach 2: hello() directly ──────────────────────────────────────────────
print('\n=== Approach 2: hello() direct ===')
try:
    dev = broadlink.hello(DEVICE_IP, timeout=8)
    print(f'  Got: type={hex(dev.devtype)}  mac={":".join(f"{b:02X}" for b in dev.mac)}')
except Exception as e:
    print(f'  Error: {e}')

# ── Approach 3: instantiate known AC types and auth ───────────────────────────
print('\n=== Approach 3: try known AC device types ===')
# Common BroadLink AC WiFi module types
AC_TYPES = [0x4E2A, 0x4EAD, 0x4F9B, 0x2722, 0x4E4D, 0x4EFB, 0x520d]

if 'XX' not in DEVICE_MAC_HEX:
    mac_bytes = bytearray.fromhex(DEVICE_MAC_HEX)
    for devtype in AC_TYPES:
        try:
            dev = broadlink.get_device(
                host=(DEVICE_IP, 80),
                mac=mac_bytes,
                devtype=devtype,
            )
            dev.timeout = 5
            dev.auth()
            print(f'  SUCCESS with type={hex(devtype)}!')
            data = dev.status() if hasattr(dev, 'status') else None
            print(f'  Status: {data}')
            break
        except Exception as e:
            print(f'  type={hex(devtype)}: {e}')
else:
    print('  Skipped — fill in DEVICE_MAC_HEX above with your full MAC')
    print('  (e.g.  DEVICE_MAC_HEX = "348E89AABBCC")')
