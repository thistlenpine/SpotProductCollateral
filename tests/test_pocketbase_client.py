import json

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


def test_create_record_with_files(pb_server):
    client = _client(pb_server)
    created = client.create_record(
        "products",
        {"upc": "555", "name": "Wine with Image"},
        files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")}
    )
    assert created["upc"] == "555"
    assert created["name"] == "Wine with Image"
    assert created["id"]
    # Verify we can find it
    found = client.find_by_upc("products", "555")
    assert found["name"] == "Wine with Image"


def test_create_record_with_files_encodes_lists_as_json_and_drops_none(pb_server):
    """Multipart requests must JSON-encode container values and drop None values."""
    client = _client(pb_server)
    created = client.create_record(
        "products",
        {
            "upc": "777",
            "name": "Wine with Image",
            "sources": ["https://a", "https://b"],
            "abv": None,
        },
        files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
    )

    stored = pb_server.records["products"][created["id"]]

    # The list arrived as a JSON string, not a Python repr.
    assert stored["sources"] == '["https://a", "https://b"]'
    assert json.loads(stored["sources"]) == ["https://a", "https://b"]

    # The None-valued field was dropped from the request entirely.
    assert "abv" not in stored

    assert stored["upc"] == "777"
    assert stored["name"] == "Wine with Image"


def test_update_record_with_files_encodes_lists_as_json_and_drops_none(pb_server):
    client = _client(pb_server)
    created = client.create_record("products", {"upc": "888", "name": "Before"})
    client.update_record(
        "products",
        created["id"],
        {"name": "After", "sources": ["https://c"], "abv": None},
        files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
    )

    stored = pb_server.records["products"][created["id"]]
    assert stored["name"] == "After"
    assert json.loads(stored["sources"]) == ["https://c"]
    assert "abv" not in stored


def test_upsert_by_upc_with_files(pb_server):
    client = _client(pb_server)
    record = client.upsert_by_upc(
        "products",
        "666",
        {"name": "New Wine with Image"},
        files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")}
    )
    assert record["upc"] == "666"
    assert record["name"] == "New Wine with Image"
