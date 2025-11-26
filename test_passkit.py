import time
import json
import hmac
import hashlib
import base64
import requests


def base64url_encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_passkit_jwt():
    api_key = '0xc5s5akwxmyPMEzhHzTbv'
    api_secret = 'bmbhnLSfaV2yeZF1V8byrVFbY+rB5+L8fyxmrcjx'

    # 1) Header
    header = {
        "typ": "JWT",
        "alg": "HS256"
    }
    encoded_header = base64url_encode(json.dumps(header).encode())

    # 2) Payload
    now = int(time.time())
    payload = {
        "uid": api_key,
        "iat": now - 5,
        "exp": now + 3600
    }
    encoded_payload = base64url_encode(json.dumps(payload).encode())

    # 3) Unsigned token
    token_unsigned = f"{encoded_header}.{encoded_payload}"

    # 4) Signature (HMAC SHA256)
    signature = hmac.new(
        api_secret.encode(),
        token_unsigned.encode(),
        hashlib.sha256
    ).digest()
    encoded_signature = base64url_encode(signature)

    # 5) Final token
    jwt = f"{token_unsigned}.{encoded_signature}"
    return jwt


url = "https://api.pub2.passkit.io/members/member/list/2iFGNn4w5c4CJgdciL7BAm"

payload = json.dumps({
  "filters": {
    "limit": 0,
    "offset": 0,
    "filterGroups": [
      {
        "condition": "AND",
        "fieldFilters": [
          {
            "filterField": "mobileNumber",
            "filterValue": "95212421",
            "filterOperator": "eq"
          }
        ]
      }
    ],
    "orderAsc": True
  },
  "emailAsCsv": False
})
headers = {
  'Authorization': generate_passkit_jwt(),
  'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)

# If PassKit returned a valid JSON
try:
    body = response.json()
except:
    body = None

# -------------------------
# 4️⃣ If found member → return it
# -------------------------
if response.status_code == 200 and body and len(body) > 0:
    print(body[0])

# -------------------------
# 5️⃣ If 200 but EMPTY → Enroll new member
# -------------------------
if response.status_code == 200 and not body:
    print('hooson')
