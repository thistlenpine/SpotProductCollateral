import json
from types import SimpleNamespace
from unittest.mock import patch

from spot_product_collateral.config import Config
from spot_product_collateral.pocketbase_client import PocketBaseClient
from spot_product_collateral.run import run_once
from spot_product_collateral.state import State
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


def test_run_once_continues_when_image_download_fails(pb_server, tmp_path):
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    with patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic, \
         patch("spot_product_collateral.run._download_image") as mock_download:
        mock_lookup.return_value = UpcLookupResult(
            found=True, name="Example Wine", description="desc",
            image_url="https://example.com/image.jpg",
        )
        mock_crawl.return_value = TastingProfileResult(found=True, tasting_profile="40% ABV", sources=["https://x"])
        mock_anthropic.return_value = SimpleNamespace(messages=None)
        mock_download.side_effect = RuntimeError("image download failed")

        manifest = run_once(config, [_item()], state_path, manifest_path)

    assert manifest["errors"] == []
    assert len(manifest["items"]) == 1
    assert manifest["items"][0]["upc"] == "111"
    assert manifest["items"][0]["status"] == "published"


def test_run_once_continues_past_per_item_failure_to_next_item(pb_server, tmp_path):
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    def lookup_side_effect(code, *args, **kwargs):
        if code == "111":
            raise RuntimeError("boom")
        return UpcLookupResult(found=True, name="Second Wine", description="desc2", image_url=None)

    with patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic:
        mock_lookup.side_effect = lookup_side_effect
        mock_crawl.return_value = TastingProfileResult(found=True, tasting_profile="40% ABV", sources=["https://x"])
        mock_anthropic.return_value = SimpleNamespace(messages=None)

        items = [_item(code="111", item_id=1), _item(code="222", item_id=2)]
        manifest = run_once(config, items, state_path, manifest_path)

    assert len(manifest["errors"]) == 1
    assert manifest["errors"][0]["upc"] == "111"
    assert "boom" in manifest["errors"][0]["error"]

    assert len(manifest["items"]) == 1
    assert manifest["items"][0]["upc"] == "222"


def test_run_once_writes_no_record_when_upc_lookup_is_rate_limited(pb_server, tmp_path):
    """A rate-limited lookup must not persist a snapshot hash, or the item is skipped forever."""
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    with patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic:
        mock_lookup.side_effect = RuntimeError("UPC lookup rate-limited for 111")
        mock_crawl.return_value = TastingProfileResult(found=True, tasting_profile="40% ABV", sources=["https://x"])
        mock_anthropic.return_value = SimpleNamespace(messages=None)

        manifest = run_once(config, [_item(code="111")], state_path, manifest_path)

    assert manifest["items"] == []
    assert len(manifest["errors"]) == 1
    assert manifest["errors"][0]["upc"] == "111"
    assert "rate-limited" in manifest["errors"][0]["error"]

    # Critically: no PocketBase record was written, so the item has no stored
    # snapshot hash and find_items_needing_enrichment will retry it next scan.
    pb_client = PocketBaseClient(pb_server.base_url, "admin@example.com", "hunter2")
    assert pb_client.find_by_upc("products", "111") is None
    assert pb_server.records.get("products", {}) == {}


def test_run_once_survives_scan_failure_and_increments_consecutive_failures(pb_server, tmp_path):
    """If the scan step itself raises, the run still writes a manifest and updates State."""
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    State(consecutive_failures=0, last_run=None, last_run_id=None).save(state_path)

    with patch("spot_product_collateral.run.find_items_needing_enrichment") as mock_scan, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic:
        mock_scan.side_effect = RuntimeError("pocketbase unreachable")
        mock_anthropic.return_value = SimpleNamespace(messages=None)

        manifest = run_once(config, [_item()], state_path, manifest_path)

    assert manifest["items"] == []
    assert len(manifest["errors"]) == 1
    assert manifest["errors"][0]["upc"] is None
    assert "scan failed: pocketbase unreachable" in manifest["errors"][0]["error"]
    assert manifest["verified"] is False

    # The manifest was still written to disk.
    with open(manifest_path) as f:
        assert json.load(f) == manifest

    saved_state = State.load(state_path)
    assert saved_state.consecutive_failures == 1


def test_run_once_manifest_includes_verified_key(pb_server, tmp_path):
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

    assert manifest["verified"] is True
    with open(manifest_path) as f:
        assert json.load(f)["verified"] is True


def test_run_once_increments_failures_and_preserves_last_run_on_verify_failure(pb_server, tmp_path):
    config = _config()
    config.pocketbase_url = pb_server.base_url
    state_path = str(tmp_path / "STATE.json")
    manifest_path = str(tmp_path / "manifest.json")

    State(consecutive_failures=0, last_run=None, last_run_id=None).save(state_path)

    with patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic, \
         patch("spot_product_collateral.run.verify_manifest") as mock_verify:
        mock_lookup.return_value = UpcLookupResult(found=True, name="Example Wine", description="desc", image_url=None)
        mock_crawl.return_value = TastingProfileResult(found=True, tasting_profile="40% ABV", sources=["https://x"])
        mock_anthropic.return_value = SimpleNamespace(messages=None)
        mock_verify.return_value = False

        run_once(config, [_item()], state_path, manifest_path)

    saved_state = State.load(state_path)
    assert saved_state.consecutive_failures == 1
    assert saved_state.last_run is None
    assert saved_state.last_run_id is None
