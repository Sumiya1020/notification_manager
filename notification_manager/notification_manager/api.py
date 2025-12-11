import time
import json
import hmac
import hashlib
import base64
import requests
import frappe


PASSKIT_PROGRAM_ID = "2iFGNn4w5c4CJgdciL7BAm"
PASSKIT_TIER_ID = "base"


def base64url_encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_passkit_jwt():
    api_key = frappe.conf.passkit_api_key
    api_secret = frappe.conf.passkit_api_secret

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


def create_passkit_member_doc(member_data):
    doc = frappe.get_doc(member_data)
    
    doc.insert(ignore_permissions=True)   # use ignore_permissions only if needed
    frappe.db.commit()


def enroll_passkit_member_api(customer, jwt_token):
    """
    Enroll a new PassKit member using ERPNext Customer data.
    """

    url = "https://api.pub2.passkit.io/members/member"

    payload = {
        "externalId": customer.name,      # Use ERPNext Customer ID
        "tierId": PASSKIT_TIER_ID,
        "programId": PASSKIT_PROGRAM_ID,

        "person": {
            "displayName": customer.customer_name,
            "forename": customer.customer_name,
            "gender": "NOT_KNOWN",
            "emailAddress": customer.email_id or "",
            "mobileNumber": customer.mobile_no or customer.phone,
            "externalId": customer.name,
        },

        "metaData": {
            "source": "ERPNext",
            "erpnext_customer": customer.name
        },

        "points": customer.custom_loyalty_points,
        "status": "ENROLLED"
    }

    headers = {
        "Authorization": jwt_token,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)

    try:
        body = response.json()
    except:
        body = None

    if response.status_code in [200, 201]:
        create_passkit_member_doc({
            "doctype": "Passkit Member",   # your custom Doctype name
            "passkit_id": body['id'],
            "customer_name": customer.name,
            "passkit_status": "ENROLLED"
        })
        
        return {
            "status": "created",
            "url": f'https://pub2.pskt.io/{body['id']}'
        }

    return {
        "status": "failed_to_create",
        "http_status": response.status_code,
        "body": body,
        "raw": response.text
    }
    

def update_passkit_member_api(customer, jwt_token):
    """
    Update a member using ERPNext Customer data.
    """

    url = "https://api.pub2.passkit.io/members/member"

    payload = {
        "externalId": customer.name,      # Use ERPNext Customer ID
        "tierId": PASSKIT_TIER_ID,
        "programId": PASSKIT_PROGRAM_ID,

        "person": {
            "displayName": customer.customer_name,
            "forename": customer.customer_name,
            "gender": "NOT_KNOWN",
            "emailAddress": customer.email_id or "",
            "mobileNumber": customer.mobile_no or customer.phone,
            "externalId": customer.name,
        },

        "metaData": {
            "source": "ERPNext",
            "erpnext_customer": customer.name
        },

        "points": customer.custom_loyalty_points
    }

    headers = {
        "Authorization": jwt_token,
        "Content-Type": "application/json"
    }

    response = requests.put(url, headers=headers, json=payload)
    
    try:
        body = response.json()
    except:
        body = None
        
    if response.status_code in [200, 201]:
        create_passkit_member_doc({
            "doctype": "Passkit Member",   # your custom Doctype name
            "passkit_id": body['id'],
            "customer_name": customer.name,
            "passkit_status": "ENROLLED"
        })
        
        return {
            "status": "updated"
        }
    else:
        return {
            "status": "failed"
        }
    

def delete_passkit_member_api(customer, jwt_token):
    """
    Enroll a new PassKit member using ERPNext Customer data.
    """

    url = "https://api.pub2.passkit.io/members/member"

    payload = {
        "externalId": customer.name,
        "programId": PASSKIT_PROGRAM_ID,
    }

    headers = {
        "Authorization": jwt_token,
        "Content-Type": "application/json"
    }

    response = requests.delete(url, headers=headers, json=payload)
    
    exists = frappe.db.exists("Passkit Member", {"customer_name": customer.name})
    if exists:
        frappe.delete_doc("Passkit Member", exists)
        frappe.db.commit()

    try:
        body = response.json()
    except:
        body = None

    if response.status_code in [200, 201]:
        return {
            "externalId": customer.name,
            "status": "deleted"
        }

    return {
        "status": "failed_to_delete",
        "http_status": response.status_code,
        "body": body,
        "raw": response.text
    }


@frappe.whitelist()
def get_item_with_qty():
    """
    Fetch items with their actual quantities using a SQL query.
    """
    try:
        # Execute the SQL query
        query = """
            SELECT 
                ti.*, 
                tb.actual_qty 
            FROM 
                `tabItem` ti
            LEFT JOIN 
                `tabBin` tb 
            ON 
                ti.name = tb.item_code
        """
        result = frappe.db.sql(query, as_dict=True)  # Fetch results as a list of dictionaries
        return result
    except Exception as e:
        # Log error and return error message
        frappe.log_error(frappe.get_traceback(), 'API Error: get_item_with_qty')
        return {'error': str(e)}


