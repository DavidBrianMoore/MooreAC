"""
Garvee Mini Split Controller - Cloud/Local
"""

import json
import time
import logging
import threading
import os
from flask import Flask, jsonify, request, send_from_directory, abort

from cloud_api import AuxCloudAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static')

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"email": "", "password": "", "region": "usa"}

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f)
    except (OSError, PermissionError) as e:
        logger.warning(f"Could not save config to {CONFIG_FILE} (likely read-only filesystem): {e}")

# ── Shared state ───────────────────────────────────────────────────────────────
state_lock = threading.Lock()
ac = {
    'power':       False,
    'mode':        'cool',
    'temperature': 72,     # °F
    'fan':         'auto',
    'connected':   False,
    'device_type': None,
    'error':       None,
    'needs_login': False,
    'target_temp_c': 22,
    'control_mode': 'cloud', # 'cloud' or 'local'
    'mac':          '',
    'ip':           '',
    'device_info':  {},
    'swing_v':      0,
    'swing_h':      0,
    'light':        True,
    'eco':          False,
    'sleep':        False,
    'health':       False,
    'clean':        False,
}

cloud_api = AuxCloudAPI()
cloud_device = None
local_device = None

# ── Protocol maps ──────────────────────────────────────────────────────────────
MODES     = {'auto': 0, 'cool': 1, 'dry': 2, 'heat': 3, 'fan': 4}
MODES_INV = {v: k for k, v in MODES.items()}
FANS      = {'auto': 0, 'low': 1, 'medium': 2, 'high': 3, 'turbo': 4, 'mute': 5}
FANS_INV  = {v: k for k, v in FANS.items()}

# ── Unit helpers ───────────────────────────────────────────────────────────────
def f_to_c(f): return max(16, min(32, round((f - 32) * 5 / 9)))
def c_to_f(c): return round(c * 9 / 5 + 32)

# ── Local Protocol Helpers ─────────────────────────────────────────────────────
def _status_packet():
    p = bytearray(16)
    p[0]=0xBB; p[1]=0x00; p[2]=0x06; p[3]=0x80
    return bytes(p)

def _control_packet(power, mode, temp_f, fan):
    p = bytearray(16)
    p[0]=0xBB; p[1]=0x00; p[2]=0x01; p[3]=0x03
    p[4]  = MODES.get(mode, 1)
    p[5]  = f_to_c(temp_f)
    p[6]  = FANS.get(fan, 0)
    p[12] = 0x01 if power else 0x00
    return bytes(p)

def _parse_response(data: bytes):
    if not data or len(data) < 13: return None
    return {
        'power': bool(data[12] & 0x01),
        'mode':  MODES_INV.get(data[4] & 0x07, 'cool'),
        'temperature': c_to_f(data[5]),
        'fan':   FANS_INV.get(data[6] & 0x07, 'auto'),
    }

# ── Connection Logic ──────────────────────────────────────────────────────────
def connect_device():
    return connect_device_with_data(load_config())

def connect_device_with_data(config):
    mode = config.get("control_mode", "cloud")
    
    with state_lock:
        ac['control_mode'] = mode
        ac['mac'] = config.get("mac", "")
        ac['ip'] = config.get("ip", "")

    if mode == "local":
        return connect_local(config.get("ip"))
    else:
        return connect_cloud_with_data(config)

def connect_local(ip):
    global local_device
    if not ip:
        _set_error("IP address required for local mode")
        return False
    try:
        import broadlink
        dev = broadlink.hello(ip)
        dev.auth()
        local_device = dev
        with state_lock:
            ac['connected'] = True
            ac['error'] = None
        return True
    except Exception as e:
        _set_error(f"Local connect failed: {e}")
        return False

def connect_cloud_with_data(config):
    global cloud_device
    if not config.get("email") or not config.get("password"):
        with state_lock:
            ac['needs_login'] = True
        _set_error("Cloud credentials not configured")
        return False
    
    with state_lock:
        ac['needs_login'] = False
        
    try:
        cloud_api.url = getattr(cloud_api, 'API_URLS', {}).get(config.get("region", "usa"), "https://app-service-usa-fd7cc04c.smarthomecs.com")
        cloud_api.login(config["email"], config["password"])
        families = cloud_api.get_families()
        if not families:
            _set_error("No families found on account")
            return False
            
        devices = cloud_api.get_devices(families[0]["familyid"])
        if not devices:
            _set_error("No devices found on account")
            return False
            
        # Filter by MAC if provided
        target_mac = config.get("mac", "").replace(":", "").lower()
        if target_mac:
            for d in devices:
                if d.get("mac", "").lower() == target_mac:
                    cloud_device = d
                    break
            if not cloud_device:
                _set_error(f"Device with MAC {config['mac']} not found in account")
                return False
        else:
            cloud_device = devices[0]

        logger.info(f"Connected to Cloud API. Device Info: {json.dumps(cloud_device, indent=2)}")
        with state_lock:
            ac['connected'] = True
            ac['error'] = None
            ac['device_info'] = {
                'name': cloud_device.get('name'),
                'mac': cloud_device.get('mac'),
                'endpointId': cloud_device.get('endpointId')
            }
        logger.info(f"Connected to Cloud API. Device: {cloud_device.get('name', 'Unknown')}")
        return True
    except Exception as e:
        logger.error(f"Cloud connection failed: {e}")
        _set_error(str(e))
        return False

def _set_error(msg):
    global cloud_device
    cloud_device = None
    with state_lock:
        ac['connected'] = False
        ac['error']     = msg
    logger.error(f'Device error: {msg}')

