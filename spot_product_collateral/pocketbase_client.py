import requests


class PocketBaseClient:
    def __init__(self, base_url: str, superuser_email: str, superuser_password: str):
        self.base_url = base_url.rstrip("/")
        self._superuser_email = superuser_email
        self._superuser_password = superuser_password
        self._token = None

    def _authenticate(self):
        resp = requests.post(
            f"{self.base_url}/api/collections/_superusers/auth-with-password",
            json={"identity": self._superuser_email, "password": self._superuser_password},
            timeout=10,
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]

    def _headers(self):
        if self._token is None:
            self._authenticate()
        return {"Authorization": self._token}

    def find_by_upc(self, collection: str, upc: str):
        resp = requests.get(
            f"{self.base_url}/api/collections/{collection}/records",
            params={"filter": f'upc="{upc}"'},
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json()["items"]
        return items[0] if items else None

    def create_record(self, collection: str, fields: dict, files: dict | None = None):
        if files:
            resp = requests.post(
                f"{self.base_url}/api/collections/{collection}/records",
                data=fields, files=files, headers=self._headers(), timeout=30,
            )
        else:
            resp = requests.post(
                f"{self.base_url}/api/collections/{collection}/records",
                json=fields, headers=self._headers(), timeout=10,
            )
        resp.raise_for_status()
        return resp.json()

    def update_record(self, collection: str, record_id: str, fields: dict, files: dict | None = None):
        if files:
            resp = requests.patch(
                f"{self.base_url}/api/collections/{collection}/records/{record_id}",
                data=fields, files=files, headers=self._headers(), timeout=30,
            )
        else:
            resp = requests.patch(
                f"{self.base_url}/api/collections/{collection}/records/{record_id}",
                json=fields, headers=self._headers(), timeout=10,
            )
        resp.raise_for_status()
        return resp.json()

    def upsert_by_upc(self, collection: str, upc: str, fields: dict, files: dict | None = None):
        existing = self.find_by_upc(collection, upc)
        if existing:
            return self.update_record(collection, existing["id"], fields, files=files)
        return self.create_record(collection, {**fields, "upc": upc}, files=files)