@frappe.whitelist()
def get_or_create_passkit_member(customer_id):
    """
    1. Looks up customer in ERPNext
    2. Calls PassKit to check if member exists
    3. If body empty → enroll new member
    """

    # -------------------------
    # 1️⃣ Fetch Customer
    # -------------------------
    customer = frappe.get_doc("Customer", customer_id)

    mobile = customer.mobile_no or customer.phone
    if not mobile:
        frappe.throw("Customer has no mobile number")

    # -------------------------
    # 2️⃣ Generate PassKit JWT
    # -------------------------
    jwt_token = generate_passkit_jwt()

    # -------------------------
    # 3️⃣ Query PassKit Member List
    # -------------------------
    url = f"https://api.pub2.passkit.io/members/member/list/{PASSKIT_PROGRAM_ID}"

    payload = {
        "filters": {
            "limit": 0,
            "offset": 0,
            "filterGroups": [
                {
                    "condition": "AND",
                    "fieldFilters": [
                        {
                            "filterField": "mobileNumber",
                            "filterValue": mobile,
                            "filterOperator": "eq"
                        }
                    ]
                }
            ],
            "orderAsc": True
        },
        "emailAsCsv": False
    }

    headers = {
        "Authorization": jwt_token,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)

    # If PassKit returned a valid JSON
    try:
        body = response.json()
    except:
        body = None

    # -------------------------
    # 4️⃣ If found member → return it
    # -------------------------
    if response.status_code == 200 and body and len(body) > 0:
        exists = frappe.db.exists("Passkit Member", {"customer_name": customer.name})
        if not exists:
            create_passkit_member_doc({
                "doctype": "Passkit Member",   # your custom Doctype name
                "passkit_id": body['result']['id'],
                "customer_name": customer.name,
                "passkit_status": "ENROLLED"
            })
        
        return {
            "status": "found",
            "member": f'https://pub2.pskt.io/{body['result']['id']}'
        }

    # -------------------------
    # 5️⃣ If 200 but EMPTY → Enroll new member
    # -------------------------
    if response.status_code == 200 and not body:
        return enroll_passkit_member_api(customer, jwt_token)

    # -------------------------
    # 6️⃣ Other errors
    # -------------------------
    return {
        "status": "error",
        "http_status": response.status_code,
        "body": body,
        "raw": response.text,
    }
    

@frappe.whitelist()
def update_passkit_member(customer_id):
    # -------------------------
    # 1️⃣ Fetch Customer
    # -------------------------
    customer = frappe.get_doc("Customer", customer_id)

    mobile = customer.mobile_no or customer.phone
    if not mobile:
        frappe.throw("Customer has no mobile number")

    # -------------------------
    # 2️⃣ Generate PassKit JWT
    # -------------------------
    jwt_token = generate_passkit_jwt()

    # -------------------------
    # 3️⃣ Query PassKit Member List
    # -------------------------
    url = f"https://api.pub2.passkit.io/members/member/list/{PASSKIT_PROGRAM_ID}"

    payload = {
        "filters": {
            "limit": 0,
            "offset": 0,
            "filterGroups": [
                {
                    "condition": "AND",
                    "fieldFilters": [
                        {
                            "filterField": "mobileNumber",
                            "filterValue": mobile,
                            "filterOperator": "eq"
                        }
                    ]
                }
            ],
            "orderAsc": True
        },
        "emailAsCsv": False
    }

    headers = {
        "Authorization": jwt_token,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)

    # If PassKit returned a valid JSON
    try:
        body = response.json()
    except:
        body = None
        
    
    if response.status_code == 200 and body and len(body) > 0:
        return update_passkit_member_api(customer, jwt_token)
    else:
        return {
            "status": "not_found"
        }
    
    
    

@frappe.whitelist()
def delete_passkit_member(customer_id):
    """
    1. Looks up customer in ERPNext
    2. Calls PassKit to check if member exists
    3. If body empty → enroll new member
    """

    # -------------------------
    # 1️⃣ Fetch Customer
    # -------------------------
    customer = frappe.get_doc("Customer", customer_id)

    mobile = customer.mobile_no or customer.phone
    if not mobile:
        frappe.throw("Customer has no mobile number")

    # -------------------------
    # 2️⃣ Generate PassKit JWT
    # -------------------------
    jwt_token = generate_passkit_jwt()

    # -------------------------
    # 3️⃣ Query PassKit Member List
    # -------------------------
    url = f"https://api.pub2.passkit.io/members/member/list/{PASSKIT_PROGRAM_ID}"

    payload = {
        "filters": {
            "limit": 0,
            "offset": 0,
            "filterGroups": [
                {
                    "condition": "AND",
                    "fieldFilters": [
                        {
                            "filterField": "mobileNumber",
                            "filterValue": mobile,
                            "filterOperator": "eq"
                        }
                    ]
                }
            ],
            "orderAsc": True
        },
        "emailAsCsv": False
    }

    headers = {
        "Authorization": jwt_token,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)

    # If PassKit returned a valid JSON
    try:
        body = response.json()
    except:
        body = None
        
    
    # -------------------------
    # 5️⃣ If 200 but EMPTY → Enroll new member
    # -------------------------
    if response.status_code == 200 and not body:
        exists = frappe.db.exists("Passkit Member", {"customer_name": customer.name})
        if exists:
            frappe.delete_doc("Passkit Member", exists)
        
        return {
            "status": "not_found"
        }

    # -------------------------
    # 4️⃣ If found member → return it
    # -------------------------
    if response.status_code == 200 and body and len(body) > 0:
        return delete_passkit_member_api(customer, jwt_token)

    # -------------------------
    # 6️⃣ Other errors
    # -------------------------
    return {
        "status": "error",
        "http_status": response.status_code,
        "body": body,
        "raw": response.text,
    }
    
    
@frappe.whitelist()
def passkit_webhook(data):
    frappe.log_error('passkit_webhook_data', data)
    
    return {
        "status": "success",
        "message": "OK"
    }