def refresh_status():
    """Pull current state from device via cloud or local."""
    global cloud_device, local_device
    
    with state_lock:
        mode = ac['control_mode']

    if mode == "local":
        if not local_device: return False
        try:
            resp = local_device.send_packet(0x6a, _status_packet())
            parsed = _parse_response(resp)
            if parsed:
                with state_lock:
                    ac['power'] = parsed['power']
                    ac['mode'] = parsed['mode']
                    ac['temperature'] = parsed['temperature']
                    ac['fan'] = parsed['fan']
                return True
        except Exception as e:
            _set_error(f"Local refresh failed: {e}")
        return False
    else:
        if not cloud_device: return False
        try:
            params = cloud_api.get_device_params(cloud_device)
            if params:
                with state_lock:
                    ac['power'] = params.get('pwr', 0) == 1
                    ac['mode'] = MODES_INV.get(params.get('ac_mode', 1), 'cool')
                    temp_c = params.get('temp', 220) / 10.0
                    ac['target_temp_c'] = temp_c
                    ac['temperature'] = c_to_f(temp_c)
                    ac['fan'] = FANS_INV.get(params.get('ac_mark', params.get('fan', 0)), 'auto')
                    
                    # Advanced features
                    ac['light'] = params.get('scrdisp', 1) == 1
                    ac['eco'] = params.get('ecomode', 0) == 1
                    ac['sleep'] = params.get('ac_slp', 0) == 1
                    ac['swing_v'] = params.get('ac_vdir', 0)
                    ac['swing_h'] = params.get('ac_hdir', 0)
                    ac['health'] = params.get('ac_health', 0) == 1
                    ac['clean'] = params.get('ac_clean', 0) == 1
                return True
        except Exception as e:
            logger.error(f"Cloud refresh failed: {e}")
    return False

def apply_state():
    """Push current ac state to device via cloud or local."""
    global cloud_device, local_device
    with state_lock:
        mode = ac['control_mode']

    if mode == "local":
        if not local_device: return False
        try:
            with state_lock:
                pkt = _control_packet(ac['power'], ac['mode'], ac['temperature'], ac['fan'])
            return local_device.send_packet(0x6a, pkt) is not None
        except Exception:
            return False
    else:
        if not cloud_device: return False
        try:
            with state_lock:
                temp_c = f_to_c(ac['temperature'])
                values = {
                    'pwr': 1 if ac['power'] else 0,
                    'ac_mode': MODES.get(ac['mode'], 1),
                    'temp': int(temp_c * 10),
                    'fan': FANS.get(ac['fan'], 0),
                    'ac_mark': FANS.get(ac['fan'], 0),
                    'scrdisp': 1 if ac['light'] else 0,
                    'ecomode': 1 if ac['eco'] else 0,
                    'ac_slp': 1 if ac['sleep'] else 0,
                    'ac_vdir': int(ac['swing_v']),
                    'ac_hdir': int(ac['swing_h']),
                    'ac_health': 1 if ac['health'] else 0,
                    'ac_clean': 1 if ac['clean'] else 0,
                }
            cloud_api.set_device_params(cloud_device, values)
            return True
        except Exception:
            return False

# ── Background polling ─────────────────────────────────────────────────────────
def _poll_loop():
    while True:
        time.sleep(15)
        if ac['connected']:
            refresh_status()
        else:
            connect_device()

threading.Thread(target=_poll_loop, daemon=True).start()

# ── REST API ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/status')
def api_status():
    with state_lock:
        if not ac['connected']:
            ac['needs_login'] = True
        return jsonify(dict(ac))

@app.route('/api/cloud/login', methods=['POST'])
def api_cloud_login():
    data = request.get_json(force=True) or {}
    email = data.get('email')
    password = data.get('password')
    region = data.get('region', 'usa')
    mac = data.get('mac', '')
    ip = data.get('ip', '')
    mode = data.get('control_mode', 'cloud')
    remember = data.get('remember', False)
    
    config = load_config()
    if email and password:
        config['email'] = email
        config['password'] = password
        config['region'] = region
    config['mac'] = mac
    config['ip'] = ip
    config['control_mode'] = mode
    
    if remember:
        save_config(config)
    else:
        # Clear sensitive data from disk but keep in memory for this session
        # Actually, connect_device() reads from load_config(), so we should
        # update the global config variable if we had one, but we don't.
        # Let's just pass the data to connect_device.
        pass
        
    ok = connect_device_with_data(config)
    if ok:
        refresh_status()
    with state_lock:
        return jsonify({'ok': ok, 'state': dict(ac)})

@app.route('/api/control', methods=['POST'])
def api_control():
    data = request.get_json(force=True) or {}
    with state_lock:
        if 'power'       in data: ac['power']       = bool(data['power'])
        if 'mode'        in data and data['mode'] in MODES:
            ac['mode']    = data['mode']
        if 'temperature' in data:
            ac['temperature'] = max(16, min(86, int(data['temperature'])))
        if 'fan'         in data and data['fan'] in FANS:
            ac['fan']     = data['fan']
        if 'light' in data: ac['light'] = bool(data['light'])
        if 'eco' in data: ac['eco'] = bool(data['eco'])
        if 'sleep' in data: ac['sleep'] = bool(data['sleep'])
        if 'swing_v' in data: ac['swing_v'] = int(data['swing_v'])
        if 'swing_h' in data: ac['swing_h'] = int(data['swing_h'])
        if 'health' in data: ac['health'] = bool(data['health'])
        if 'clean' in data: ac['clean'] = bool(data['clean'])
    ok = apply_state()
    with state_lock:
        return jsonify({'ok': ok, 'state': dict(ac)})

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    connect_device()
    if ac['connected']:
        refresh_status()
    print('\n  AC Freedom Cloud Controller running at  http://localhost:5000\n')
    app.run(host='0.0.0.0', port=5000, debug=False)
