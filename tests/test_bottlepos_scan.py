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
