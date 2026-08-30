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
