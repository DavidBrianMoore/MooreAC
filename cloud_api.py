import base64
import hashlib
import json
import time
import requests
from Crypto.Cipher import AES

# Keys & Constants
TIMESTAMP_TOKEN_ENCRYPT_KEY = "kdixkdqp54545^#*"
PASSWORD_ENCRYPT_KEY = "4969fj#k23#"
BODY_ENCRYPT_KEY = "xgx3d*fe3478$ukx"

AES_INITIAL_VECTOR = bytes([(b + 256) % 256 for b in [-22, -86, -86, 58, -69, 88, 98, -94, 25, 24, -75, 119, 29, 22, 21, -86]])

LICENSE = "PAFbJJ3WbvDxH5vvWezXN5BujETtH/iuTtIIW5CE/SeHN7oNKqnEajgljTcL0fBQQWM0XAAAAAAnBhJyhMi7zIQMsUcwR/PEwGA3uB5HLOnr+xRrci+FwHMkUtK7v4yo0ZHa+jPvb6djelPP893k7SagmffZmOkLSOsbNs8CAqsu8HuIDs2mDQAAAAA="
LICENSE_ID = "3c015b249dd66ef0f11f9bef59ecd737"
COMPANY_ID = "48eb1b36cf0202ab2ef07b880ecda60d"

SPOOF_APP_VERSION = "2.2.10.456537160"
SPOOF_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 12; SM-G991B Build/SP1A.210812.016)"
SPOOF_SYSTEM = "android"
SPOOF_APP_PLATFORM = "android"

API_URLS = {
    "eu": "https://app-service-deu-f0e9ebbb.smarthomecs.de",
    "usa": "https://app-service-usa-fd7cc04c.smarthomecs.com",
    "cn": "https://app-service-chn-31a93883.ibroadlink.com",
    "rus": "https://app-service-rus-b8bbc3be.smarthomecs.com",
}

def encrypt_aes_cbc_zero_padding(iv: bytes, key: bytes, data: bytes):
    try:
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_data = data + b"\x00" * (AES.block_size - len(data) % AES.block_size)
        return cipher.encrypt(padded_data)
    except Exception as e:
        print(e)
        return None

