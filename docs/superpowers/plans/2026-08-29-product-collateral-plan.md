# SpotProductCollateral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python enrichment pipeline that scans BottlePOS for products, looks up UPC data, crawls for tasting profiles via Claude's web search tool, and writes the results into SpotWeb's PocketBase instance — plus the weekly-loop scaffolding to run it.

**Architecture:** A `spot_product_collateral` Python package with one module per pipeline stage (scan, UPC lookup, crawl, enrich/write), a thin PocketBase REST client, and an orchestrator (`run.py`) that ties them together with state tracking and a deterministic verifier — mirroring the `SpotOrderRecommender` repo's pattern.

**Tech Stack:** Python 3.10+, `requests`, `anthropic` SDK, `pytest`, `BottleIntegrations`' `bottlepos` package (sibling repo dependency), PocketBase (hosted by the sibling `SpotWeb` repo).

**Spec:** `docs/superpowers/specs/2026-08-29-product-collateral-design.md`

## Global Constraints

- **Repo layout assumption:** `SpotProductCollateral`, `SpotWeb`, and `BottleIntegrations` are sibling directories under `C:\Users\thist\Spot Projects\` (confirmed present in this environment). `BottleIntegrations` is installed into this repo's virtualenv via `pip install -e ../BottleIntegrations` (its `bottlepos` package, per that repo's README).
- **Env vars (read via `os.environ`, no defaults for secrets):** `BOTTLE_URL`, `BOTTLE_USER`, `BOTTLE_PASS` (BottlePOS credentials, same names `SpotSalesForecasting`'s `runner/config.py::connect()` uses), `POCKETBASE_URL` (e.g. `http://127.0.0.1:8090`), `PB_SUPERUSER_EMAIL`, `PB_SUPERUSER_PASSWORD` (same PocketBase superuser account SpotWeb's `1764579159_create_superuser.js` migration provisions), `ANTHROPIC_API_KEY`.
- **Model:** all Claude API calls use `model="claude-opus-5"`.
- **Web search tool:** `{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}` — no beta header required.
- **UPC lookup API:** UPCitemdb trial endpoint, `GET https://api.upcitemdb.com/prod/trial/lookup?upc=<upc>`, no API key. Chosen for zero-signup access at the low weekly request volume this pipeline needs (confirm rate limits at the pre-run human gate per `HUMAN-GATES.md`).
- **Change-detection hash:** BottlePOS's `Item` has no update timestamp, so "changed since last enrichment" is determined by hashing `f"{item.name}|{item.description}|{item.category_name}"` with SHA-256 and comparing against the stored `bottlepos_snapshot_hash` field on the PocketBase record.
- **Confidence/status rule:** `confidence="high"`, `status="published"` when both the UPC lookup found a match AND the crawler found at least one source; otherwise `confidence="low"`, `status="needs_review"`.
- **PocketBase `products` collection fields:** `upc` (text, unique), `bottlepos_item_id` (text), `name` (text), `image` (file, single, image mimetypes), `description` (text), `tasting_profile` (text), `region` (text, always empty in this plan's scope — see Task 7), `abv` (number, nullable), `sources` (json array of strings), `confidence` (select: `high`/`low`), `status` (select: `published`/`needs_review`), `bottlepos_snapshot_hash` (text), `last_enriched_at` (date). Public read (`listRule`/`viewRule` = `""`), superuser-only write (`createRule`/`updateRule`/`deleteRule` = `null`) — matches the spec's resolution that SpotSommelier reads via plain public REST GET, no token needed.
- **Testing:** all external calls (BottlePOS, UPCitemdb, PocketBase, Anthropic) are mocked in tests. No live network calls in `pytest`. PocketBase is faked with a local `http.server` instance (per Task 2), matching `BottleIntegrations`' `mock_server.py` pattern of standing up a real local HTTP server rather than patching `requests`.
- **Scope limit (ruling):** Region is not parsed out of the crawler's free-text summary in this plan — it's covered in the `tasting_profile` text but the `region` field is always left empty. ABV *is* extracted via a simple regex (`\d+(\.\d+)?\s*%\s*ABV`) since that's mechanical and reliable; region extraction would need unreliable free-text parsing and is out of scope for v1.

---

### Task 1: Project scaffolding & config

**Files:**
- Create: `pyproject.toml`
- Create: `spot_product_collateral/__init__.py`
- Create: `spot_product_collateral/config.py`
- Create: `pytest.ini`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `spot_product_collateral.config.Config` — a dataclass with fields `bottle_url: str`, `bottle_user: str`, `bottle_pass: str`, `pocketbase_url: str`, `pb_superuser_email: str`, `pb_superuser_password: str`, `anthropic_api_key: str`, and classmethod `Config.from_env() -> "Config"` that reads the env vars listed in Global Constraints and raises `RuntimeError` naming the missing var if any is unset/empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from spot_product_collateral.config import Config

REQUIRED_VARS = [
    "BOTTLE_URL", "BOTTLE_USER", "BOTTLE_PASS",
    "POCKETBASE_URL", "PB_SUPERUSER_EMAIL", "PB_SUPERUSER_PASSWORD",
    "ANTHROPIC_API_KEY",
]


def _set_all(monkeypatch):
    values = {name: f"test-{name.lower()}" for name in REQUIRED_VARS}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_from_env_reads_all_vars(monkeypatch):
    values = _set_all(monkeypatch)
    config = Config.from_env()
    assert config.bottle_url == values["BOTTLE_URL"]
    assert config.bottle_user == values["BOTTLE_USER"]
    assert config.bottle_pass == values["BOTTLE_PASS"]
    assert config.pocketbase_url == values["POCKETBASE_URL"]
    assert config.pb_superuser_email == values["PB_SUPERUSER_EMAIL"]
    assert config.pb_superuser_password == values["PB_SUPERUSER_PASSWORD"]
    assert config.anthropic_api_key == values["ANTHROPIC_API_KEY"]


@pytest.mark.parametrize("missing", REQUIRED_VARS)
def test_from_env_raises_on_missing_var(monkeypatch, missing):
    _set_all(monkeypatch)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match=missing):
        Config.from_env()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spot_product_collateral'`

- [ ] **Step 3: Write minimal implementation**

```python
# spot_product_collateral/__init__.py
```

