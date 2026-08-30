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
