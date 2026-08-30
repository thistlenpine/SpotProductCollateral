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
