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
