_VALID_STATUSES = {"published", "needs_review"}


def verify_manifest(manifest: dict) -> bool:
    items = manifest.get("items")
    if not isinstance(items, list):
        return False
    # Total-failure run: everything attempted errored out and nothing landed.
    # (An empty run with no errors is fine — nothing needed enrichment.)
    if items == [] and manifest.get("errors"):
        return False
    for entry in items:
        if not isinstance(entry, dict):
            return False
        if not entry.get("upc"):
            return False
        if entry.get("status") not in _VALID_STATUSES:
            return False
    return True