class AuxCloudAPI:
    def __init__(self, region="usa"):
        self.url = API_URLS.get(region, API_URLS["usa"])
        self.email = None
        self.password = None
        self.loginsession = None
        self.userid = None
        self.devices = []

    def _get_headers(self, **kwargs):
        return {
            "Content-Type": "application/x-java-serialized-object",
            "licenseId": LICENSE_ID,
            "lid": LICENSE_ID,
            "language": "en",
            "appVersion": SPOOF_APP_VERSION,
            "User-Agent": SPOOF_USER_AGENT,
            "system": SPOOF_SYSTEM,
            "appPlatform": SPOOF_APP_PLATFORM,
            "loginsession": self.loginsession or "",
            "userid": self.userid or "",
            **kwargs,
        }

    def _make_request(self, method, endpoint, headers=None, data=None, data_raw=None, params=None):
        url = f"{self.url}/{endpoint}"
        payload = data_raw if data_raw else (json.dumps(data, separators=(",", ":")) if data else None)
        response = requests.request(method, url, headers=headers, data=payload, params=params)
        response.raise_for_status()
        return response.json()

    def login(self, email, password):
        self.email = email
        self.password = password
        
        current_time = time.time()
        sha_password = hashlib.sha1(f"{password}{PASSWORD_ENCRYPT_KEY}".encode()).hexdigest()
        
        payload = {
            "email": email,
            "password": sha_password,
            "companyid": COMPANY_ID,
            "lid": LICENSE_ID,
        }
        json_payload = json.dumps(payload, separators=(",", ":"))
        token = hashlib.md5(f"{json_payload}{BODY_ENCRYPT_KEY}".encode()).hexdigest()
        md5 = hashlib.md5(f"{current_time}{TIMESTAMP_TOKEN_ENCRYPT_KEY}".encode()).digest()
        
        json_data = self._make_request(
            method="POST",
            endpoint="account/login",
            headers=self._get_headers(timestamp=f"{current_time}", token=token),
            data_raw=encrypt_aes_cbc_zero_padding(AES_INITIAL_VECTOR, md5, json_payload.encode())
        )
        
        if json_data.get("status") == 0:
            self.loginsession = json_data["loginsession"]
            self.userid = json_data["userid"]
            return True
        raise Exception(f"Failed to login: {json_data}")

    def get_families(self):
        json_data = self._make_request(
            method="POST",
            endpoint="appsync/group/member/getfamilylist",
            headers=self._get_headers()
        )
        if json_data.get("status") == 0:
            return json_data["data"]["familyList"]
        raise Exception(f"Failed to get families list: {json_data}")

    def get_devices(self, familyid):
        json_data = self._make_request(
            method="POST",
            endpoint="appsync/group/dev/query?action=select",
            data_raw='{"pids":[]}',
            headers=self._get_headers(familyid=familyid)
        )
        if json_data.get("status") == 0:
            devices = json_data.get("data", {}).get("endpoints", [])
            for dev in devices:
                try:
                    dev["params"] = self.get_device_params(dev)
                except Exception as e:
                    print(f"Error fetching params for {dev.get('endpointId')}: {e}")
                    dev["params"] = {}
            self.devices = devices
            return devices
        raise Exception(f"Failed to query devices: {json_data}")

    def _get_directive_header(self, namespace, name, message_id_prefix, **kwargs):
        return {
            "namespace": namespace,
            "name": name,
            "interfaceVersion": "2",
            "senderId": "sdk",
            "messageId": f"{message_id_prefix}-{int(time.time())}",
            **kwargs,
        }

    def _act_device_params(self, device, act, params=None, vals=None):
        params = params or []
        vals = vals or []
        
        cookie = json.loads(base64.b64decode(device["cookie"].encode()))
        mapped_cookie = base64.b64encode(
            json.dumps({
                "device": {
                    "id": cookie["terminalid"],
                    "key": cookie["aeskey"],
                    "devSession": device["devSession"],
                    "aeskey": cookie["aeskey"],
                    "did": device["endpointId"],
                    "pid": device["productId"],
                    "mac": device["mac"],
                }
            }, separators=(",", ":")).encode()
        ).decode()
        
        header = self._get_directive_header(
            namespace="DNA.KeyValueControl",
            name="KeyValueControl",
            message_id_prefix=device["endpointId"],
            timstamp=f"{int(time.time())}"
        )
        
        data = {
            "directive": {
                "header": header,
                "endpoint": {
                    "devicePairedInfo": {
                        "did": device["endpointId"],
                        "pid": device["productId"],
                        "mac": device["mac"],
                        "devicetypeflag": device.get("devicetypeFlag", 1),
                        "cookie": mapped_cookie,
                    },
                    "endpointId": device["endpointId"],
                    "cookie": {},
                    "devSession": device["devSession"],
                },
                "payload": {"act": act, "params": params, "vals": vals, "did": device["endpointId"]},
            }
        }
        
        if len(params) == 1 and act == "get":
            data["directive"]["payload"]["vals"] = [[{"val": 0, "idx": 1}]]
            
        json_data = self._make_request(
            method="POST",
            endpoint="device/control/v2/sdkcontrol",
            data=data,
            params={"license": LICENSE},
            headers=self._get_headers()
        )
        
        try:
            response = json.loads(json_data["event"]["payload"]["data"])
            response_dict = {}
            for i in range(len(response["params"])):
                response_dict[response["params"][i]] = response["vals"][i][0]["val"]
            return response_dict
        except Exception as e:
            raise Exception(f"Failed to parse device params: {json_data}") from e

    def get_device_params(self, device, params=None):
        return self._act_device_params(device, "get", params)

    def set_device_params(self, device, values):
        params = list(values.keys())
        vals = [[{"idx": 1, "val": x}] for x in values.values()]
        return self._act_device_params(device, "set", params, vals)
