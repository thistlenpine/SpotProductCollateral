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
