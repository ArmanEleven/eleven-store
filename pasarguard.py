import requests

class PasarGuardAPI:
    def __init__(self, base_url, username, password, timeout=15, verify_ssl=None):
        from config import PANEL_VERIFY_SSL
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.verify_ssl = PANEL_VERIFY_SSL if verify_ssl is None else verify_ssl

    def login(self):
        response = requests.post(
            f"{self.base_url}/api/admin/token",
            data={
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
            },
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def test_connection(self):
        auth = self.login()
        token = auth["access_token"]
        response = requests.get(
            f"{self.base_url}/api/admin",
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return {"token": token, "admin": response.json()}

    def get_admins(self, token):
        response = requests.get(
            f"{self.base_url}/api/admins",
            headers={"Authorization": f"Bearer {token}"},
            params={"sort": "-created_at", "limit": 50, "offset": 0},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def create_user(self, token, username, data_limit_bytes=0, expire=0, status="active"):
        payload = {
            "username": username,
            "proxy_settings": {},
            "expire": expire,
            "data_limit": int(data_limit_bytes),
            "data_limit_reset_strategy": "no_reset",
            "status": status,
        }
        response = requests.post(
            f"{self.base_url}/api/user",
            headers=self._headers(token),
            json=payload,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def get_user(self, token, user_id):
        response = requests.get(
            f"{self.base_url}/api/user/by-id/{user_id}",
            headers=self._headers(token), timeout=self.timeout, verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def update_user(self, token, user_id, **changes):
        response = requests.put(
            f"{self.base_url}/api/user/by-id/{user_id}",
            headers=self._headers(token), json=changes,
            timeout=self.timeout, verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def delete_user(self, token, user_id):
        response = requests.delete(
            f"{self.base_url}/api/user/by-id/{user_id}",
            headers=self._headers(token), timeout=self.timeout, verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json() if response.content else {}

# Extended dealer operations

def _pg_create_admin(self, token, username, password, data_limit_bytes, expire, max_users):
    import requests
    payload={"username":username,"password":password,"status":"active","data_limit":int(data_limit_bytes),"discord_webhook":"","sub_domain":"","profile_title":"","support_url":"","sub_template":"","note":"","custom_variables":[],"notification_enable":{"create":True,"modify":True,"delete":True,"status_change":True,"reset_data_usage":True,"data_reset_by_next":True,"subscription_revoked":True},"permission_overrides":{"max_users":None if max_users==0 else int(max_users),"data_limit_min":None,"data_limit_max":None,"expire_min":None,"expire_max":None,"min_hwid_per_user":None,"max_hwid_per_user":None,"on_hold_timeout_min":None,"on_hold_timeout_max":None},"role_id":3}
    r=requests.post(f"{self.base_url}/api/admin",headers=self._headers(token),json=payload,timeout=self.timeout,verify=self.verify_ssl)
    if not r.ok:
        detail = r.text[:2000]
        try:
            detail = str(r.json())[:2000]
        except Exception:
            pass
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {detail}", response=r)
    return r.json()
PasarGuardAPI.create_admin=_pg_create_admin


def _pg_update_admin(self, token, admin_id, **changes):
    import requests
    r=requests.put(f"{self.base_url}/api/admin/{admin_id}",headers=self._headers(token),json=changes,timeout=self.timeout,verify=self.verify_ssl)
    if not r.ok:
        detail=r.text[:2000]
        try: detail=str(r.json())[:2000]
        except Exception: pass
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {detail}",response=r)
    return r.json() if r.content else {}
PasarGuardAPI.update_admin=_pg_update_admin

def _pg_delete_admin(self, token, admin_id):
    import requests
    r=requests.delete(f"{self.base_url}/api/admin/{admin_id}",headers=self._headers(token),timeout=self.timeout,verify=self.verify_ssl)
    if not r.ok:
        detail=r.text[:2000]
        try: detail=str(r.json())[:2000]
        except Exception: pass
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {detail}",response=r)
    return r.json() if r.content else {}
PasarGuardAPI.delete_admin=_pg_delete_admin


def _pg_get_admin(self, token, admin_id):
    import requests
    r=requests.get(f"{self.base_url}/api/admin/{admin_id}",headers=self._headers(token),timeout=self.timeout,verify=self.verify_ssl)
    if not r.ok:
        detail=r.text[:2000]
        try: detail=str(r.json())[:2000]
        except Exception: pass
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {detail}",response=r)
    return r.json()
PasarGuardAPI.get_admin_by_id=_pg_get_admin
