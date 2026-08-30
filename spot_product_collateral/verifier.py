_VALID_STATUSES = {"published", "needs_review"}


def verify_manifest(manifest: dict) -> bool:
    items = manifest.get("items")
    if not isinstance(items, list):
        return False
    for entry in items:
        if not isinstance(entry, dict):
            return False
        if not entry.get("upc"):
            return False
        if entry.get("status") not in _VALID_STATUSES:
            return False
    return True