```python
# spot_product_collateral/config.py
import os
from dataclasses import dataclass

_REQUIRED = [
    "BOTTLE_URL", "BOTTLE_USER", "BOTTLE_PASS",
    "POCKETBASE_URL", "PB_SUPERUSER_EMAIL", "PB_SUPERUSER_PASSWORD",
    "ANTHROPIC_API_KEY",
]


@dataclass
class Config:
    bottle_url: str
    bottle_user: str
    bottle_pass: str
    pocketbase_url: str
    pb_superuser_email: str
    pb_superuser_password: str
    anthropic_api_key: str

    @classmethod
    def from_env(cls) -> "Config":
        values = {}
        for name in _REQUIRED:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            values[name] = value
        return cls(
            bottle_url=values["BOTTLE_URL"],
            bottle_user=values["BOTTLE_USER"],
            bottle_pass=values["BOTTLE_PASS"],
            pocketbase_url=values["POCKETBASE_URL"],
            pb_superuser_email=values["PB_SUPERUSER_EMAIL"],
            pb_superuser_password=values["PB_SUPERUSER_PASSWORD"],
            anthropic_api_key=values["ANTHROPIC_API_KEY"],
        )
```

```ini
# pytest.ini
[pytest]
testpaths = tests
```

```text
# requirements.txt
requests>=2.28
anthropic>=0.40
```

```text
# requirements-dev.txt
-r requirements.txt
pytest>=7.0
```

```toml
# pyproject.toml
[project]
name = "spot-product-collateral"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["requests>=2.28", "anthropic>=0.40"]

[tool.setuptools.packages.find]
include = ["spot_product_collateral*"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (8 tests: 1 + 7 parametrized)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml spot_product_collateral/__init__.py spot_product_collateral/config.py pytest.ini requirements.txt requirements-dev.txt tests/test_config.py
git commit -m "feat: project scaffolding and env-based config"
```

---

### Task 2: PocketBase client

**Files:**
- Create: `spot_product_collateral/pocketbase_client.py`
- Create: `tests/mock_pocketbase.py`
- Create: `tests/conftest.py`
- Test: `tests/test_pocketbase_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `spot_product_collateral.pocketbase_client.PocketBaseClient(base_url: str, superuser_email: str, superuser_password: str)` with methods:
  - `find_by_upc(collection: str, upc: str) -> dict | None`
  - `create_record(collection: str, fields: dict, files: dict[str, tuple[str, bytes, str]] | None = None) -> dict`
  - `update_record(collection: str, record_id: str, fields: dict, files: dict[str, tuple[str, bytes, str]] | None = None) -> dict`
  - `upsert_by_upc(collection: str, upc: str, fields: dict, files: dict | None = None) -> dict` — finds by `upc`, updates if found else creates (merging `upc` into `fields`).
  `files` values are `(filename, content_bytes, content_type)` tuples, passed straight to `requests`' `files=` param.

`tests/mock_pocketbase.py` exposes `MockPocketBaseServer` — a context manager that starts a local `http.server.HTTPServer` on `127.0.0.1` with an ephemeral port, implementing: `POST /api/collections/_superusers/auth-with-password` (returns a fixed fake token given any credentials), `GET /api/collections/{c}/records?filter=...` (in-memory store, supports `upc="<value>"` filter parsing), `POST /api/collections/{c}/records` (create, assigns an incrementing `id`), `PATCH /api/collections/{c}/records/{id}` (update). It exposes `.base_url` and `.records` (the in-memory dict) for assertions.

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import pytest
from tests.mock_pocketbase import MockPocketBaseServer


@pytest.fixture
def pb_server():
    with MockPocketBaseServer() as server:
        yield server
```

```python
# tests/test_pocketbase_client.py
from spot_product_collateral.pocketbase_client import PocketBaseClient


def _client(pb_server):
    return PocketBaseClient(
        base_url=pb_server.base_url,
        superuser_email="admin@example.com",
        superuser_password="hunter2",
    )


def test_find_by_upc_returns_none_when_absent(pb_server):
    client = _client(pb_server)
    assert client.find_by_upc("products", "000000000000") is None


def test_create_and_find_by_upc(pb_server):
    client = _client(pb_server)
    created = client.create_record("products", {"upc": "111", "name": "Test Wine"})
    assert created["upc"] == "111"
    found = client.find_by_upc("products", "111")
    assert found["id"] == created["id"]
    assert found["name"] == "Test Wine"


def test_update_record(pb_server):
    client = _client(pb_server)
    created = client.create_record("products", {"upc": "222", "name": "Old Name"})
    updated = client.update_record("products", created["id"], {"name": "New Name"})
    assert updated["name"] == "New Name"
    assert client.find_by_upc("products", "222")["name"] == "New Name"


def test_upsert_by_upc_creates_when_absent(pb_server):
    client = _client(pb_server)
    record = client.upsert_by_upc("products", "333", {"name": "Fresh"})
    assert record["upc"] == "333"
    assert record["name"] == "Fresh"


def test_upsert_by_upc_updates_when_present(pb_server):
    client = _client(pb_server)
    client.create_record("products", {"upc": "444", "name": "Before"})
    record = client.upsert_by_upc("products", "444", {"name": "After"})
    assert record["name"] == "After"
    assert len(pb_server.records["products"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pocketbase_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spot_product_collateral.pocketbase_client'` (and `tests.mock_pocketbase` missing)

- [ ] **Step 3: Write minimal implementation**

```python
# tests/mock_pocketbase.py
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

_FAKE_TOKEN = "fake-superuser-token"


class _Store:
    def __init__(self):
        self.records = {}  # collection -> {id: record}
        self._next_id = {}

    def next_id(self, collection):
        n = self._next_id.get(collection, 0) + 1
        self._next_id[collection] = n
        return f"rec{n}"


class _Handler(BaseHTTPRequestHandler):
    store: _Store = None  # set per-instance via server

    def log_message(self, format, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def do_POST(self):
        store = self.server.store
        if self.path == "/api/collections/_superusers/auth-with-password":
            self._read_json_body()
            self._send_json(200, {"token": _FAKE_TOKEN})
            return

        parts = self.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "collections" and parts[3] == "records":
            collection = parts[2]
            fields = self._read_json_body()
            record_id = store.next_id(collection)
            record = dict(fields)
            record["id"] = record_id
            store.records.setdefault(collection, {})[record_id] = record
            self._send_json(200, record)
            return

        self._send_json(404, {"error": "not found"})

    def do_PATCH(self):
        store = self.server.store
        parts = self.path.strip("/").split("/")
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "collections" and parts[3] == "records":
            collection, record_id = parts[2], parts[4]
            fields = self._read_json_body()
            record = store.records.get(collection, {}).get(record_id)
            if record is None:
                self._send_json(404, {"error": "not found"})
                return
            record.update(fields)
            self._send_json(200, record)
            return
        self._send_json(404, {"error": "not found"})

    def do_GET(self):
        store = self.server.store
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "collections" and parts[3] == "records":
            collection = parts[2]
            query = parse_qs(parsed.query)
            filter_expr = query.get("filter", [""])[0]
            items = list(store.records.get(collection, {}).values())
            if filter_expr:
                # only supports: upc="<value>"
                field, _, raw_value = filter_expr.partition("=")
                field = field.strip()
                value = raw_value.strip().strip('"')
                items = [r for r in items if r.get(field) == value]
            self._send_json(200, {"items": items})
            return
        self._send_json(404, {"error": "not found"})


class MockPocketBaseServer:
    def __enter__(self):
        self._store = _Store()
        self._httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.store = self._store
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.records = self._store.records
        return self

    def __exit__(self, exc_type, exc, tb):
        self._httpd.shutdown()
        self._httpd.server_close()
```

