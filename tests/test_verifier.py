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
