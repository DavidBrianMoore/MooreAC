"""
Direct BroadLink UDP probe - sends the hello packet directly to 192.168.1.74:80
and listens for the device's response, bypassing broadlink.discover().
"""
import socket, struct, time, random

DEVICE_IP   = '192.168.1.74'
DEVICE_PORT = 80
LOCAL_PORT  = random.randint(10000, 60000)

def build_hello_packet(local_ip):
    """Build the BroadLink discovery hello packet."""
    packet = bytearray(0x30)
    t = time.localtime()
    packet[0x08] = t.tm_min
    packet[0x09] = t.tm_hour
    packet[0x0a] = t.tm_year & 0xff
    packet[0x0b] = t.tm_year >> 8
    packet[0x0c] = t.tm_wday
    packet[0x0d] = t.tm_mday
    packet[0x0e] = t.tm_mon
    packet[0x0f] = t.tm_sec
    # Local IP (little-endian)
    for i, part in enumerate(local_ip.split('.')):
        packet[0x18 + i] = int(part)
    # Local port
    packet[0x1c] = LOCAL_PORT & 0xff
    packet[0x1d] = LOCAL_PORT >> 8
    packet[0x26] = 6  # Command: discover
    # Checksum
    cs = sum(packet) & 0xffff
    packet[0x20] = cs & 0xff
    packet[0x21] = cs >> 8
    return bytes(packet)

local_ip = '192.168.1.220'  # Your PC's IP
pkt = build_hello_packet(local_ip)

print(f'Sending hello to {DEVICE_IP}:{DEVICE_PORT} from local port {LOCAL_PORT}')
print(f'Packet: {pkt.hex()}')

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.settimeout(5)

try:
    sock.bind(('', LOCAL_PORT))
    sock.sendto(pkt, (DEVICE_IP, DEVICE_PORT))
    print('Packet sent. Waiting for response...')
    
    try:
        data, addr = sock.recvfrom(1024)
        print(f'\nGot response from {addr}!')
        print(f'Raw hex: {data.hex()}')
        if len(data) >= 0x40:
            devtype = data[0x34] | (data[0x35] << 8)
            mac = ':'.join(f'{b:02X}' for b in reversed(data[0x3a:0x40]))
            print(f'Device type: {hex(devtype)}')
            print(f'MAC: {mac}')
    except socket.timeout:
        print('\nNo response (timeout). Possible causes:')
        print('  - Windows Firewall blocked the response (run discover_firewall.bat as Admin)')
        print('  - The device uses a different protocol port')
        print('  - The device is not in normal operation mode')
finally:
    sock.close()