```python
# spot_product_collateral/pocketbase_client.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pocketbase_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add spot_product_collateral/pocketbase_client.py tests/mock_pocketbase.py tests/conftest.py tests/test_pocketbase_client.py
git commit -m "feat: PocketBase REST client with local mock server for tests"
```

---

### Task 3: PocketBase `products` collection migration (SpotWeb sibling repo)

**Files:**
- Create: `../SpotWeb/apps/pocketbase/pb_migrations/1798000000_created_products.js`

**Interfaces:**
- Consumes: nothing.
- Produces: the `products` PocketBase collection that Task 2's client and all later tasks read/write.

**Note:** this task edits a file in the sibling `SpotWeb` repository, not this one — SpotWeb owns the PocketBase instance being extended (see spec's Architecture section and Global Constraints). Commit this file with SpotWeb's own git repo, not this one's.

- [ ] **Step 1: Write the migration**

```javascript
// ../SpotWeb/apps/pocketbase/pb_migrations/1798000000_created_products.js
/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = new Collection({
    "createRule": null,
    "deleteRule": null,
    "fields": [
      {
        "autogeneratePattern": "[a-z0-9]{15}",
        "hidden": false,
        "id": "text_products_id",
        "max": 15,
        "min": 15,
        "name": "id",
        "pattern": "^[a-z0-9]+$",
        "presentable": false,
        "primaryKey": true,
        "required": true,
        "system": true,
        "type": "text"
      },
      {
        "hidden": false,
        "id": "text_products_upc",
        "name": "upc",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "text_products_bottlepos_item_id",
        "name": "bottlepos_item_id",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "text_products_name",
        "name": "name",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "file_products_image",
        "name": "image",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "file",
        "maxSelect": 1,
        "maxSize": 20971520,
        "mimeTypes": ["image/jpeg", "image/png", "image/gif", "image/webp"],
        "thumbs": []
      },
      {
        "hidden": false,
        "id": "text_products_description",
        "name": "description",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "text_products_tasting_profile",
        "name": "tasting_profile",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "text_products_region",
        "name": "region",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "number_products_abv",
        "name": "abv",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "number",
        "max": null,
        "min": null,
        "onlyInt": false
      },
      {
        "hidden": false,
        "id": "json_products_sources",
        "name": "sources",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "json",
        "maxSize": 0
      },
      {
        "hidden": false,
        "id": "select_products_confidence",
        "name": "confidence",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "select",
        "maxSelect": 1,
        "values": ["high", "low"]
      },
      {
        "hidden": false,
        "id": "select_products_status",
        "name": "status",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "select",
        "maxSelect": 1,
        "values": ["published", "needs_review"]
      },
      {
        "hidden": false,
        "id": "text_products_snapshot_hash",
        "name": "bottlepos_snapshot_hash",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "text",
        "autogeneratePattern": "",
        "max": 0,
        "min": 0,
        "pattern": ""
      },
      {
        "hidden": false,
        "id": "date_products_last_enriched_at",
        "name": "last_enriched_at",
        "presentable": false,
        "primaryKey": false,
        "required": false,
        "system": false,
        "type": "date",
        "max": "",
        "min": ""
      },
      {
        "hidden": false,
        "id": "autodate_products_created",
        "name": "created",
        "onCreate": true,
        "onUpdate": false,
        "presentable": false,
        "system": false,
        "type": "autodate"
      },
      {
        "hidden": false,
        "id": "autodate_products_updated",
        "name": "updated",
        "onCreate": true,
        "onUpdate": true,
        "presentable": false,
        "system": false,
        "type": "autodate"
      }
    ],
    "id": "pbc_products_collection",
    "indexes": ["CREATE UNIQUE INDEX `idx_products_upc` ON `products` (`upc`)"],
    "listRule": "",
    "name": "products",
    "system": false,
    "type": "base",
    "updateRule": null,
    "viewRule": ""
  });

  try {
    return app.save(collection);
  } catch (e) {
    if (e.message.includes("Collection name must be unique")) {
      console.log("Collection already exists, skipping");
      return;
    }
    throw e;
  }
}, (app) => {
  try {
    const collection = app.findCollectionByNameOrId("pbc_products_collection");
    return app.delete(collection);
  } catch (e) {
    if (e.message.includes("no rows in result set")) {
      console.log("Collection not found, skipping revert");
      return;
    }
    throw e;
  }
})
```

- [ ] **Step 2: Verify the migration applies**

Run (from `SpotWeb/apps/pocketbase`, per that repo's own README/dev setup): `npm run dev` (or the pocketbase binary's normal startup) and confirm the `products` collection appears in the PocketBase admin UI at `/_/`, with the fields above and public list/view rules.
Expected: collection created, no errors in the PocketBase server log.

- [ ] **Step 3: Commit (in the SpotWeb repo)**

```bash
cd "../SpotWeb"
git add apps/pocketbase/pb_migrations/1798000000_created_products.js
git commit -m "feat: add products collection for SpotProductCollateral"
```

---

### Task 4: BottlePOS scan/diff module

**Files:**
- Create: `spot_product_collateral/bottlepos_scan.py`
- Test: `tests/test_bottlepos_scan.py`

**Interfaces:**
- Consumes: `PocketBaseClient.find_by_upc` (Task 2).
- Produces: `spot_product_collateral.bottlepos_scan.snapshot_hash(item) -> str` and `spot_product_collateral.bottlepos_scan.find_items_needing_enrichment(items: list, pb_client: PocketBaseClient) -> list[tuple[Any, str]]` — `items` is a list of `bottlepos.models.Item`-shaped objects (only `.code`, `.name`, `.description`, `.category_name` are read, so tests can use a simple stand-in object/namedtuple). Returns a list of `(item, computed_hash)` pairs for items with no PocketBase record yet, or whose computed hash differs from the stored `bottlepos_snapshot_hash`. Items with a falsy `.code` are skipped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bottlepos_scan.py
from types import SimpleNamespace
from spot_product_collateral.bottlepos_scan import snapshot_hash, find_items_needing_enrichment
from spot_product_collateral.pocketbase_client import PocketBaseClient


def _item(code, name="Wine", description="A wine", category_name="RED WINE"):
    return SimpleNamespace(code=code, name=name, description=description, category_name=category_name)


def _client(pb_server):
    return PocketBaseClient(pb_server.base_url, "admin@example.com", "hunter2")


def test_hash_is_deterministic_for_same_fields():
    a = _item("111", name="Same", description="Same desc", category_name="RED WINE")
    b = _item("222", name="Same", description="Same desc", category_name="RED WINE")
    assert snapshot_hash(a) == snapshot_hash(b)


def test_hash_differs_when_name_changes():
    a = _item("111", name="Old Name")
    b = _item("111", name="New Name")
    assert snapshot_hash(a) != snapshot_hash(b)


def test_skips_items_with_no_code(pb_server):
    client = _client(pb_server)
    items = [_item(code=None), _item(code="")]
    assert find_items_needing_enrichment(items, client) == []


def test_new_item_needs_enrichment(pb_server):
    client = _client(pb_server)
    item = _item("333")
    result = find_items_needing_enrichment([item], client)
    assert len(result) == 1
    assert result[0][0] is item
    assert result[0][1] == snapshot_hash(item)


def test_unchanged_item_is_skipped(pb_server):
    client = _client(pb_server)
    item = _item("444")
    client.create_record("products", {
        "upc": "444",
        "name": "Wine",
        "confidence": "high",
        "status": "published",
        "bottlepos_snapshot_hash": snapshot_hash(item),
    })
    assert find_items_needing_enrichment([item], client) == []


def test_changed_item_needs_enrichment(pb_server):
    client = _client(pb_server)
    old_item = _item("555", name="Old Name")
    client.create_record("products", {
        "upc": "555",
        "name": "Old Name",
        "confidence": "high",
        "status": "published",
        "bottlepos_snapshot_hash": snapshot_hash(old_item),
    })
    new_item = _item("555", name="New Name")
    result = find_items_needing_enrichment([new_item], client)
    assert len(result) == 1
    assert result[0][0] is new_item
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bottlepos_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spot_product_collateral.bottlepos_scan'`

- [ ] **Step 3: Write minimal implementation**

```python
# spot_product_collateral/bottlepos_scan.py
import hashlib


def snapshot_hash(item) -> str:
    basis = f"{item.name}|{item.description}|{item.category_name}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def find_items_needing_enrichment(items, pb_client):
    to_enrich = []
    for item in items:
        if not item.code:
            continue
        new_hash = snapshot_hash(item)
        existing = pb_client.find_by_upc("products", item.code)
        if existing is None or existing.get("bottlepos_snapshot_hash") != new_hash:
            to_enrich.append((item, new_hash))
    return to_enrich
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bottlepos_scan.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add spot_product_collateral/bottlepos_scan.py tests/test_bottlepos_scan.py
git commit -m "feat: BottlePOS scan/diff module with hash-based change detection"
```

---

### Task 5: UPC lookup module

**Files:**
- Create: `spot_product_collateral/upc_lookup.py`
- Test: `tests/test_upc_lookup.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone HTTP client).
- Produces: `spot_product_collateral.upc_lookup.UpcLookupResult` (dataclass: `found: bool`, `name: str | None`, `image_url: str | None`, `description: str | None`) and `spot_product_collateral.upc_lookup.lookup_upc(upc: str, session=None) -> UpcLookupResult`. `session` defaults to the `requests` module itself (so `session.get(...)` works); tests pass a fake object with a `.get` method to avoid real HTTP calls.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_upc_lookup.py
from spot_product_collateral.upc_lookup import lookup_upc


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.last_call = None

    def get(self, url, params=None, timeout=None):
        self.last_call = (url, params, timeout)
        return self._response


def test_lookup_found_returns_populated_result():
    response = _FakeResponse(200, {
        "code": "OK",
        "items": [{
            "title": "Example Vodka 750ML",
            "description": "A smooth vodka.",
            "images": ["https://example.com/vodka.jpg", "https://example.com/other.jpg"],
        }],
    })
    session = _FakeSession(response)
    result = lookup_upc("012345678905", session=session)
    assert result.found is True
    assert result.name == "Example Vodka 750ML"
    assert result.description == "A smooth vodka."
    assert result.image_url == "https://example.com/vodka.jpg"
    assert session.last_call[1] == {"upc": "012345678905"}


def test_lookup_no_items_returns_not_found():
    response = _FakeResponse(200, {"code": "OK", "items": []})
    session = _FakeSession(response)
    result = lookup_upc("000000000000", session=session)
    assert result.found is False


def test_lookup_rate_limited_returns_not_found():
    response = _FakeResponse(429, {})
    session = _FakeSession(response)
    result = lookup_upc("000000000000", session=session)
    assert result.found is False


def test_lookup_no_images_leaves_image_url_none():
    response = _FakeResponse(200, {
        "code": "OK",
        "items": [{"title": "No Image Item", "description": "desc", "images": []}],
    })
    session = _FakeSession(response)
    result = lookup_upc("111", session=session)
    assert result.found is True
    assert result.image_url is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_upc_lookup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spot_product_collateral.upc_lookup'`

- [ ] **Step 3: Write minimal implementation**

```python
# spot_product_collateral/upc_lookup.py
from dataclasses import dataclass

import requests

UPCITEMDB_TRIAL_URL = "https://api.upcitemdb.com/prod/trial/lookup"


@dataclass
class UpcLookupResult:
    found: bool
    name: str | None = None
    image_url: str | None = None
    description: str | None = None


def lookup_upc(upc: str, session=None) -> UpcLookupResult:
    session = session or requests
    resp = session.get(UPCITEMDB_TRIAL_URL, params={"upc": upc}, timeout=10)
    if resp.status_code == 429:
        return UpcLookupResult(found=False)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items") or []
    if not items:
        return UpcLookupResult(found=False)
    item = items[0]
    images = item.get("images") or []
    return UpcLookupResult(
        found=True,
        name=item.get("title"),
        image_url=images[0] if images else None,
        description=item.get("description"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_upc_lookup.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add spot_product_collateral/upc_lookup.py tests/test_upc_lookup.py
git commit -m "feat: UPCitemdb lookup client"
```

---

### Task 6: Crawler module (Claude web search)

**Files:**
- Create: `spot_product_collateral/crawler.py`
- Test: `tests/test_crawler.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone; takes an injected Anthropic client).
- Produces: `spot_product_collateral.crawler.TastingProfileResult` (dataclass: `found: bool`, `tasting_profile: str | None`, `sources: list[str]`) and `spot_product_collateral.crawler.crawl_tasting_profile(product_name: str, client) -> TastingProfileResult`. `client` is a required parameter (an `anthropic.Anthropic`-shaped object with `.messages.create(...)`) — tests pass a fake, `run.py` (Task 8) passes a real `anthropic.Anthropic(api_key=...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crawler.py
from types import SimpleNamespace
from spot_product_collateral.crawler import crawl_tasting_profile


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _search_result_block(urls):
    return SimpleNamespace(
        type="web_search_tool_result",
        content=[SimpleNamespace(url=u) for u in urls],
    )


def test_crawl_with_sources_and_text_is_found():
    response = SimpleNamespace(content=[
        _text_block("This vodka has notes of citrus and pepper, ABV 40%."),
        _search_result_block(["https://example.com/a", "https://example.com/b"]),
    ])
    client = _FakeClient(response)
    result = crawl_tasting_profile("Example Vodka 750ML", client=client)
    assert result.found is True
    assert "citrus" in result.tasting_profile
    assert result.sources == ["https://example.com/a", "https://example.com/b"]
    assert client.messages.last_kwargs["model"] == "claude-opus-5"
    tools = client.messages.last_kwargs["tools"]
    assert tools[0]["type"] == "web_search_20260209"
    assert tools[0]["name"] == "web_search"


def test_crawl_with_no_sources_is_not_found():
    response = SimpleNamespace(content=[
        _text_block("I could not find reliable information."),
    ])
    client = _FakeClient(response)
    result = crawl_tasting_profile("Obscure Item", client=client)
    assert result.found is False
    assert result.sources == []


def test_crawl_with_no_text_is_not_found():
    response = SimpleNamespace(content=[
        _search_result_block(["https://example.com/a"]),
    ])
    client = _FakeClient(response)
    result = crawl_tasting_profile("Item", client=client)
    assert result.found is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spot_product_collateral.crawler'`

- [ ] **Step 3: Write minimal implementation**

```python
# spot_product_collateral/crawler.py
from dataclasses import dataclass, field


@dataclass
class TastingProfileResult:
    found: bool
    tasting_profile: str | None = None
    sources: list[str] = field(default_factory=list)


def crawl_tasting_profile(product_name: str, client) -> TastingProfileResult:
    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=1024,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        messages=[{
            "role": "user",
            "content": (
                f"Search the web for tasting notes, region of origin, and ABV for "
                f'the product "{product_name}". Write a short original summary in '
                "your own words (do not quote source text verbatim) covering "
                "tasting profile, region, and ABV if you can find them. If you "
                "cannot find reliable information, say so plainly."
            ),
        }],
    )

    text_parts = []
    sources = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "web_search_tool_result":
            content = block.content
            if isinstance(content, list):
                for result in content:
                    url = getattr(result, "url", None)
                    if url:
                        sources.append(url)

    summary = "\n".join(text_parts).strip()
    if not sources or not summary:
        return TastingProfileResult(found=False)
    return TastingProfileResult(found=True, tasting_profile=summary, sources=sources)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add spot_product_collateral/crawler.py tests/test_crawler.py
git commit -m "feat: Claude web-search-based tasting profile crawler"
```

---

### Task 7: Enrichment logic (confidence/status/record building)

**Files:**
- Create: `spot_product_collateral/enrichment.py`
- Test: `tests/test_enrichment.py`

**Interfaces:**
- Consumes: `UpcLookupResult` (Task 5), `TastingProfileResult` (Task 6), BottlePOS item shape from Task 4 (`.code`, `.name`, `.id`).
- Produces:
  - `spot_product_collateral.enrichment.determine_confidence_and_status(upc_result, tasting_result) -> tuple[str, str]` — returns `("high", "published")` when both `upc_result.found` and `tasting_result.found` are true, else `("low", "needs_review")`.
  - `spot_product_collateral.enrichment.extract_abv(text: str | None) -> float | None` — regex `\d+(\.\d+)?\s*%\s*ABV` (case-insensitive), returns the matched number as `float`, or `None` if no match or `text` is `None`.
  - `spot_product_collateral.enrichment.build_product_fields(item, snapshot_hash: str, upc_result, tasting_result, enriched_at: str) -> dict` — returns the PocketBase field dict per Global Constraints' field list (excluding `image`, which is handled separately as a file upload in Task 8), with `region` always `""` per the Global Constraints scope limit, `sources` as `tasting_result.sources`, and `name` falling back to `item.name` when `upc_result.name` is falsy.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrichment.py
from types import SimpleNamespace
from spot_product_collateral.enrichment import (
    determine_confidence_and_status,
    extract_abv,
    build_product_fields,
)
from spot_product_collateral.upc_lookup import UpcLookupResult
from spot_product_collateral.crawler import TastingProfileResult


def test_confidence_high_when_both_found():
    upc = UpcLookupResult(found=True, name="Wine")
    tasting = TastingProfileResult(found=True, tasting_profile="notes", sources=["https://x"])
    assert determine_confidence_and_status(upc, tasting) == ("high", "published")


def test_confidence_low_when_upc_not_found():
    upc = UpcLookupResult(found=False)
    tasting = TastingProfileResult(found=True, tasting_profile="notes", sources=["https://x"])
    assert determine_confidence_and_status(upc, tasting) == ("low", "needs_review")


def test_confidence_low_when_tasting_not_found():
    upc = UpcLookupResult(found=True, name="Wine")
    tasting = TastingProfileResult(found=False)
    assert determine_confidence_and_status(upc, tasting) == ("low", "needs_review")


def test_extract_abv_finds_percentage():
    assert extract_abv("This vodka is 40% ABV and citrusy.") == 40.0


def test_extract_abv_finds_decimal_percentage():
    assert extract_abv("Bottled at 13.5% ABV.") == 13.5


def test_extract_abv_returns_none_when_absent():
    assert extract_abv("No alcohol content mentioned.") is None


def test_extract_abv_returns_none_for_none_text():
    assert extract_abv(None) is None


def test_build_product_fields_uses_upc_name_when_present():
    item = SimpleNamespace(code="123", name="BottlePOS Name", id=42)
    upc = UpcLookupResult(found=True, name="Vendor Name", description="desc", image_url="https://img")
    tasting = TastingProfileResult(found=True, tasting_profile="40% ABV, citrus notes", sources=["https://x"])
    fields = build_product_fields(item, "hash123", upc, tasting, "2026-08-29T00:00:00Z")
    assert fields["upc"] == "123"
    assert fields["bottlepos_item_id"] == "42"
    assert fields["name"] == "Vendor Name"
    assert fields["description"] == "desc"
    assert fields["tasting_profile"] == "40% ABV, citrus notes"
    assert fields["region"] == ""
    assert fields["abv"] == 40.0
    assert fields["sources"] == ["https://x"]
    assert fields["confidence"] == "high"
    assert fields["status"] == "published"
    assert fields["bottlepos_snapshot_hash"] == "hash123"
    assert fields["last_enriched_at"] == "2026-08-29T00:00:00Z"


def test_build_product_fields_falls_back_to_item_name():
    item = SimpleNamespace(code="123", name="BottlePOS Name", id=42)
    upc = UpcLookupResult(found=False)
    tasting = TastingProfileResult(found=False)
    fields = build_product_fields(item, "hash123", upc, tasting, "2026-08-29T00:00:00Z")
    assert fields["name"] == "BottlePOS Name"
    assert fields["confidence"] == "low"
    assert fields["status"] == "needs_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_enrichment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spot_product_collateral.enrichment'`

- [ ] **Step 3: Write minimal implementation**

```python
# spot_product_collateral/enrichment.py
import re

_ABV_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*ABV", re.IGNORECASE)


def determine_confidence_and_status(upc_result, tasting_result):
    if upc_result.found and tasting_result.found:
        return "high", "published"
    return "low", "needs_review"


def extract_abv(text):
    if not text:
        return None
    match = _ABV_PATTERN.search(text)
    if not match:
        return None
    return float(match.group(1))


def build_product_fields(item, snapshot_hash, upc_result, tasting_result, enriched_at):
    confidence, status = determine_confidence_and_status(upc_result, tasting_result)
    return {
        "upc": item.code,
        "bottlepos_item_id": str(item.id),
        "name": upc_result.name or item.name,
        "description": upc_result.description or "",
        "tasting_profile": tasting_result.tasting_profile or "",
        "region": "",
        "abv": extract_abv(tasting_result.tasting_profile),
        "sources": tasting_result.sources,
        "confidence": confidence,
        "status": status,
        "bottlepos_snapshot_hash": snapshot_hash,
        "last_enriched_at": enriched_at,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_enrichment.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add spot_product_collateral/enrichment.py tests/test_enrichment.py
git commit -m "feat: enrichment confidence/status rule and PocketBase field builder"
```

---

### Task 8: Orchestrator, state tracking, and verifier

**Files:**
- Create: `spot_product_collateral/state.py`
- Create: `spot_product_collateral/verifier.py`
- Create: `spot_product_collateral/run.py`
- Test: `tests/test_state.py`
- Test: `tests/test_verifier.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `PocketBaseClient` (Task 2), `find_items_needing_enrichment`/`snapshot_hash` (Task 4), `lookup_upc` (Task 5), `crawl_tasting_profile` (Task 6), `build_product_fields` (Task 7).
- Produces:
  - `spot_product_collateral.state.State` (dataclass: `consecutive_failures: int`, `last_run: str | None`, `last_run_id: str | None`) with `State.load(path: str) -> "State"` (returns a zeroed/default `State` if the file doesn't exist — valid JSON dict with those three keys) and `.save(path: str) -> None` (writes JSON).
  - `spot_product_collateral.verifier.verify_manifest(manifest: dict) -> bool` — returns `True` iff `manifest["items"]` is a list and every entry has non-empty `upc` and a `status` in `{"published", "needs_review"}`; returns `False` (never raises) on any structural problem.
  - `spot_product_collateral.run.run_once(config, bottlepos_items: list, state_path: str, manifest_path: str) -> dict` — the orchestration function: builds a `PocketBaseClient` and `anthropic.Anthropic` client from `config`, calls `find_items_needing_enrichment`, and for each `(item, hash)` pair: calls `lookup_upc(item.code)`, calls `crawl_tasting_profile(item.name, client=...)`, builds fields via `build_product_fields`, and calls `pb_client.upsert_by_upc("products", item.code, fields, files=...)` — uploading the UPC lookup's `image_url` as the `image` file when present (download via `requests.get`, skip the upload gracefully — log and continue — if the download raises). Per-item exceptions are caught, logged to the returned manifest's `errors` list, and do not abort the run. Writes a manifest dict (`{"run_id": ..., "generated_at": ..., "items": [...], "errors": [...]}`) to `manifest_path`, runs it through `verify_manifest`, updates and saves `State` at `state_path` (increment `consecutive_failures` on `verify_manifest` returning `False`, else reset to 0 and set `last_run`/`last_run_id`), and returns the manifest dict. `run_id` is today's UTC date in `YYYY-MM-DD` form.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_state.py
import json
import os
from spot_product_collateral.state import State


def test_load_missing_file_returns_defaults(tmp_path):
    path = str(tmp_path / "STATE.json")
    state = State.load(path)
    assert state.consecutive_failures == 0
    assert state.last_run is None
    assert state.last_run_id is None


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "STATE.json")
    state = State(consecutive_failures=2, last_run="2026-08-29T00:00:00Z", last_run_id="2026-08-29")
    state.save(path)
    loaded = State.load(path)
    assert loaded.consecutive_failures == 2
    assert loaded.last_run == "2026-08-29T00:00:00Z"
    assert loaded.last_run_id == "2026-08-29"
    with open(path) as f:
        assert json.load(f)["consecutive_failures"] == 2
```

```python
# tests/test_verifier.py
from spot_product_collateral.verifier import verify_manifest


def test_valid_manifest_passes():
    manifest = {"items": [
        {"upc": "111", "status": "published"},
        {"upc": "222", "status": "needs_review"},
    ]}
    assert verify_manifest(manifest) is True


def test_empty_items_list_passes():
    assert verify_manifest({"items": []}) is True


def test_missing_items_key_fails():
    assert verify_manifest({}) is False


def test_item_missing_upc_fails():
    manifest = {"items": [{"status": "published"}]}
    assert verify_manifest(manifest) is False


def test_item_bad_status_fails():
    manifest = {"items": [{"upc": "111", "status": "bogus"}]}
    assert verify_manifest(manifest) is False
```

```python
# tests/test_run.py
import json
from types import SimpleNamespace
from unittest.mock import patch

from spot_product_collateral.config import Config
from spot_product_collateral.run import run_once
from spot_product_collateral.upc_lookup import UpcLookupResult
from spot_product_collateral.crawler import TastingProfileResult


def _config():
    return Config(
        bottle_url="http://bottlepos.example",
        bottle_user="user",
        bottle_pass="pass",
        pocketbase_url="http://pb.example",
        pb_superuser_email="admin@example.com",
        pb_superuser_password="hunter2",
        anthropic_api_key="fake-key",
    )


def _item(code="111", name="Example Wine", item_id=1, description="d", category_name="RED WINE"):
    return SimpleNamespace(code=code, name=name, id=item_id, description=description, category_name=category_name)


def test_run_once_writes_manifest_and_state(pb_server, tmp_path):
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    with patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic:
        mock_lookup.return_value = UpcLookupResult(found=True, name="Example Wine", description="desc", image_url=None)
        mock_crawl.return_value = TastingProfileResult(found=True, tasting_profile="40% ABV", sources=["https://x"])
        mock_anthropic.return_value = SimpleNamespace(messages=None)

        manifest = run_once(config, [_item()], state_path, manifest_path)

    assert manifest["errors"] == []
    assert len(manifest["items"]) == 1
    assert manifest["items"][0]["upc"] == "111"
    assert manifest["items"][0]["status"] == "published"

    with open(manifest_path) as f:
        assert json.load(f) == manifest

    with open(state_path) as f:
        state_data = json.load(f)
    assert state_data["consecutive_failures"] == 0
    assert state_data["last_run_id"] == manifest["run_id"]


def test_run_once_records_per_item_error_without_aborting(pb_server, tmp_path):
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    with patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic:
        mock_lookup.side_effect = RuntimeError("boom")
        mock_crawl.return_value = TastingProfileResult(found=False)
        mock_anthropic.return_value = SimpleNamespace(messages=None)

        manifest = run_once(config, [_item()], state_path, manifest_path)

    assert manifest["items"] == []
    assert len(manifest["errors"]) == 1
    assert "boom" in manifest["errors"][0]["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_state.py tests/test_verifier.py tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError` for `spot_product_collateral.state`, `.verifier`, and `.run`

- [ ] **Step 3: Write minimal implementation**

```python
# spot_product_collateral/state.py
import json
import os
from dataclasses import dataclass, asdict


@dataclass
class State:
    consecutive_failures: int = 0
    last_run: str | None = None
    last_run_id: str | None = None

    @classmethod
    def load(cls, path: str) -> "State":
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls(
            consecutive_failures=data.get("consecutive_failures", 0),
            last_run=data.get("last_run"),
            last_run_id=data.get("last_run_id"),
        )

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
```

```python
# spot_product_collateral/verifier.py
_VALID_STATUSES = {"published", "needs_review"}


def verify_manifest(manifest: dict) -> bool:
    items = manifest.get("items")
    if not isinstance(items, list):
        return False
    for entry in items:
        if not isinstance(entry, dict):
            return False
        if not entry.get("upc"):
            return False
        if entry.get("status") not in _VALID_STATUSES:
            return False
    return True
```

```python
# spot_product_collateral/run.py
import json
from datetime import datetime, timezone

import anthropic
import requests

from spot_product_collateral.bottlepos_scan import find_items_needing_enrichment
from spot_product_collateral.crawler import crawl_tasting_profile
from spot_product_collateral.enrichment import build_product_fields
from spot_product_collateral.pocketbase_client import PocketBaseClient
from spot_product_collateral.state import State
from spot_product_collateral.upc_lookup import lookup_upc
from spot_product_collateral.verifier import verify_manifest


def _download_image(url: str):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    filename = url.rsplit("/", 1)[-1] or "image.jpg"
    return {"image": (filename, resp.content, content_type)}


def run_once(config, bottlepos_items: list, state_path: str, manifest_path: str) -> dict:
    pb_client = PocketBaseClient(config.pocketbase_url, config.pb_superuser_email, config.pb_superuser_password)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y-%m-%d")
    manifest = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "items": [],
        "errors": [],
    }

    pending = find_items_needing_enrichment(bottlepos_items, pb_client)
    for item, item_hash in pending:
        try:
            upc_result = lookup_upc(item.code)
            tasting_result = crawl_tasting_profile(item.name, client=anthropic_client)
            fields = build_product_fields(item, item_hash, upc_result, tasting_result, now.isoformat())

            files = None
            if upc_result.image_url:
                try:
                    files = _download_image(upc_result.image_url)
                except Exception:
                    files = None

            pb_client.upsert_by_upc("products", item.code, fields, files=files)
            manifest["items"].append({"upc": item.code, "status": fields["status"]})
        except Exception as exc:
            manifest["errors"].append({"upc": getattr(item, "code", None), "error": str(exc)})

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    state = State.load(state_path)
    if verify_manifest(manifest):
        state.consecutive_failures = 0
        state.last_run = now.isoformat()
        state.last_run_id = run_id
    else:
        state.consecutive_failures += 1
    state.save(state_path)

    return manifest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state.py tests/test_verifier.py tests/test_run.py -v`
Expected: PASS (2 + 5 + 2 = 9 tests)

- [ ] **Step 5: Commit**

```bash
git add spot_product_collateral/state.py spot_product_collateral/verifier.py spot_product_collateral/run.py tests/test_state.py tests/test_verifier.py tests/test_run.py
git commit -m "feat: orchestrator, run state, and manifest verifier"
```

---

### Task 9: Loop scaffolding (SKILL.md, TRIGGER.md, HUMAN-GATES.md, STATE.md, run_weekly.ps1)

**Files:**
- Create: `SKILL.md`
- Create: `TRIGGER.md`
- Create: `HUMAN-GATES.md`
- Create: `STATE.md`
- Create: `run_weekly.ps1`
- Create: `main.py`

**Interfaces:**
- Consumes: `Config.from_env` (Task 1), `run_once` (Task 8). No new Python interfaces are produced — this task is documentation plus a thin CLI entry point.
- Produces: `main.py`'s `if __name__ == "__main__":` block, which loads `Config.from_env()`, fetches BottlePOS items via `bottlepos.BottlePOSClient(config.bottle_url, config.bottle_user, config.bottle_pass).list_items()`, and calls `run_once(config, items, "STATE.json", f"runs/{<today>}.json")`, creating the `runs/` directory if absent.

- [ ] **Step 1: Write `main.py`**

```python
# main.py
import os
from datetime import datetime, timezone

from bottlepos import BottlePOSClient

from spot_product_collateral.config import Config
from spot_product_collateral.run import run_once


def main():
    config = Config.from_env()
    bottlepos_client = BottlePOSClient(config.bottle_url, config.bottle_user, config.bottle_pass)
    items = bottlepos_client.list_items()

    os.makedirs("runs", exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    manifest_path = os.path.join("runs", f"{run_id}.json")

    manifest = run_once(config, items, "STATE.json", manifest_path)
    print(f"Run {manifest['run_id']}: {len(manifest['items'])} enriched, {len(manifest['errors'])} errors")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `SKILL.md`**

```markdown
---
name: product-collateral
description: >
  Self-running loop: for each BottlePOS item that is new or whose name,
  description, or category has changed since last enrichment, a PocketBase
  `products` record exists with UPC-sourced image/description and a
  crawler-sourced tasting profile, marked `published` when both sources were
  found or `needs_review` otherwise. Fires weekly and on manual request.
---

# product-collateral

## Goal

**Exit predicate (checked every run):** every BottlePOS item with a non-empty
UPC that is new or has a changed name/description/category since its last
enrichment has a `products` record in PocketBase with `confidence`/`status`
set per the rule below, and `runs/<run_id>.json` names every item processed
this run plus any per-item errors. This is a per-run predicate — the loop
produces a fresh incremental batch each time it fires, it does not drain a
queue across runs.

## Pattern: ReAct + deterministic verifier

Each run proceeds in order:

### 1. Read state

Load `STATE.json` (this repo's root). If `consecutive_failures >= 10`, STOP
immediately and raise the budget gate in `HUMAN-GATES.md` — do not run.

### 2. Discover

Fetch the full BottlePOS catalog via `BottleIntegrations`' `BottlePOSClient.list_items()`
(not `search_items()` — it needs a filter). Diff against PocketBase's
`products` collection via `spot_product_collateral.bottlepos_scan.find_items_needing_enrichment`,
which hashes each item's name/description/category and compares against the
stored `bottlepos_snapshot_hash`.

### 3. Act

For each item needing enrichment: look up the UPC via
`spot_product_collateral.upc_lookup.lookup_upc`, crawl for a tasting profile
via `spot_product_collateral.crawler.crawl_tasting_profile` (Claude web
search — writes an original summary, never republishes scraped text), build
the PocketBase fields via `spot_product_collateral.enrichment.build_product_fields`,
and upsert via `PocketBaseClient.upsert_by_upc`. A record is `confidence:
high, status: published` only when both the UPC lookup and the crawl found
something; otherwise `confidence: low, status: needs_review` and it waits for
manual review in the PocketBase admin UI — no separate review tool.

Per-item failures are caught and logged to the run's `errors` list; they do
not abort the run.

### 4. Verify

`spot_product_collateral.verifier.verify_manifest` checks every manifest
entry has a `upc` and a valid `status`. On failure, increment
`consecutive_failures` in `STATE.json` and STOP — do not silently retry. At
10 consecutive failures this trips the budget gate in `HUMAN-GATES.md`.

### 5. Write state

Update `STATE.json` regardless of pass/fail, per step 4.

### 6. Check exit predicate

If `runs/<run_id>.json` exists and the verifier passed, this run's goal
predicate holds. The loop waits for the next trigger (weekly cron or manual
request) to produce the next batch.

## How to run

Consult `TRIGGER.md` for the per-host invocation. Before the first live run,
clear gate G1 in `HUMAN-GATES.md`.

## What "done" means (per run)

- `runs/<run_id>.json` exists and the verifier returned `True` for it.
- `STATE.json` has an updated `last_run` timestamp.
- No open gate from `HUMAN-GATES.md` is blocking.

The loop never reaches a final "done" state — it recurs weekly. "Done"
applies per run, per the predicate above.
```

- [ ] **Step 3: Write `TRIGGER.md`**

```markdown
# product-collateral — Trigger Definition

## Verifiable goal (per run)

> Every BottlePOS item with a UPC that is new or changed since last
> enrichment has a PocketBase `products` record with confidence/status set
> per the rule in `SKILL.md`, and a run manifest exists naming every
> processed item and any errors.

## State files

```
STATE.json
runs/<run_id>.json
```

(All paths relative to this repo's root. Every run reads `STATE.json` at
startup and writes it before stopping.)

## Trigger 1: recurring schedule

**Cadence:** every Sunday at 8:00 AM (operator's local time) — chosen to run
after `SpotOrderRecommender`'s Sunday 7:00 AM job so the two don't contend
for the BottlePOS API at the same moment.

**Mechanism: Windows Task Scheduler** (same mechanism `SpotOrderRecommender`
uses — not `CronCreate`, which is session-only and dies with the Claude Code
process, and not the `schedule` skill's cloud routines, which have no access
to this machine's `.venv` or environment variables).

- **Task name:** `SpotProductCollateral Weekly`
- **Action:** runs `run_weekly.ps1` (this repo's root) via `powershell.exe`.
  If the full path contains spaces, use the 8.3 short path the same way
  `SpotOrderRecommender/TRIGGER.md` documents, rather than fighting
  `schtasks` quoting.
- **Schedule:** Weekly, Sunday, 8:00 AM, logon mode "Interactive only".
- **Created via:** `schtasks /create /tn "SpotProductCollateral Weekly" /tr
  "powershell.exe -NoProfile -ExecutionPolicy Bypass -File <path-to-run_weekly.ps1>"
  /sc WEEKLY /d SUN /st 08:00 /rl LIMITED /f` — re-verify this syntax against
  current `schtasks /create /?` output before creating it.

## Trigger 2: manual invocation

Ask the agent in chat, e.g.:

> Run the product-collateral loop now.

This loads `SKILL.md` fresh and proceeds through the same
read-state → discover → act → verify → write-state sequence.

## Launch prompt (host-agnostic fallback)

> Read `STATE.json` in this repo and the `product-collateral` skill's
> `SKILL.md`, then run the product-collateral loop.

## Trigger notes

- Gate G1 in `HUMAN-GATES.md` must be cleared before the recurring trigger is
  created.
- Since no human is present for the scheduled run, a newly-triggered gate
  gets recorded in `STATE.json` and the run stops rather than self-clearing —
  the next run stays blocked until a human clears it.
- The budget/stop limit (10 consecutive failures) in `HUMAN-GATES.md` takes
  precedence over the weekly cadence.
```

- [ ] **Step 4: Write `HUMAN-GATES.md`**

```markdown
# product-collateral — Human Gates & Budget

## Human gates

| # | Gate | Trigger condition | Who approves |
|---|------|-------------------|--------------|
| G1 | Pre-run sign-off | Before the first live run on real BottlePOS/PocketBase data. Must confirm: (a) the UPCitemdb trial endpoint's rate limits are acceptable for this catalog's weekly incremental volume, (b) UPC-sourced images may be stored and displayed on SpotSpirits.com, (c) the PocketBase `products` collection schema (Task 3's migration) matches what's actually deployed. | Loop owner |
| G2 | Verifier anomaly | `verify_manifest` returns `False` on any run | Loop owner |

### How to clear a gate

1. The loop writes a gate-request entry to `STATE.json` with the gate ID,
   reason, and proposed action.
2. A human reads the entry, confirms it's safe, and replies with an explicit
   approval in chat.
3. The loop records the approval in `STATE.json` and continues.

Never self-approve.

## Budget / stop

| Dimension | Limit | Action on breach |
|-----------|-------|-------------------|
| Max consecutive failed runs | 10 | Halt the loop; write `budget-exceeded` to `STATE.json`; wait for a human to diagnose and reset the counter |

Each run is a single weekly (or on-demand) batch, not an open-ended retry
loop, so no separate wall-clock or per-run iteration cap was added beyond
the consecutive-failure count.

## Single-worker note

This loop runs one worker at a time (weekly trigger or manual chat
invocation) against a single `STATE.json`. No parallel/worktree execution.
```

- [ ] **Step 5: Write initial `STATE.json`, `run_weekly.ps1`**

```json
{
  "consecutive_failures": 0,
  "last_run": null,
  "last_run_id": null
}
```

```powershell
# run_weekly.ps1
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

& "$repoRoot\.venv\Scripts\python.exe" "$repoRoot\main.py" *>> "$repoRoot\run_weekly.log"
```

- [ ] **Step 6: Verify `main.py` imports cleanly**

Run: `python -c "import main"`
Expected: no import errors (this only checks imports resolve; it does not run `main()`, which needs live credentials).

- [ ] **Step 7: Commit**

```bash
git add main.py SKILL.md TRIGGER.md HUMAN-GATES.md STATE.md run_weekly.ps1
git commit -m "feat: weekly loop scaffolding (SKILL, TRIGGER, HUMAN-GATES, entry point)"
```
